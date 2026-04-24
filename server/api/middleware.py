import time
import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

logger = logging.getLogger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        
        logger.info(
            "Request processed",
            extra={
                "method": request.method,
                "url": str(request.url),
                "status_code": response.status_code,
                "process_time_ms": round(process_time * 1000, 2),
                "client_host": request.client.host if request.client else None
            }
        )
        return response

class OriginRestrictionMiddleware(BaseHTTPMiddleware):
    """
    Restrict requests to specified domains (booky-ai.com and localhost).
    """
    async def dispatch(self, request: Request, call_next):
        # Skip check for certain paths if needed (e.g. docs)
        if request.url.path in ["/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        twilio_signature = request.headers.get("x-twilio-signature")
        
        # Always allow Twilio webhooks
        if twilio_signature:
            return await call_next(request)

        allowed_patterns = [
            "booky-ai.com",
            'bookyai.co.uk',
            'www.bookyai.co.uk',
            "staging.booky-ai.com",
            "staging.bookyai.co.uk",
            "localhost",
            "127.0.0.1"
        ]
        
        # In a browser, requests will typically have an Origin or Referer
        # If neither is present, it might be a direct call (e.g. curl, postman)
        # For strict security as requested, we check if they match our allowed patterns
        
        def is_allowed(value: str):
            if not value:
                return False
            return any(pattern in value for pattern in allowed_patterns)

        # Allow if either Origin or Referer is from an allowed domain
        # If neither is present, we might want to block or allow based on environment
        # Given "Only Request from main", we'll be strict.
        if origin or referer:
            if not (is_allowed(origin) or is_allowed(referer)):
                logger.warning(f"Blocked request from unauthorized origin/referer: {origin} / {referer}")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Access forbidden: Unauthorized origin", "status": "error"}
                )
        
        # If it's a browser request but missing both, it's suspicious for this specific app
        # But we'll allow it if it's not a browser (e.g. internal service) 
        # unless user wants to block EVERYTHING except those domains.
        
        return await call_next(request)

async def global_exception_handler(request: Request, exc: Exception):
    """
    Standardizes error responses across the API.
    """
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "status": "error"}
        )
    
    logger.exception(f"Unhandled exception occurred: {exc}")
    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal Server Error", "status": "error"}
    )
