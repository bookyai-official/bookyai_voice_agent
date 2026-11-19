import logging
import asyncio
import math
from typing import Optional, Tuple, Dict, Any
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from models.agent import AIAgent
from models.business import BusinessConfiguration
from models.call import CallRecord
from services.usage_service import UsageService
from services.openai_summary import generate_call_summary

logger = logging.getLogger(__name__)

class VoiceService:
    """
    Shared service for managing Voice sessions across Twilio and Browser channels.
    Provides logic for agent configuration, usage gating, and session lifecycle.
    """

    @staticmethod
    async def get_session_config(agent_id: int) -> Tuple[Optional[AIAgent], Optional[BusinessConfiguration]]:
        """
        Fetches Agent and Business configuration for a session.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AIAgent, BusinessConfiguration)
                .outerjoin(BusinessConfiguration, AIAgent.business_id == BusinessConfiguration.business_id)
                .options(selectinload(AIAgent.tools))
                .where(AIAgent.id == agent_id)
            )
            row = result.first()
            if not row:
                return None, None
            return row

    @staticmethod
    async def check_usage_limit(business_id: int) -> int:
        """
        Checks remaining minutes for a business and returns remaining seconds.
        """
        async with AsyncSessionLocal() as session:
            remaining_minutes = await UsageService.get_remaining_usage(session, business_id, "minutes")
            return remaining_minutes * 60

    @staticmethod
    async def create_call_record(
        agent_id: int, 
        call_sid: str, 
        from_number: str = "unknown", 
        to_number: str = "agent", 
        call_type: str = "inbound", 
        call_mode: str = "voice"
    ):
        """
        Initializes a CallRecord in the database or updates it if it already exists.
        """
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(CallRecord).where(CallRecord.call_sid == call_sid))
            existing_call = res.scalar_one_or_none()
            
            if existing_call:
                existing_call.status = "in-progress"
                await db.commit()
                logger.info(f"[VOICE SERVICE] Updated CallRecord to in-progress for {call_sid}")
            else:
                new_call = CallRecord(
                    agent_id=agent_id,
                    call_sid=call_sid,
                    status="in-progress",
                    from_number=from_number,
                    to_number=to_number,
                    call_type=call_type,
                    call_mode=call_mode
                )
                db.add(new_call)
                await db.commit()
                logger.info(f"[VOICE SERVICE] Initialized CallRecord for {call_sid}")

    @staticmethod
    async def finalize_call(
        call_sid: str, 
        duration_seconds: int, 
        transcript: list, 
        usage: dict, 
        business_id: int,
        precharged: bool = False,
        failed: bool = False,
    ):
        """Commit the call result first; billing and summary requests cannot block its storage."""
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(CallRecord).where(CallRecord.call_sid == call_sid))
            call_rec = res.scalar_one_or_none()
            if not call_rec:
                return
            call_rec.status = "failed" if failed else "completed"
            call_rec.transcript = transcript
            call_rec.duration_seconds = duration_seconds
            call_rec.input_tokens = usage.get("input_tokens", 0)
            call_rec.output_tokens = usage.get("output_tokens", 0)
            call_rec.total_tokens = usage.get("total_tokens", 0)
            call_rec.cached_tokens = usage.get("cached_tokens", 0)
            call_rec.call_summary = (
                'Summary generation in progress.' if transcript else 'No transcript available for summary.'
            )
            await db.commit()

            minutes_to_charge = math.ceil(duration_seconds / 60)
            if minutes_to_charge > 0 and not precharged:
                await UsageService.update_usage(db, business_id, "minutes", minutes_to_charge)

        if not transcript:
            return
        try:
            summary = await asyncio.wait_for(
                generate_call_summary(transcript, business_id=business_id), timeout=20,
            )
        except Exception as exc:
            print(f'[VOICE] Summary unavailable for {call_sid} ({type(exc).__name__}).', flush=True)
            summary = 'Summary unavailable. The call transcript has been saved.'

        # Summary generation runs outside the transaction that saved the transcript.
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(CallRecord).where(CallRecord.call_sid == call_sid))
            call_rec = res.scalar_one_or_none()
            if call_rec:
                call_rec.call_summary = summary
                await db.commit()
