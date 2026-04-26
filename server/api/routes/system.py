from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from core.database import get_db
from models.system import SystemSetting
from api.dependencies import verify_token

router = APIRouter(prefix="/system", tags=["System"])

@router.get("/settings", dependencies=[Depends(verify_token)])
async def get_system_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemSetting))
    db_setting = result.scalar_one_or_none()
    
    if not db_setting:
        return {
            "text_model": "gpt-4o-mini",
            "realtime_llm_model": "gpt-realtime-2025-08-28",
            "summary_model": "gpt-4o-mini",
            "maintenance_mode": False,
            "maintenance_message": "We are currently undergoing maintenance. Please check back later.",
            "company_name": "BookyAI",
            "company_email": "support@bookyai.com",
            "company_phone": "",
            "facebook_link": "",
            "twitter_link": "",
            "instagram_link": "",
            "linkedin_link": ""
        }
        
    return {
        "text_model": db_setting.text_model,
        "realtime_llm_model": db_setting.realtime_llm_model,
        "summary_model": db_setting.summary_model,
        "maintenance_mode": db_setting.maintenance_mode,
        "maintenance_message": db_setting.maintenance_message,
        "company_name": db_setting.company_name,
        "company_email": db_setting.company_email,
        "company_phone": db_setting.company_phone,
        "facebook_link": db_setting.facebook_link,
        "twitter_link": db_setting.twitter_link,
        "instagram_link": db_setting.instagram_link,
        "linkedin_link": db_setting.linkedin_link
    }
