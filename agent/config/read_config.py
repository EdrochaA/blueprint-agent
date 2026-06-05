import json
import os
import boto3
from .config_dto import AgentLLMConfigDTO, GatewayConfig, LLMConfig, AgentConfig, MemoryConfig


def resolve_gateway_id(config: GatewayConfig, region: str) -> str:
    """Resolve the AgentCore Gateway ID from SSM Parameter Store.

    Args:
        config: GatewayConfig instance
        region: AWS region for SSM client

    Returns:
        The resolved gateway_id string

    Raises:
        ValueError: If ssm_parameter_name is not configured
    """
    if config.ssm_parameter_name:
        ssm = boto3.client("ssm", region_name=region)
        response = ssm.get_parameter(Name=config.ssm_parameter_name)
        return response["Parameter"]["Value"]
    raise ValueError(
        "GatewayConfig requires 'ssm_parameter_name' to be set"
    )


def is_gateway_enabled(config: GatewayConfig) -> bool:
    """Return True if the GatewayConfig contains enough information to connect.

    A GatewayConfig is considered enabled when ssm_parameter_name is a non-empty string.

    Args:
        config: GatewayConfig instance (may have all-None fields)

    Returns:
        True if gateway is enabled, False otherwise
    """
    return bool(config.ssm_parameter_name)


def read_config(config_path: str = "config/config.json") -> AgentLLMConfigDTO:
    """Read config.json and return AgentLLMConfigDTO object.

    Args:
        config_path: Path to config.json file

    Returns:
        AgentLLMConfigDTO object with nested LLM, Agent, Gateway and Memory configs
    """
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Extract LLM data
    llm = data.get("llm", {})
    connection = llm.get("connection", {})
    model = llm.get("model", {})

    # Extract Agent data
    agent = data.get("agent", {})
    metadata = agent.get("metadata", {})

    # Extract Gateway data
    gateway = data.get("gateway", {})

    # Extract Memory data
    memory = data.get("memory", {})

    llm_config = LLMConfig(
        model_id=os.getenv("BEDROCK_MODEL_ID") or model.get("model_id"),
        region_name=connection.get("region_name"),
        endpoint_url=connection.get("endpoint_url"),
        max_tokens=model.get("max_tokens"),
        temperature=model.get("temperature"),
        top_p=model.get("top_p"),
    )

    agent_config = AgentConfig(
        agent_id=metadata.get("agent_id"),
        agent_name=metadata.get("name"),
        agent_description=metadata.get("description"),
    )

    gateway_config = GatewayConfig(
        ssm_parameter_name=gateway.get("ssm_parameter_name"),
        mcp_target_name=gateway.get("mcp_target_name"),
    )

    memory_config = MemoryConfig(
        enable_stm=memory.get("enable_stm", True),
        enable_ltm=memory.get("enable_ltm", True),
        memory_id=memory.get("memory_id"),
        stm_k=memory.get("stm_k", 5),
        ltm_top_k=memory.get("ltm_top_k", 3),
        min_relevance_score=memory.get("min_relevance_score", 0.3),
        ltm_namespaces=memory.get("ltm_namespaces"),
        user_query_delimiter=memory.get("user_query_delimiter", "[Consulta actual del usuario]"),
        ltm_header=memory.get("ltm_header", "[Contexto de memoria a largo plazo del usuario]"),
    )

    return AgentLLMConfigDTO(
        llm=llm_config,
        agent=agent_config,
        gateway=gateway_config,
        memory=memory_config,
    )
