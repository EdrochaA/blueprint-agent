import os
import logging
import traceback
import uuid
import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient
from .agent import create_agent
from .config.read_config import read_config, resolve_gateway_id, is_gateway_enabled
from .config.read_prompt_management import read_prompt_management
from .config.read_guardrails import read_guardrails


# Implement logging
logging.basicConfig(
    format="%(levelname)s | %(message)s",
)
logger = logging.getLogger("blueprint-agent-memory")
logger.setLevel(logging.INFO)

app = BedrockAgentCoreApp()

agent_llm_config = read_config("agent/config/config.json")
logger.debug(f"Read config: {agent_llm_config}")

prompt_management_config = read_prompt_management("agent/config/prompt_management.json")
logger.debug(f"Read prompt management config: {prompt_management_config}")

guardrails_config = read_guardrails(
    "agent/config/guardrails.json",
    region=agent_llm_config.llm.region_name,
)
logger.debug(f"Read guardrails config: {guardrails_config}")

# Configuration constants
REGION = agent_llm_config.llm.region_name
if is_gateway_enabled(agent_llm_config.gateway):
    GATEWAY_ID: str | None = resolve_gateway_id(agent_llm_config.gateway, REGION)
    logger.debug(f"Gateway-Enabled Mode — GATEWAY_ID={GATEWAY_ID}, REGION={REGION}")
else:
    GATEWAY_ID = None
    logger.debug("Gateway-Disabled Mode — no gateway configuration found; MCP tools will not be loaded")


def _extract_authorization_header(context):
    request_headers = getattr(context, "request_headers", None)
    if request_headers is None:
        return None
    if isinstance(request_headers, dict):
        return request_headers.get("Authorization")
    return request_headers


def _get_session_id(context) -> str:
    session_id = getattr(context, "session_id", None)
    return session_id or f"sandbox-session-{uuid.uuid4().hex}"


async def _run_agent(all_mcp_tools: list, actor_id: str, session_id: str, user_input: str):
    """Run the agent with the given tools and return the response.

    Args:
        all_mcp_tools: List of MCP tools to pass to the agent (may be empty)
        actor_id: The actor/user identifier for memory scoping
        session_id: The session identifier
        user_input: The user's input prompt

    Returns:
        The agent's text response, or an error string
    """
    _agent = create_agent(
        all_mcp_tools=all_mcp_tools,
        actor_id=actor_id,
        session_id=session_id,
        agent_llm_config=agent_llm_config,
        prompt_management_config=prompt_management_config,
        guardrails_config=guardrails_config,
    )

    if _agent is None:
        logger.error("Cannot process request: agent is not initialized due to a startup error.")
        return "Agent unavailable. Check logs for initialization errors."

    response = await _agent.invoke_async(user_input)

    logger.debug(f"Full response: {response}")

    try:
        return response.message["content"][0]["text"]
    except (AttributeError, KeyError, TypeError) as e:
        logger.error(f"Error processing response: {e}")
        return str(response)


@app.entrypoint
async def invoke_agent(payload, context=None):
    """
    Main entrypoint for the Memory Agent.

    Identity is validated at the inbound layer (Cognito JWT authorizer
    configured in deploy.py).  The agent itself does NOT decode the JWT.

    When LTM is enabled, actor_id must be provided explicitly in the payload
    so the MemoryHook can scope memory data to the correct user namespace.

    Expected payload:
        {
            "prompt":   "...",
            "actor_id": "testMemoryLTM1"   # or "username": "testMemoryLTM1"
        }

    For sandbox/manual tests the invocation may arrive without request headers.
    In that case the runtime continues if the configured Gateway does not
    require caller JWT forwarding.
    """
    logger.info(f"Received payload: {payload}")
    session_id = _get_session_id(context)

    logger.info(f"Context session_id: {session_id}")

    auth_header = _extract_authorization_header(context)
    if not auth_header:
        logger.info("Header 'Authorization' not found in context; proceeding without it. ")
    else:
        logger.info("Authorization header extracted from context.")

    user_input = payload.get("prompt")
    if user_input is None:
        logger.error("Missing 'prompt' field in payload")
        return "ERROR: Missing 'prompt' field in payload"

    actor_id = payload.get("actor_id") or payload.get("username")
    if not actor_id:
        if agent_llm_config.memory.enable_ltm:
            logger.error("Missing 'actor_id' (or 'username') field in payload")
            return "ERROR: Missing 'actor_id' (or 'username') field in payload"

        actor_id = "anonymous"
        logger.info("LTM disabled: using fallback actor_id='anonymous'")

    logger.info(f"actor_id={actor_id}, session_id={session_id}")

    try:
        if GATEWAY_ID is not None:
            # Gateway-Enabled: fetch URL, load tools via MCPClient
            gateway_client = boto3.client("bedrock-agentcore-control", region_name=REGION)
            gateway_response = gateway_client.get_gateway(gatewayIdentifier=GATEWAY_ID)
            gateway_url = gateway_response.get("gatewayUrl")

            if not gateway_url:
                logger.error("Gateway URL not found in response")
                return "Error: Could not retrieve Gateway URL"

            # Initialize MCP client and list tools on each invocation to ensure we have the latest toolset from the Gateway.
            # Build headers dynamically: only include Authorization if present
            headers = {}
            if auth_header:
                headers["Authorization"] = auth_header
                logger.info(f"[FORWARDING] Authorization header forwarded to gateway")
            else:
                logger.info("[FORWARDING] Empty headers dict {} passed to gateway")
            
            mcp_client = MCPClient(
                lambda: streamablehttp_client(
                    url=gateway_url,
                    headers=headers,
                )
            )

            with mcp_client:
                all_mcp_tools = mcp_client.list_tools_sync()
                logger.info(f"Available MCP tools: {len(all_mcp_tools)}")
                return await _run_agent(all_mcp_tools, actor_id, session_id, user_input)
        else:
            # Gateway-Disabled: empty tool list, no network calls
            logger.info("Running agent without MCP tools")
            return await _run_agent([], actor_id, session_id, user_input)

    except Exception as e:
        error_msg = f"Runtime error: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return error_msg


if __name__ == "__main__":
    app.run()
