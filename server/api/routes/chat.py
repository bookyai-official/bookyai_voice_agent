from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import json
import httpx
import logging

from core.database import get_db
from core.config import settings
from models.agent import VoiceAgent
from api.dependencies import verify_token
from services.external_tools import execute_tool

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
OPENAI_MODEL        = "gpt-5.4-mini" #DO NOT CHANGE
DEFAULT_TEMPERATURE = 0.8
MAX_TOOL_ITERATIONS = 5
OPENAI_TIMEOUT      = 30.0
RESPONSES_URL       = "https://api.openai.com/v1/responses"


# ── Key difference vs Chat Completions ────────────────────────────────────────
#
#  Chat Completions tool schema:          Responses API tool schema:
#  {                                      {
#    "type": "function",                    "type": "function",
#    "function": {          ← nested        "name": "...",        ← flat
#      "name": "...",                       "description": "...",
#      "description": "...",                "parameters": { ... }
#      "parameters": { ... }              }
#    }
#  }
#
#  Tool result in Chat Completions:       Tool result in Responses API:
#  { "role": "tool",                      {
#    "tool_call_id": "...",                  "type": "function_call_output",
#    "content": "..." }                      "call_id": "...",
#                                            "output": "..."
#                                         }
#
#  System prompt:  messages[0] role=system    →   top-level "instructions" field
#
#  Multi-turn:     resend full messages list  →   pass "previous_response_id"
#                  (grows on every turn)           (OpenAI holds state server-side)
# ─────────────────────────────────────────────────────────────────────────────


def _build_tool_schema(agent: VoiceAgent) -> tuple[list[dict], dict]:
    """
    Build Responses API tool definitions (flat schema, no nested 'function' key)
    and a lookup dict of tool configs keyed by tool name.
    """
    formatted_tools: list[dict] = []
    tool_configs:    dict       = {}

    for t in agent.tools:
        # Responses API: flat structure — name/description/parameters at top level
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


async def _execute_tool(tool_call: dict, tool_configs: dict) -> str:
    """Execute a single tool call and return the result as a JSON string."""
    name     = tool_call.get("name", "")
    raw_args = tool_call.get("arguments", "{}")

    try:
        parsed_args: dict = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        logger.warning("[CHAT] Could not parse args for tool '%s': %s", name, raw_args)
        parsed_args = {}

    config = tool_configs.get(name)
    if not config:
        logger.warning("[CHAT] Tool '%s' not found in agent config", name)
        return json.dumps({"error": f"Unknown tool: {name}"})

    t_type: str = config.get("type", "webhook")
    logger.info("[CHAT] Executing tool '%s' (type=%s)", name, t_type)

    if t_type == "call_end":
        return json.dumps({"status": "success", "message": "Call ended (simulated)"})

    if t_type == "call_transfer":
        target = config.get("target") or "unknown"
        return json.dumps({"status": "success", "message": f"Transferring to {target} (simulated)"})

    if t_type == "webhook":
        url = config.get("url")
        if not url:
            logger.warning("[CHAT] Webhook tool '%s' has no URL configured", name)
            return json.dumps({"error": "Tool not properly configured: missing URL"})
        return await execute_tool(url, config["method"], config["timeout_seconds"], raw_args)

    logger.warning("[CHAT] Unsupported tool type '%s' for tool '%s'", t_type, name)
    return json.dumps({"error": f"Unsupported tool type: {t_type}"})


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/{agent_id}", dependencies=[Depends(verify_token)])
async def agent_chat_test(
    agent_id: int,
    payload:  dict,
    db:       AsyncSession = Depends(get_db),
):
    """
    Text-based chat endpoint for testing voice agents (uses OpenAI Responses API).

    First turn payload:
        {"messages": [{"role": "user", "content": "Hello"}]}

    Subsequent turns (stateful — avoids resending full history):
        {
            "messages":            [{"role": "user", "content": "Follow-up question"}],
            "previous_response_id": "resp_abc123"
        }

    Response:
        {
            "role":                "assistant",
            "content":             "...",
            "response_id":         "resp_xyz789",   ← pass back as previous_response_id
            "usage":               { ... }
        }
    """

    # ── 1. Fetch agent ────────────────────────────────────────────────────────
    db_result = await db.execute(
        select(VoiceAgent)
        .options(selectinload(VoiceAgent.tools))
        .where(VoiceAgent.id == agent_id)
    )
    agent: VoiceAgent | None = db_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # ── 2. Validate request ───────────────────────────────────────────────────
    messages: list[dict] = payload.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # Only the latest user message is needed when previous_response_id is set
    previous_response_id: str | None = payload.get("previous_response_id")

    # Responses API uses "input" not "messages"
    # Only pass the new user message(s) when continuing a conversation
    user_input = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") != "system"   # system prompt goes in "instructions", not input
    ]

    # ── 3. Build tools ────────────────────────────────────────────────────────
    formatted_tools, tool_configs = _build_tool_schema(agent)

    # ── 4. Agentic loop ───────────────────────────────────────────────────────
    # WHY the loop is still needed:
    # The Responses API auto-executes OpenAI's OWN hosted tools (web_search, etc.)
    # but for CUSTOM FUNCTIONS (your webhooks), it still returns a function_call
    # output item and waits for you to execute it and pass the result back.
    # The loop handles that hand-off for custom webhook tools.

    try:
        async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT) as client:

            current_input          = user_input
            current_prev_resp_id   = previous_response_id

            for iteration in range(MAX_TOOL_ITERATIONS):

                api_payload: dict = {
                    "model":        OPENAI_MODEL,
                    "instructions": (
                        "YOU MUST ONLY SPEAK IN ENGLISH. DO NOT USE ANY OTHER LANGUAGE. "
                        f"{agent.system_prompt}"
                    ),
                    "input":        current_input,
                    "temperature":  agent.temperature
                                    if agent.temperature is not None
                                    else DEFAULT_TEMPERATURE,
                }

                # Stateful multi-turn: OpenAI keeps conversation history server-side.
                # We only send the delta (new messages), not the full history.
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
                    logger.error("[CHAT] OpenAI error %s: %s", response.status_code, error_body)
                    raise HTTPException(
                        status_code=502,
                        detail=f"Upstream LLM error ({response.status_code}): {error_body}",
                    )

                data        = response.json()
                response_id = data.get("id")        # save for next turn
                output      = data.get("output", [])

                # ── Scan output items ─────────────────────────────────────────
                # Responses API returns a list of output items (messages, tool calls, etc.)

                function_calls = [item for item in output if item.get("type") == "function_call"]
                text_outputs   = [
                    item for item in output
                    if item.get("type") == "message"
                    and item.get("role") == "assistant"
                ]

                # ── Tool-call branch ──────────────────────────────────────────
                if function_calls:
                    # Build function_call_output items for all tool calls
                    tool_result_items: list[dict] = []

                    for fc in function_calls:
                        result_str = await _execute_tool(fc, tool_configs)
                        tool_result_items.append({
                            "type":    "function_call_output",
                            "call_id": fc["call_id"],   # Responses API uses call_id (not tool_call_id)
                            "output":  result_str,
                        })
                        logger.info(
                            "[CHAT] Tool '%s' executed (iteration %d/%d)",
                            fc.get("name"), iteration + 1, MAX_TOOL_ITERATIONS,
                        )

                    # Next iteration: send tool results as the new input.
                    # previous_response_id links this back to the current response.
                    current_input        = tool_result_items
                    current_prev_resp_id = response_id
                    continue

                # ── Final response branch ─────────────────────────────────────
                if text_outputs:
                    # Extract text from the assistant message content
                    content_parts = text_outputs[-1].get("content", [])
                    final_text = " ".join(
                        part.get("text", "")
                        for part in content_parts
                        if part.get("type") == "output_text"
                    )
                    return {
                        "role":        "assistant",
                        "content":     final_text,
                        "response_id": response_id,   # client passes this back next turn
                        "usage":       data.get("usage"),
                    }

                # Edge case: output had neither tool calls nor a text message
                logger.warning("[CHAT] Unexpected output structure: %s", output)
                raise HTTPException(status_code=500, detail="Unexpected response structure from LLM")

            logger.error("[CHAT] Exceeded max tool iterations (%d)", MAX_TOOL_ITERATIONS)
            raise HTTPException(
                status_code=500,
                detail=f"Agent exceeded the maximum of {MAX_TOOL_ITERATIONS} tool-call iterations.",
            )

    except HTTPException:
        raise
    except httpx.TimeoutException:
        logger.error("[CHAT] OpenAI request timed out after %.1fs", OPENAI_TIMEOUT)
        raise HTTPException(status_code=504, detail="LLM request timed out")
    except Exception as exc:
        logger.error("[CHAT] Unexpected error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))