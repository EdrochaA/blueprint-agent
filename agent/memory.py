import logging
from typing import Optional

from strands.hooks import (
    AfterInvocationEvent,
    AgentInitializedEvent,
    HookProvider,
    HookRegistry,
    MessageAddedEvent,
)

from bedrock_agentcore.memory.constants import ConversationalMessage, MessageRole
from bedrock_agentcore.memory.session import MemorySession


logger = logging.getLogger("blueprint-agent-memory")

class MemoryHook(HookProvider):
    """
    Manages STM + LTM using a single AgentCore Memory resource.

    - STM (on_agent_initialized):
        Loads last K turns and injects into system prompt.

    - LTM retrieval (on_message_added):
        Searches long-term memories for the user's query and injects into the message.

    - Persistence (save_interaction):
        After model invocation, stores user+assistant messages via add_turns().
        LTM strategies are processed asynchronously by the memory resource.
    """

    def __init__(
        self,
        actor_id: str,
        memory_session: MemorySession,
        ltm_namespaces: list[str],
        *,
        enable_stm: bool = True,
        enable_ltm: bool = True,
        stm_k: int = 5,
        ltm_top_k: int = 3,
        min_relevance_score: float = 0.3,
        user_query_delimiter: str = "[Consulta actual del usuario]",
        ltm_header: str = "[Contexto de memoria a largo plazo del usuario]",
    ) -> None:
        self.actor_id = actor_id
        self.memory_session = memory_session
        self.ltm_namespaces = ltm_namespaces
        self.enable_stm = enable_stm
        self.enable_ltm = enable_ltm
        self.stm_k = stm_k
        self.ltm_top_k = ltm_top_k
        self.min_relevance_score = min_relevance_score
        self.user_query_delimiter = user_query_delimiter
        self.ltm_header = ltm_header

    # ----------------------------
    # STM: load recent turns at agent init
    # ----------------------------
    def on_agent_initialized(self, event: AgentInitializedEvent):
        # If STM is disabled, do nothing (disable STM)
        if not self.enable_stm:
            logger.info("STM: Disabled by configuration")
            return
            
        try:
            recent_turns = self.memory_session.get_last_k_turns(k=self.stm_k)

            if not recent_turns:
                logger.info("STM: No previous conversation history found")
                return

            context_messages: list[str] = []
            for turn in recent_turns:
                for message in turn:
                    # tolerate variability in message format
                    role = message.get("role", "unknown") if isinstance(message, dict) else getattr(message, "role", "unknown")
                    if isinstance(message, dict):
                        content = message.get("content", {}).get("text", "") if isinstance(message.get("content"), dict) else message.get("content", "")
                    else:
                        content = getattr(message, "content", "")
                    context_messages.append(f"{role}: {content}")

            context = "\n".join(context_messages)

            event.agent.system_prompt += (
                f"\n\nRecent conversation history:\n{context}\n\n"
                "Continue the conversation naturally based on this context."
            )
            logger.info(f"STM: Loaded {len(recent_turns)} recent turns")

        except Exception as e:
            logger.error(f"STM load error: {e}", exc_info=True)

    # ----------------------------
    # LTM: retrieve and inject into user messages
    # ----------------------------
    def on_message_added(self, event: MessageAddedEvent):
        # If LTM is disabled, do nothing (disable LTM)
        if not self.enable_ltm:
            return
            
        messages = event.agent.messages
        if not messages:
            return

        last = messages[-1]
        content = last.get("content", [{}])
        if not content or not isinstance(content[0], dict):
            return

        # only inject on real user text messages (not tool results)
        if last.get("role") != "user" or "toolResult" in content[0]:
            return

        user_query = content[0].get("text", "")
        actor_id = self.actor_id
        if not user_query or not actor_id:
            return

        self._inject_ltm_context(content[0], user_query, actor_id)

    # ----------------------------
    # Persist: store last user+assistant pair after invocation
    # ----------------------------
    def save_interaction(self, event: AfterInvocationEvent):
        try:
            messages = event.agent.messages
            if not messages or len(messages) < 2:
                logger.warning("save_interaction: not enough messages to store")
                return

            agent_response = self._extract_last_assistant_text(messages)
            if not agent_response:
                logger.warning("save_interaction: no assistant text found")
                return

            customer_query = self._extract_last_user_text(messages)
            if not customer_query:
                logger.warning("save_interaction: no user query found")
                return

            interaction_messages = [
                ConversationalMessage(customer_query, MessageRole.USER),
                ConversationalMessage(agent_response, MessageRole.ASSISTANT),
            ]
            result = self.memory_session.add_turns(messages=interaction_messages)
            logger.info(f"Memory: Stored conversation pair — Event ID: {result.get('eventId')}")

        except Exception as e:
            logger.error(f"Memory save error: {e}", exc_info=True)

    def _extract_last_assistant_text(self, messages: list[dict]) -> Optional[str]:
        if messages[-1].get("role") != "assistant":
            return None
        for block in messages[-1].get("content", []):
            if isinstance(block, dict) and block.get("text"):
                return block["text"]
        return None

    def _extract_last_user_text(self, messages: list[dict]) -> Optional[str]:
        for msg in reversed(messages[:-1]):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [{}])
            if not content or not isinstance(content[0], dict):
                continue
            if "toolResult" in content[0] or not content[0].get("text"):
                continue

            raw_text = content[0]["text"]
            # strip LTM injected prefix if present
            if self.user_query_delimiter in raw_text:
                return raw_text.split(self.user_query_delimiter + "\n", 1)[-1]
            return raw_text
        return None

    def _inject_ltm_context(self, content_block: dict, user_query: str, actor_id: str):
        try:
            all_context: list[str] = []

            for ns_template in self.ltm_namespaces:
                namespace = ns_template.format(actorId=actor_id)

                memories = self.memory_session.search_long_term_memories(
                    query=user_query,
                    namespace_prefix=namespace,
                    top_k=self.ltm_top_k,
                )

                for memory in memories:
                    score = memory.get("score", 0) or 0
                    if score < self.min_relevance_score:
                        continue

                    text = memory.get("content", {}).get("text", "").strip()
                    if not text:
                        continue

                    label = "PREFERENCIAS" if "preferences" in namespace else "DATOS"
                    all_context.append(f"[{label}] {text}")

            if not all_context:
                logger.info("LTM: No relevant memories found")
                return

            context_block = "\n".join(all_context)
            original_text = content_block.get("text", "")

            content_block["text"] = (
                f"{self.ltm_header}\n"
                f"{context_block}\n\n"
                f"{self.user_query_delimiter}\n"
                f"{original_text}"
            )
            logger.info(f"LTM: Injected {len(all_context)} memories into message")

        except Exception as e:
            logger.error(f"LTM retrieval error: {e}", exc_info=True)

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(AgentInitializedEvent, self.on_agent_initialized)
        registry.add_callback(MessageAddedEvent, self.on_message_added)
        registry.add_callback(AfterInvocationEvent, self.save_interaction)