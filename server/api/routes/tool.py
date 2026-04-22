from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from core.database import get_db
from models.tool import AgentTool
from models.agent import VoiceAgent
from schemas.tool import AgentToolCreate, AgentToolUpdate, AgentToolResponse
from api.dependencies import verify_token

router = APIRouter(prefix="/tools", tags=["Tools"])

@router.post("/", response_model=AgentToolResponse, dependencies=[Depends(verify_token)])
async def create_tool(tool: AgentToolCreate, db: AsyncSession = Depends(get_db)):
    # Verify Agent exists
    res = await db.execute(select(VoiceAgent).where(VoiceAgent.id == tool.agent_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Agent not found")

    db_tool = AgentTool(**tool.model_dump())
    db.add(db_tool)
    await db.commit()
    await db.refresh(db_tool)
    return db_tool

@router.put("/{tool_id}", response_model=AgentToolResponse, dependencies=[Depends(verify_token)])
async def update_tool(tool_id: int, tool: AgentToolUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentTool).where(AgentTool.id == tool_id))
    db_tool = result.scalar_one_or_none()
    if not db_tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    
    update_data = tool.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_tool, key, value)
    
    await db.commit()
    await db.refresh(db_tool)
    return db_tool

@router.delete("/{tool_id}", dependencies=[Depends(verify_token)])
async def delete_tool(tool_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentTool).where(AgentTool.id == tool_id))
    db_tool = result.scalar_one_or_none()
    if not db_tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    
    await db.delete(db_tool)
    await db.commit()
    return {"ok": True}
