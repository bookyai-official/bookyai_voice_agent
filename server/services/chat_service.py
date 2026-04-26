"""
ChatService — Unified text-based agent brain (DB-backed conversation history).

Channel-agnostic service that:
1. Finds or creates a Chat session (by phone_number or session_key)
2. Loads full conversation history from the DB
3. Sends history + new message to OpenAI Responses API (with tool calling)
4. Saves user message + assistant response to the DB
5. Returns the response to the channel route

Used by SMS, Widget, and Test Chat routes.
"""

import json
import httpx
import logging
from dataclasses import dataclass
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.config import settings
from core.database import AsyncSessionLocal
from models.conversation import Chat, Message
from services.external_tools import execute_tool

logger = logging.getLogger(__name__)

from models.system import SystemSetting

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_TEMPERATURE = 0.8
MAX_TOOL_ITERATIONS = 5
OPENAI_TIMEOUT      = 30.0
RESPONSES_URL       = "https://api.openai.com/v1/responses"


@dataclass
class ChatResponse:
    """Result returned by the ChatService to any channel."""
    content: str
    chat_id: int
    usage: dict | None = None


# ── Tool Helpers ──────────────────────────────────────────────────────────────

def build_tool_schema(agent) -> tuple[list[dict], dict]:
    """
    Build Responses API tool definitions (flat schema) and a lookup dict
    of tool configs keyed by tool name.
    """
    formatted_tools: list[dict] = []
    tool_configs: dict = {}

    for t in agent.tools:
        formatted_tools.append({
            "type":        "function",
            "name":        t.name,
            "description": t.description,
            "parameters":  t.json_schema,
        })
        tool_configs[t.name] = {
            "type":            t.tool_type or "webhook",
            "url":             t.url,
            "target":          t.tool_target,
            "method":          t.method,
            "timeout_seconds": t.timeout_seconds,
        }

    return formatted_tools, tool_configs


async def _execute_tool_call(tool_call: dict, tool_configs: dict) -> str:
    """Execute a single tool call and return the result as a JSON string."""
    name     = tool_call.get("name", "")
    raw_args = tool_call.get("arguments", "{}")

    try:
        json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        logger.warning("[CHAT SERVICE] Could not parse args for tool '%s': %s", name, raw_args)

    config = tool_configs.get(name)
    if not config:
        logger.warning("[CHAT SERVICE] Tool '%s' not found in agent config", name)
        return json.dumps({"error": f"Unknown tool: {name}"})

    t_type: str = config.get("type", "webhook")
    logger.info("[CHAT SERVICE] Executing tool '%s' (type=%s)", name, t_type)

    if t_type == "call_end":
        return json.dumps({"status": "success", "message": "Conversation ended"})

    if t_type == "call_transfer":
        target = config.get("target") or "unknown"
        return json.dumps({"status": "success", "message": f"Transferring to {target}"})

    if t_type == "webhook":
        url = config.get("url")
        if not url:
            logger.warning("[CHAT SERVICE] Webhook tool '%s' has no URL configured", name)
            return json.dumps({"error": "Tool not properly configured: missing URL"})
        return await execute_tool(url, config["method"], config["timeout_seconds"], raw_args)

    logger.warning("[CHAT SERVICE] Unsupported tool type '%s' for tool '%s'", t_type, name)
    return json.dumps({"error": f"Unsupported tool type: {t_type}"})


# ── Chat Session Management ──────────────────────────────────────────────────

async def get_or_create_chat(
    business_id: int,
    phone_number: str | None = None,
    session_key: str | None = None,
) -> Chat:
    """
    Find an existing Chat or create a new one.

    Lookup priority:
    - SMS channel: by business_id + phone_number
    - Widget channel: by business_id + session_key
    """
    async with AsyncSessionLocal() as db:
        query = select(Chat).where(Chat.business_id == business_id, Chat.is_active == True)

        if phone_number:
            query = query.where(Chat.phone_number == phone_number)
        elif session_key:
            query = query.where(Chat.session_key == session_key)
        else:
            raise ChatServiceError("Either phone_number or session_key is required")

        result = await db.execute(query)
        chat = result.scalar_one_or_none()

        if chat:
            return chat

        # Create new chat
        chat = Chat(
            business_id=business_id,
            phone_number=phone_number,
            session_key=session_key,
        )
        db.add(chat)
        await db.commit()
        await db.refresh(chat)
        logger.info(
            "[CHAT SERVICE] Created new Chat id=%d (business=%d, %s)",
            chat.id, business_id,
            f"phone={phone_number}" if phone_number else f"session={session_key}",
        )
        return chat


async def _load_conversation_history(chat_id: int) -> list[dict]:
    """Load all messages for a chat, formatted for OpenAI input."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()

    return [
        {"role": msg.role, "content": msg.content}
        for msg in messages
        if msg.role in ("user", "assistant")  # Only send user/assistant turns to OpenAI
    ]


async def _save_message(chat_id: int, role: str, content: str) -> Message:
    """Save a message to the DB."""
    async with AsyncSessionLocal() as db:
        msg = Message(chat_id=chat_id, role=role, content=content)
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg


# ── Core: Get Agent Response ─────────────────────────────────────────────────

async def get_agent_response(
    agent,
    user_message: str,
    chat_id: int,
    channel: str = "unknown",
) -> ChatResponse:
    """
    Send a user message to an AIAgent and get a text response.

    1. Saves the user message to DB
    2. Loads full conversation history
    3. Sends history to OpenAI Responses API
    4. Executes any tool calls in a loop
    5. Saves the assistant response to DB
    6. Returns the response

    Args:
        agent: AIAgent ORM object (must have .tools eagerly loaded).
        user_message: The user's text message.
        chat_id: The Chat record ID for conversation history.
        channel: Logging label — "sms", "widget", "test", etc.

    Returns:
        ChatResponse with the assistant's reply and chat_id.
    """
    tag = f"[CHAT SERVICE][{channel.upper()}]"

    # 1. Save user message
    await _save_message(chat_id, "user", user_message)

    # 2. Load full conversation history
    history = await _load_conversation_history(chat_id)
    logger.info("%s Chat %d — %d messages in history", tag, chat_id, len(history))

    # 3. Build tools from agent config
    formatted_tools, tool_configs = build_tool_schema(agent)

    # 4. Call OpenAI with full history
    try:
        async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT) as client:

            current_input = history  # Full conversation history
            current_prev_resp_id = None

            for iteration in range(MAX_TOOL_ITERATIONS):
                
                # Fetch dynamic model configuration
                async with AsyncSessionLocal() as db_session:
                    system_setting = await db_session.execute(select(SystemSetting))
                    system_setting = system_setting.scalar_one_or_none()
                    current_model = system_setting.text_model if system_setting and system_setting.text_model else "gpt-4o-mini"

                api_payload: dict = {
                    "model": current_model,
                    "instructions": (
                        "YOU MUST ONLY SPEAK IN ENGLISH. DO NOT USE ANY OTHER LANGUAGE. "
                        f"{agent.system_prompt}"
                    ),
                    "input":        current_input,
                    "temperature":  (
                        agent.temperature
                        if agent.temperature is not None
                        else DEFAULT_TEMPERATURE
                    ),
                }

                # On tool-call re-send, link back to previous response
                if current_prev_resp_id:
                    api_payload["previous_response_id"] = current_prev_resp_id

                if formatted_tools:
                    api_payload["tools"] = formatted_tools

                response = await client.post(
                    RESPONSES_URL,
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type":  "application/json",
                    },
                    json=api_payload,
                )

                if response.status_code != 200:
                    error_body = response.text
                    logger.error("%s OpenAI error %s: %s", tag, response.status_code, error_body)
                    raise ChatServiceError(f"Upstream LLM error ({response.status_code})")

                data        = response.json()
                response_id = data.get("id")
                output      = data.get("output", [])

                # Scan output items
                function_calls = [item for item in output if item.get("type") == "function_call"]
                text_outputs   = [
                    item for item in output
                    if item.get("type") == "message" and item.get("role") == "assistant"
                ]

                # ── Tool-call branch ──────────────────────────────────────
                if function_calls:
                    tool_result_items: list[dict] = []

                    for fc in function_calls:
                        result_str = await _execute_tool_call(fc, tool_configs)
                        tool_result_items.append({
                            "type":    "function_call_output",
                            "call_id": fc["call_id"],
                            "output":  result_str,
                        })
                        logger.info(
                            "%s Tool '%s' executed (iteration %d/%d)",
                            tag, fc.get("name"), iteration + 1, MAX_TOOL_ITERATIONS,
                        )

                    # Next iteration: send tool results, linked to current response
                    current_input        = tool_result_items
                    current_prev_resp_id = response_id
                    continue

                # ── Final text response ───────────────────────────────────
                if text_outputs:
                    content_parts = text_outputs[-1].get("content", [])
                    final_text = " ".join(
                        part.get("text", "")
                        for part in content_parts
                        if part.get("type") == "output_text"
                    )

                    # 5. Save assistant response to DB
                    await _save_message(chat_id, "assistant", final_text)

                    logger.info("%s Response: %s", tag, final_text[:200])
                    return ChatResponse(
                        content=final_text,
                        chat_id=chat_id,
                        usage=data.get("usage"),
                    )

                # Edge case
                logger.warning("%s Unexpected output structure: %s", tag, output)
                raise ChatServiceError("Unexpected response structure from LLM")

            logger.error("%s Exceeded max tool iterations (%d)", tag, MAX_TOOL_ITERATIONS)
            raise ChatServiceError(
                f"Agent exceeded the maximum of {MAX_TOOL_ITERATIONS} tool-call iterations."
            )

    except ChatServiceError:
        raise
    except httpx.TimeoutException:
        logger.error("%s OpenAI request timed out after %.1fs", tag, OPENAI_TIMEOUT)
        raise ChatServiceError("LLM request timed out")
    except Exception as exc:
        logger.error("%s Unexpected error: %s", tag, exc, exc_info=True)
        raise ChatServiceError(str(exc))


class ChatServiceError(Exception):
    """Raised when the ChatService encounters a non-recoverable error."""
    pass
