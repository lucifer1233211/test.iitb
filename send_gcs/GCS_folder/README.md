# GCS_folder - Simplified GCS Web App

A simplified web-based Ground Control Station with a sample backend.

## Structure

- `frontend/` — Simple HTML UI (one-page design, clean interface)
- `backend/` — Sample Flask backend with basic endpoints
- `requirements.txt` — Python dependencies

## Quick Start

### 1. Install Dependencies
```bash
pip install flask flask-cors
```

### 2. Run Backend
```bash
cd backend
python app.py
```
Backend runs on: `http://localhost:5000`

### 3. Open Frontend
Open a web browser and go to:
```
http://localhost:5000
```

## Features

- **Mission Control**: Start/stop missions with model and prompt selection
- **Telemetry Display**: Altitude, speed, heading, battery, GPS status
- **Live Status**: Backend health, mission status indicators
- **Log Panel**: Real-time event logging

## API Endpoints

- `GET /health` — System health status
- `GET /telemetry` — Flight telemetry data
- `GET /models` — Available AI models
- `GET /missions/status` — Current mission status
- `POST /missions/start` — Start a new mission
- `POST /missions/stop` — Stop the current mission

## Notes

- This is a sample/demo implementation, not a production system
- Backend state is in-memory only (resets on restart)
- No database or persistent storage
