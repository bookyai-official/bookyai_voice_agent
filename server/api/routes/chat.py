"""
Test Chat Route — Authenticated endpoint for testing agents via text.

Stateless — does NOT save to Chat/Message tables.
Uses OpenAI's previous_response_id for multi-turn (OpenAI holds state server-side).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import json
import httpx
import logging

from core.database import get_db
from core.config import settings
from models.agent import AIAgent
from api.dependencies import verify_token
from services.chat_service import build_tool_schema, _execute_tool_call, ChatServiceError

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = logging.getLogger(__name__)

OPENAI_MODEL        = "gpt-5.4-mini"  # DO NOT CHANGE
DEFAULT_TEMPERATURE = 0.8
MAX_TOOL_ITERATIONS = 5
OPENAI_TIMEOUT      = 30.0
RESPONSES_URL       = "https://api.openai.com/v1/responses"


@router.post("/{agent_id}", dependencies=[Depends(verify_token)])
async def agent_chat_test(
    agent_id: int,
    payload:  dict,
    db:       AsyncSession = Depends(get_db),
):
    """
    Stateless text chat for testing agents. No DB records created.

    First turn:
        {"messages": [{"role": "user", "content": "Hello"}]}

    Subsequent turns:
        {
            "messages":            [{"role": "user", "content": "Follow-up"}],
            "previous_response_id": "resp_abc123"
        }

    Response:
        {
            "role":                "assistant",
            "content":             "...",
            "response_id":         "resp_xyz789",
            "usage":               { ... }
        }
    """
    # ── 1. Fetch agent ────────────────────────────────────────────────────
    db_result = await db.execute(
        select(AIAgent)
        .options(selectinload(AIAgent.tools))
        .where(AIAgent.id == agent_id)
    )
    agent: AIAgent | None = db_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # ── 2. Validate request ───────────────────────────────────────────────
    messages: list[dict] = payload.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    user_messages = [m for m in messages if m.get("role") == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message found")

    previous_response_id: str | None = payload.get("previous_response_id")

    user_input = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") != "system"
    ]

    # ── 3. Build tools ────────────────────────────────────────────────────
    formatted_tools, tool_configs = build_tool_schema(agent)

    # ── 4. Stateless agentic loop (no DB writes) ─────────────────────────
    try:
        async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT) as client:

            current_input        = user_input
            current_prev_resp_id = previous_response_id

            for iteration in range(MAX_TOOL_ITERATIONS):

                api_payload: dict = {
                    "model":        OPENAI_MODEL,
                    "instructions": (
                        "YOU MUST ONLY SPEAK IN ENGLISH. DO NOT USE ANY OTHER LANGUAGE. "
                        f"{agent.system_prompt}"
                    ),
                    "input":        current_input,
                    "temperature":  agent.temperature if agent.temperature is not None else DEFAULT_TEMPERATURE,
                }

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
                    logger.error("[TEST CHAT] OpenAI error %s: %s", response.status_code, response.text)
                    raise HTTPException(status_code=502, detail=f"Upstream LLM error ({response.status_code})")

                data        = response.json()
                response_id = data.get("id")
                output      = data.get("output", [])

                function_calls = [item for item in output if item.get("type") == "function_call"]
                text_outputs   = [
                    item for item in output
                    if item.get("type") == "message" and item.get("role") == "assistant"
                ]

                if function_calls:
                    tool_result_items: list[dict] = []
                    for fc in function_calls:
                        result_str = await _execute_tool_call(fc, tool_configs)
                        tool_result_items.append({
                            "type":    "function_call_output",
                            "call_id": fc["call_id"],
                            "output":  result_str,
                        })
                        logger.info("[TEST CHAT] Tool '%s' executed (%d/%d)", fc.get("name"), iteration + 1, MAX_TOOL_ITERATIONS)

                    current_input        = tool_result_items
                    current_prev_resp_id = response_id
                    continue

                if text_outputs:
                    content_parts = text_outputs[-1].get("content", [])
                    final_text = " ".join(
                        part.get("text", "")
                        for part in content_parts
                        if part.get("type") == "output_text"
                    )
                    return {
                        "role":        "assistant",
                        "content":     final_text,
                        "response_id": response_id,
                        "usage":       data.get("usage"),
                    }

                logger.warning("[TEST CHAT] Unexpected output: %s", output)
                raise HTTPException(status_code=500, detail="Unexpected response structure from LLM")

            raise HTTPException(status_code=500, detail=f"Exceeded max tool iterations ({MAX_TOOL_ITERATIONS})")

    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="LLM request timed out")
    except Exception as exc:
        logger.error("[TEST CHAT] Error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))