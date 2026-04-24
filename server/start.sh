#!/bin/bash

# Production Startup Script for Booky Voice Agent FastAPI
# Binds to 0.0.0.0 and uses $PORT provided by the host (Railway, Render, etc.)

PORT=${PORT:-8000}
WORKERS=${WEB_CONCURRENCY:-1}

echo "Starting FastAPI server on port $PORT with $WORKERS workers..."

# Using uvicorn directly. For higher concurrency, gunicorn with uvicorn workers can be used:
# gunicorn main:app -w $WORKERS -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT

exec uvicorn main:app --host 0.0.0.0 --port $PORT --workers $WORKERS
