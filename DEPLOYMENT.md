# Digital Twin API Deployment Guide

## Overview

The Digital Twin API is now production-ready with comprehensive deployment configuration. The application uses FastAPI with uvicorn as the ASGI server.

## 🚀 Quick Start

### Required Start Command
```bash
uvicorn api.main:app --host 0.0.0.0 --port $PORT
```

### Environment Setup
1. Copy `.env.example` to `.env` and configure your settings
2. Install dependencies: `pip install -r requirements.txt`
3. Run the application with the start command

## 📁 Deployment Files Created

### Core Configuration
- **`Procfile`** - Heroku/cloud platform deployment configuration
- **`runtime.txt`** - Python 3.9.16 runtime specification
- **`.env.example`** - Environment variables template
- **`config.yaml`** - Application configuration

### Startup Scripts
- **`start.sh`** - Linux/macOS startup script
- **`start.bat`** - Windows startup script
- **`test_startup.py`** - Deployment verification script

## 🔧 Configuration

### Environment Variables
```bash
# Server Configuration
PORT=8000
ENVIRONMENT=production
HOST=0.0.0.0

# Database
DATABASE_URL=postgresql+asyncpg://user:password@your-railway-db.railway.app:5432/digital_twin

# Authentication
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Digital Twin
MAX_IT_POWER_KW=500
IDLE_POWER_FRACTION=0.4
AIR_FLOW_M3_S=8.0

# External Services
MQTT_BROKER_HOST=your-railway-mqtt.railway.app
MQTT_BROKER_PORT=1883
```

### Application Configuration
The `config.yaml` file contains comprehensive settings for:
- Patent objective weights (α, β, γ)
- Training parameters
- Environment physics constants
- Safety validation ranges
- Performance optimization settings

## 🏗️ Deployment Options

### 1. Heroku Deployment
```bash
# Create Heroku app
heroku create your-app-name

# Set environment variables
heroku config:set PORT=8000
heroku config:set ENVIRONMENT=production

# Deploy
git push heroku main
```

### 2. Docker Deployment
```dockerfile
FROM python:3.9.16

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE $PORT

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "$PORT"]
```

### 3. Direct Server Deployment
```bash
# Using startup script
chmod +x start.sh
./start.sh

# Or directly
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

## 🔍 API Endpoints

### Authentication Required
All endpoints require JWT authentication (except health check):

- **GET /api/health** - Health check
- **GET /api/state** - Get current digital twin state
- **GET /api/simulate/{hours}** - Run simulation
- **POST /api/optimize** - RL optimization
- **GET /api/anomaly_score** - Anomaly detection
- **WebSocket /ws/live** - Live state updates

### Example Usage
```bash
# Health check
curl https://function-bun-production-6ce5.up.railway.app/api/health

# Get state (requires auth token)
curl -H "Authorization: Bearer $TOKEN" \
     https://function-bun-production-6ce5.up.railway.app/api/state?utilisation=0.8&outside_temp=25.0
```

## ✅ Pre-Deployment Testing

Run the deployment verification script:
```bash
python test_startup.py
```

This tests:
- ✅ API module imports
- ✅ FastAPI app creation
- ✅ Application readiness

## 📊 Performance Features

### Production Optimizations
- **Async/await** for high concurrency
- **Connection pooling** for database
- **CORS middleware** for web integration
- **Structured logging** with configurable levels
- **Health checks** for monitoring

### Scaling Options
```bash
# Multiple workers
uvicorn api.main:app --host 0.0.0.0 --port $PORT --workers 4

# With SSL
uvicorn api.main:app --host 0.0.0.0 --port $PORT --ssl-keyfile key.pem --ssl-certfile cert.pem
```

## 🔒 Security Features

- **JWT authentication** with configurable expiration
- **CORS protection** with configurable origins
- **Input validation** with Pydantic models
- **SQL injection protection** via SQLAlchemy
- **Environment variable** configuration for secrets

## 📝 Monitoring & Logging

### Log Configuration
```python
# Logs are written to:
- Console (stdout/stderr)
- File: logs/api.log (configurable)
- Structured JSON format for log aggregation
```

### Health Monitoring
```bash
# Health check endpoint
curl https://function-bun-production-6ce5.up.railway.app/api/health

# Response
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

## 🚨 Troubleshooting

### Common Issues

1. **Database Connection Failed**
   - Check `DATABASE_URL` environment variable
   - Ensure PostgreSQL is running and accessible
   - Verify credentials and network connectivity

2. **Module Import Errors**
   - Run `pip install -r requirements.txt`
   - Check Python path configuration
   - Verify all dependencies are installed

3. **Port Already in Use**
   - Change PORT environment variable
   - Kill existing process: `lsof -ti:8000 | xargs kill`

4. **Authentication Failures**
   - Verify `SECRET_KEY` is set
   - Check token expiration settings
   - Ensure proper Authorization header format

### Debug Mode
```bash
# Enable debug logging
uvicorn api.main:app --host 0.0.0.0 --port $PORT --log-level debug
```

## 📈 Production Checklist

- [ ] Environment variables configured
- [ ] Database connection tested
- [ ] SSL certificates installed (if using HTTPS)
- [ ] Health checks passing
- [ ] Log rotation configured
- [ ] Monitoring and alerting set up
- [ ] Backup procedures documented
- [ ] Security audit completed
- [ ] Load testing performed
- [ ] Documentation updated

## 🌐 Repository

The deployment-ready code is available at:
https://github.com/08817711624aiml-coder/DigitalTwin

## 📞 Support

For deployment issues:
1. Check the logs: `tail -f logs/api.log`
2. Run the test script: `python test_startup.py`
3. Review this documentation
4. Check GitHub issues for known problems

---

**Note**: The application is designed to be cloud-agnostic and can be deployed on any platform that supports Python 3.9+ and the specified start command.
