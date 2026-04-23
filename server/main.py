from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings
from core.database import engine
from models.base import Base
import logging

# Ensure models are imported so Base knows about them
import models.agent
import models.call
import models.tool

from api.routes import agent, call, tool, chat
from api.websockets import stream, webcall

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# FastAPI app init
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Custom Production Grade Voice Agent powered by Twilio, FastAPI, and OpenAI Realtime API",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(agent.router, prefix="/api")
app.include_router(tool.router, prefix="/api")
app.include_router(call.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(stream.router)   # Twilio WS router
app.include_router(webcall.router)  # Browser WS router

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up Voice Agent Service...")
    try:
        # Tables are now managed by Django migrations
        logger.info("Database connection established.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        logger.warning("Service starting with local DB error. Some endpoints may fail until DB is fixed.")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down async engine...")
    await engine.dispose()

@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}"}
