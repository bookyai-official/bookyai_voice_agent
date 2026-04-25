from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from core.database import get_db
from core.config import settings
from models.agent import AIAgent
from schemas.agent import AIAgentCreate, AIAgentUpdate, AIAgentResponse
from api.dependencies import verify_token

router = APIRouter(prefix="/agents", tags=["Agents"])

@router.get("/voice-preview/{voice}", dependencies=[Depends(verify_token)])
async def get_voice_preview(voice: str):
    """
    Generates a short audio preview using OpenAI TTS.
    """
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")
    
    # Fallback for voices not supported by tts-1 model
    # verse and ballad are Realtime-only for now
    target_voice = voice
    if voice.lower() in ["verse", "ballad"]:
        target_voice = "alloy" # Use alloy as a temporary preview fallback
    
    # Capitalize voice name for the text
    display_voice = voice.capitalize()
    text = f"Hello! I am the {display_voice} voice. How can I help you today?"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                json={
                    "model": "tts-1",
                    "voice": target_voice,
                    "input": text
                },
                timeout=10.0
            )
            response.raise_for_status()
            
            return StreamingResponse(response.iter_bytes(), media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/", response_model=AIAgentResponse, dependencies=[Depends(verify_token)])
async def create_agent(agent: AIAgentCreate, db: AsyncSession = Depends(get_db)):
    db_agent = AIAgent(**agent.model_dump())
    db.add(db_agent)
    await db.commit()
    
    # Reload with relationships for response
    result = await db.execute(
        select(AIAgent)
        .options(selectinload(AIAgent.tools), selectinload(AIAgent.calls))
        .where(AIAgent.id == db_agent.id)
    )
    return result.scalar_one()

@router.get("/", response_model=list[AIAgentResponse], dependencies=[Depends(verify_token)])
async def get_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AIAgent)
        .options(selectinload(AIAgent.tools), selectinload(AIAgent.calls))
    )
    return result.scalars().all()

@router.get("/{agent_id}", response_model=AIAgentResponse, dependencies=[Depends(verify_token)])
async def get_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AIAgent)
        .options(selectinload(AIAgent.tools), selectinload(AIAgent.calls))
        .where(AIAgent.id == agent_id)
    )
    db_agent = result.scalar_one_or_none()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return db_agent

@router.put("/{agent_id}", response_model=AIAgentResponse, dependencies=[Depends(verify_token)])
async def update_agent(agent_id: int, agent: AIAgentUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIAgent).where(AIAgent.id == agent_id))
    db_agent = result.scalar_one_or_none()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    update_data = agent.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_agent, key, value)
    
    await db.commit()
    
    # Reload with relationships
    result = await db.execute(
        select(AIAgent)
        .options(selectinload(AIAgent.tools), selectinload(AIAgent.calls))
        .where(AIAgent.id == db_agent.id)
    )
    return result.scalar_one()

@router.delete("/{agent_id}", dependencies=[Depends(verify_token)])
async def delete_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIAgent).where(AIAgent.id == agent_id))
    db_agent = result.scalar_one_or_none()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    await db.delete(db_agent)
    await db.commit()
    return {"ok": True}
