# agent/agent.py
import logging
import boto3
from strands import Agent
from strands.models import BedrockModel
from bedrock_agentcore.memory.session import MemorySessionManager
from .memory import MemoryHook


logger = logging.getLogger("blueprint-agent-memory")

def create_agent(all_mcp_tools, actor_id, session_id, agent_llm_config, prompt_management_config, guardrails_config) -> Agent:
    """
    Creates the Strands Agent.
    Currently using all tools from the Gateway, with filtering logic commented out.
    """
    logger.info("Initializing agent...")

    # Resolve the system prompt from Bedrock Prompt Management
    system_prompt = resolve_system_prompt(prompt_management_config)
    if not system_prompt:
        return None

    # Define the BedrockModel with parameters from config
    model = BedrockModel(
        model_id=agent_llm_config.llm.model_id,
        max_tokens=agent_llm_config.llm.max_tokens,
        temperature=agent_llm_config.llm.temperature,
        top_p=agent_llm_config.llm.top_p,
        region_name=agent_llm_config.llm.region_name,
        endpoint_url=agent_llm_config.llm.endpoint_url,
        guardrail_id=guardrails_config.guardrail_id,
        guardrail_version=guardrails_config.guardrail_version,
        guardrail_trace=guardrails_config.guardrail_trace,
        guardrail_stream_processing_mode=guardrails_config.guardrail_stream_processing_mode,
        guardrail_redact_input=guardrails_config.guardrail_redact_input,
        guardrail_redact_input_message=guardrails_config.guardrail_redact_input_message,
        guardrail_redact_output=guardrails_config.guardrail_redact_output,
        guardrail_redact_output_message=guardrails_config.guardrail_redact_output_message,
        guardrail_latest_message=guardrails_config.guardrail_latest_message,
    )

    # Create the MemoryHook
    memory_hook = config_memory_hook(actor_id, session_id, agent_llm_config)

    # Create the Agent with the model, hooks (memory), system prompt, tools, and initial state
    agent = Agent(
        model=model,
        hooks=[memory_hook],
        system_prompt=system_prompt,
        tools=all_mcp_tools,
    )

    logger.info(f"Agent initialized — actor_id={actor_id}, session_id={session_id}")
    return agent


def resolve_system_prompt(prompt_management_config) -> str | None:
    """
     Resolves the active system prompt based on prompt_management.json.
 
     The active section (key 'prompt_management') is read by read_prompt_management().
     The mode is derived directly from the fields present:
     - 'system_prompt_path' set → reads the prompt from that .txt file.
     - Otherwise               → fetches the prompt version from SSM Parameter Store
                                 and retrieves the text from Bedrock Prompt Management.
 
     The active mode is determined by which section in prompt_management.json has
     the key 'prompt_management' (vs 'prompt_management_disabled').

    Args:
        prompt_management_config: Prompt management configuration

    Returns:
        The system prompt string, or None if resolution fails.
    """
    try:
        if prompt_management_config.system_prompt_path:
            path = prompt_management_config.system_prompt_path
            with open(path, "r", encoding="utf-8") as f:
                system_prompt = f.read().strip()
            if not system_prompt:
                raise ValueError(f"Prompt file '{path}' is empty.")
            logger.info(f"System prompt loaded from file: {path}")
            return system_prompt
 
         # Default: Bedrock Prompt Management + SSM
        prompt_version = get_prompt_version_from_ssm(
            prompt_management_config.param_name_version,
            prompt_management_config.region,
        )
        logger.info(f"Resolved prompt version: {prompt_version}")

        system_prompt = get_prompt_management(
            prompt_management_config.prompt_id,
            prompt_version,
            prompt_management_config.region,
        )
        logger.info("System prompt successfully loaded from Bedrock Prompt Management")
        return system_prompt
    except Exception as e:
        logger.error(f"Agent initialization failed: {e}")
        return None


def get_prompt_version_from_ssm(param_name: str, region: str) -> str:
    """
    Fetch the current prompt version string from AWS SSM Parameter Store.

    Args:
        param_name: Name of the SSM parameter that holds the prompt version.
        region: AWS region where the SSM parameter is stored.

    Returns:
        The prompt version string.
    """
    ssm_client = boto3.client("ssm", region_name=region)
    try:
        response = ssm_client.get_parameter(Name=param_name)
    except ssm_client.exceptions.ParameterNotFound:
        raise ValueError(f"SSM parameter '{param_name}' not found in region '{region}'.")
    except Exception as e:
        raise RuntimeError(f"Error fetching SSM parameter '{param_name}': {e}") from e
    return response["Parameter"]["Value"].strip()


def get_prompt_management(prompt_id: str, version: str, region: str) -> str:
    """
    Retrieve the prompt text for a given version from Bedrock Prompt Management.

    Args:
        prompt_id: ARN or ID of the Bedrock prompt.
        version: Version of the prompt to retrieve.
        region: AWS region where the prompt is stored.

    Returns:
        The system prompt text string.
    """
    bedrock_client = boto3.client("bedrock-agent", region_name=region)

    try:
        response = bedrock_client.get_prompt(
            promptIdentifier=prompt_id,
            promptVersion=version,
        )
    except bedrock_client.exceptions.ResourceNotFoundException:
        raise ValueError(f"Prompt '{prompt_id}' version '{version}' not found in Bedrock Prompt Management (region: '{region}').")
    except bedrock_client.exceptions.AccessDeniedException:
        raise PermissionError(f"Access denied fetching prompt '{prompt_id}'. Check IAM permissions for bedrock:GetPrompt.")
    except Exception as e:
        raise RuntimeError(f"Error fetching prompt '{prompt_id}' version '{version}': {e}") from e

    # Prefer variants[0] (usually the full object); fallback to defaultVariant
    selected_variant = None

    variant_list = response.get("variants")
    if isinstance(variant_list, list) and variant_list and isinstance(variant_list[0], dict):
        selected_variant = variant_list[0]

    if selected_variant is None:
        default_variant = response.get("defaultVariant")
        if isinstance(default_variant, dict):
            selected_variant = default_variant

    if selected_variant is None:
        raise RuntimeError(
            "Prompt Management response has no usable variant object (variants/defaultVariant)"
        )

    template_config = selected_variant.get("templateConfiguration", {})
    system_prompt = template_config.get("text", {}).get("text", "")

    if not system_prompt:
        raise ValueError(f"Prompt '{prompt_id}' version '{version}' returned an empty prompt text.")

    return system_prompt


def config_memory_hook(actor_id: str, session_id: str, agent_llm_config) -> MemoryHook:
    """
    Creates a MemoryHook scoped to the current user and session.
    Opens a MemorySession via MemorySessionManager and wires it into a
    MemoryHook instance configured with the STM/LTM parameters from config.

    Args:
        actor_id: Identifier of the user making the request.
        session_id: Identifier of the current conversation session.
        agent_llm_config: Full agent and LLM configuration settings.

    Returns:
        A configured MemoryHook instance.
    """
    session_manager = MemorySessionManager(
        memory_id=agent_llm_config.memory.memory_id,
        region_name=agent_llm_config.llm.region_name,
    )
    mem_session = session_manager.create_memory_session(actor_id=actor_id, session_id=session_id)

    memory_hook = MemoryHook(
        actor_id=actor_id,
        memory_session=mem_session,
        ltm_namespaces=agent_llm_config.memory.ltm_namespaces,
        enable_stm=agent_llm_config.memory.enable_stm,
        enable_ltm=agent_llm_config.memory.enable_ltm,
        stm_k=agent_llm_config.memory.stm_k,
        ltm_top_k=agent_llm_config.memory.ltm_top_k,
        min_relevance_score=agent_llm_config.memory.min_relevance_score,
        user_query_delimiter=agent_llm_config.memory.user_query_delimiter,
        ltm_header=agent_llm_config.memory.ltm_header,
    )

    memory_status = []
    if agent_llm_config.memory.enable_stm:
        memory_status.append("STM enabled")
    if agent_llm_config.memory.enable_ltm:
        memory_status.append("LTM enabled")
    logger.info(f"MemoryHook created: {', '.join(memory_status) if memory_status else 'Memory disabled'}")

    return memory_hook