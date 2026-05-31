from dataclasses import dataclass


@dataclass
class LLMConfig:
    """LLM configuration.

    It contains LLM connection parameters and model parameters.

    Attributes:
        model_id: The Bedrock model ID
        region_name: AWS region to use for the Bedrock service
        endpoint_url: Custom endpoint URL for VPC endpoints (PrivateLink)
        max_tokens: Maximum number of tokens to generate in the response
        temperature: Controls randomness in generation (higher = more random)
        top_p: Controls diversity via nucleus sampling (higher = more diverse)
    """
    model_id: str
    region_name: str | None = "eu-central-1"
    endpoint_url: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None


@dataclass
class AgentConfig:
    """Agent configuration.
    
    It contains agent metadata and the system prompt that defines the agent's behavior.

    Attributes:
        agent_id: Optional ID for the agent, useful for session management and multi-agent scenarios
        agent_name: Optional name of the Agent
        agent_description: Optional description of what the Agent does
    """
    agent_id: str | None = None
    agent_name: str | None = None
    agent_description: str | None = None


@dataclass
class GatewayConfig:
    """Gateway metadata

    It contains the AgentCore Gateway ID. All fields are optional to support
    Gateway-Disabled Mode when no gateway configuration is present.

    Attributes:
        ssm_parameter_name: Optional name of the SSM parameter that contains the gateway_id.
            If both gateway_id and ssm_parameter_name are provided, gateway_id takes precedence.  
        mcp_target_name: Optional name of the MCP target that contains the gateway_id.
            If both gateway_id and mcp_target_name are provided, gateway_id takes precedence. 
    """
    ssm_parameter_name: str | None = None
    mcp_target_name: str | None = None


@dataclass
class MemoryConfig:
    """Memory configuration for STM (Short-Term Memory) and LTM (Long-Term Memory).
    
    It contains memory session parameters and behavior flags.

    Attributes:
        enable_stm: Enable/disable Short-Term Memory (recent conversation context)
        enable_ltm: Enable/disable Long-Term Memory (persistent user context)
        memory_id: AgentCore Memory resource identifier
        stm_k: Number of recent conversation turns to load for STM
        ltm_top_k: Number of top relevant long-term memories to retrieve
        min_relevance_score: Minimum relevance threshold for LTM retrieval (0.0 to 1.0)
        ltm_namespaces: List of namespace templates for LTM (use {actorId} placeholder)
        user_query_delimiter: Delimiter text to mark the start of user query in prompts
        ltm_header: Header text for injected LTM context
    """
    enable_stm: bool = True
    enable_ltm: bool = True
    memory_id: str | None = None
    stm_k: int = 5
    ltm_top_k: int = 3
    min_relevance_score: float = 0.3
    ltm_namespaces: list[str] | None = None
    user_query_delimiter: str = "[Consulta actual del usuario]"
    ltm_header: str = "[Contexto de memoria a largo plazo del usuario]"


@dataclass
class AgentLLMConfigDTO:
    """Root DTO containing nested LLM, Agent, Gateway and Memory configurations.

    Attributes:
        llm: LLM configuration with connection and model parameters
        agent: Agent configuration with metadata and system prompt
        gateway: Gateway configuration with MCP tools settings
        memory: Memory configuration with STM/LTM settings
    """
    llm: LLMConfig
    agent: AgentConfig
    gateway: GatewayConfig
    memory: MemoryConfig
