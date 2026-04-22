from fastapi import Header, HTTPException, Depends
from core.config import settings

def verify_token(x_token: str = Header(..., description="API Secret Token")):
    if x_token != settings.API_SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API Secret Token")
    return x_token
