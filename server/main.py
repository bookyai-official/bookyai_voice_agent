from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from core.config import settings
from core.database import engine
from core.logging_config import setup_logging
from api.routes import agent, call, tool, chat
from api.websockets import stream, webcall
from api.middleware import RequestLoggingMiddleware, OriginRestrictionMiddleware, global_exception_handler

# Import models to ensure they are registered
import models.agent
import models.call
import models.tool

# Setup structured logging
setup_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("Starting up Voice Agent Service...")
    logger.info("Database connection established.")
    yield
    # Shutdown logic
    logger.info("Shutting down async engine...")
    await engine.dispose()

# FastAPI app init
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Custom Production Grade Voice Agent powered by Twilio, FastAPI, and OpenAI Realtime API",
    version="1.0.0",
    lifespan=lifespan
)

# Exception Handlers
app.add_exception_handler(Exception, global_exception_handler)

# Middlewares
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(OriginRestrictionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
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

@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}", "status": "running"}
