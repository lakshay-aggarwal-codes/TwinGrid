#!/bin/bash

# Digital Twin API Startup Script
# Production deployment with uvicorn

# Set default port if not specified
export PORT=${PORT:-8000}

# Set environment variables for production
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export ENVIRONMENT="production"

# Create logs directory if it doesn't exist
mkdir -p logs

echo "Starting Digital Twin API Server..."
echo "Port: $PORT"
echo "Environment: $ENVIRONMENT"
echo "Timestamp: $(date)"

# Start the FastAPI application with uvicorn
exec uvicorn api.main:app --host 0.0.0.0 --port $PORT --workers 1 --log-level info
