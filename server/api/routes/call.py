from fastapi import APIRouter, Request, Query, HTTPException, Depends
from typing import List, Optional
from fastapi.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
from pydantic import BaseModel
from services.twilio_client import make_outbound_call
from api.dependencies import verify_token
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from core.database import AsyncSessionLocal, get_db
from models.call import CallRecord
from models.agent import AIAgent
from schemas.call import CallRecordResponse
from models.business import BusinessConfiguration, BlockedPhoneNumber
from services.usage_service import UsageService

router = APIRouter(prefix="/calls", tags=["Calls"])

@router.get("/", response_model=List[CallRecordResponse], dependencies=[Depends(verify_token)])
async def get_calls(
    agent_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    # Join with AIAgent to get the agent name
    query = select(CallRecord, AIAgent.name.label("agent_name")).join(AIAgent, CallRecord.agent_id == AIAgent.id)
    
    if agent_id:
        query = query.where(CallRecord.agent_id == agent_id)
    
    query = query.order_by(CallRecord.created_at.desc())
    result = await db.execute(query)
    
    # We need to manually construct the response because of the join/label
    calls = []
    for row in result.all():
        call_obj = row[0]
        call_obj.agent_name = row[1]
        calls.append(call_obj)
    
    return calls

@router.get("/{call_id}", response_model=CallRecordResponse, dependencies=[Depends(verify_token)])
async def get_call_detail(
    call_id: int,
    db: AsyncSession = Depends(get_db)
):
    query = select(CallRecord, AIAgent.name.label("agent_name")).join(AIAgent, CallRecord.agent_id == AIAgent.id).where(CallRecord.id == call_id)
    result = await db.execute(query)
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Call record not found")
        
    call_obj = row[0]
    call_obj.agent_name = row[1]
    return call_obj

@router.post("/incoming")
async def handle_incoming_call(
    request: Request, 
    agent_id: int = Query(..., description="ID of the Agent config to use"),
    lead_info: Optional[str] = Query(None, description="Lead info or special instructions")
):
    """
    Webhook for Twilio Inbound (or Outbound loopback) calls.
    Returns TwiML that connects the call to our WebSocket stream.
    """
    # Assuming FastAPI app is being reversed proxied (e.g., via ngrok)
    host = request.headers.get("host")
    if not host:
        host = "localhost:8000"
    
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "unknown-sid-debug")
    from_number = form_data.get("From", "")
    to_number = form_data.get("To", "")
    direction = form_data.get("Direction", "inbound")
    
    # ── 1. Fetch Agent and Business Context ──────────────────────────────
    async with AsyncSessionLocal() as db:
        # We need the business_id from the agent to check for blocked numbers
        agent_result = await db.execute(select(AIAgent).where(AIAgent.id == agent_id))
        agent = agent_result.scalar_one_or_none()
        
        if not agent:
            # If agent not found, we can't do much. Reject the call.
            response = VoiceResponse()
            response.reject()
            return HTMLResponse(content=str(response), media_type="application/xml")

        # ── 2. Check for Blocked Phone Number ───────────────────────────────
        if from_number:
            block_result = await db.execute(
                select(BlockedPhoneNumber).where(
                    BlockedPhoneNumber.business_id == agent.business_id,
                    BlockedPhoneNumber.phone_number == from_number
                )
            )
            if block_result.scalar_one_or_none():
                # Number is blocked for this business
                response = VoiceResponse()
                response.reject() # Or response.hangup()
                return HTMLResponse(content=str(response), media_type="application/xml")

        # ── 2.5 Check Usage Limit ───────────────────────────────────────────
        has_usage = await UsageService.has_remaining_usage(db, agent.business_id, "minutes")
        if not has_usage:
            # Business has no minutes left. Reject the call.
            response = VoiceResponse()
            response.reject()
            return HTMLResponse(content=str(response), media_type="application/xml")

    # ── 3. WebSocket URL and DB record ────────────────────────────────────
    # Replace HTTP/HTTPS with WSS for WebSocket URL
    ws_url = f"wss://{host}/ws/stream/{agent_id}?direction={direction}"
    if lead_info:
        from urllib.parse import quote
        ws_url += f"&lead_info={quote(lead_info)}"
    
    # inbound or outbound-api
    call_type = "outbound" if "outbound" in direction else "inbound"
    
    # Save Initial Call Record Event
    async with AsyncSessionLocal() as db:
        new_call = CallRecord(
            agent_id=agent_id,
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            status="ringing",
            call_type=call_type,
            call_mode="phone"
        )
        db.add(new_call)
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            # If unique constraint hit on call_sid somehow, ignore for now.
            pass

    response = VoiceResponse()
    connect = Connect()
    # Pass CallSid to WebSocket via URL parameter or we can just rely on Twilio stream data
    connect.stream(url=ws_url)
    response.append(connect)
    # Enable recording for the call
    response.record()

    return HTMLResponse(content=str(response), media_type="application/xml")

class OutboundCallRequest(BaseModel):
    to_number: str
    agent_id: int
    lead_info: Optional[str] = None

@router.post("/outbound", dependencies=[Depends(verify_token)])
async def trigger_outbound_call(request: Request, payload: OutboundCallRequest, db: AsyncSession = Depends(get_db)):
    """
    Triggers a Twilio API request to make an outbound call.
    Uses per-business credentials and per-agent phone numbers.
    """
    # 1. Fetch Agent
    result = await db.execute(select(AIAgent).where(AIAgent.id == payload.agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # 2. Fetch Business Config
    result = await db.execute(select(BusinessConfiguration).where(BusinessConfiguration.business_id == agent.business_id))
    biz_config = result.scalar_one_or_none()
    twilio_sid = biz_config.twilio_sid if biz_config else None
    twilio_token = biz_config.twilio_auth_token if biz_config else None
    from_number = agent.phone_number or (biz_config.twilio_phone_number if biz_config else None)

    if not twilio_sid or not twilio_token or not from_number:
        raise HTTPException(status_code=400, detail="Twilio credentials or phone number missing for this agent/business.")

    # 3. Check for Blocked Phone Number
    block_result = await db.execute(
        select(BlockedPhoneNumber).where(
            BlockedPhoneNumber.business_id == agent.business_id,
            BlockedPhoneNumber.phone_number == payload.to_number
        )
    )
    if block_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="The destination phone number is blocked.")

    # 4. Check Usage Limit
    has_usage = await UsageService.has_remaining_usage(db, agent.business_id, "minutes")
    if not has_usage:
        raise HTTPException(status_code=403, detail="Business has exceeded call minutes limit.")

    host = request.headers.get("host")
    try:
        call_sid = make_outbound_call(
            to_number=payload.to_number, 
            from_number=from_number,
            agent_id=payload.agent_id, 
            host_domain=host,
            twilio_sid=twilio_sid,
            twilio_token=twilio_token,
            lead_info=payload.lead_info,
            time_limit=(agent.max_call_duration_minutes or 10) * 60
        )
        return {"status": "success", "call_sid": call_sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
