# IIT Bombay Security System

A full-stack campus security system with facial recognition via CCTV and drone footage, branded for IIT Bombay.

## Architecture

- **Frontend**: Next.js 16.2.1 (TypeScript, Tailwind CSS, shadcn/ui) on port 5000
- **Backend**: Python FastAPI on port 8000 (proxied via Next.js rewrites)
- **Database**: Replit PostgreSQL (auto-provisioned)
- **ML Pipeline**: MediaPipe BlazeFace (detection) + ArcFace ResNet100 ONNX (recognition, 512-dim embeddings)

## Dashboard Pages

All pages are under `src/app/dashboard/`:
- `/dashboard` - Main overview with system stats
- `/dashboard/cameras` - Camera list with search/filter
- `/dashboard/cameras/add` - Add new camera form
- `/dashboard/monitoring` - Live camera monitoring grid (2x2/3x3/4x4)
- `/dashboard/alerts` - Security alerts with severity/status filters
- `/dashboard/face-recognition/persons` - Enrolled persons list
- `/dashboard/face-recognition/enroll` - Enroll new person (upload face images)
- `/dashboard/face-recognition/detections` - Face detection history table
- `/dashboard/face-recognition/test` - Test face recognition (upload photo or live webcam with real-time detection/identification)
- `/dashboard/video-analysis` - Upload offline video files for face analysis
- `/dashboard/video-analysis/rtsp` - Connect to RTSP camera streams for real-time analysis
- `/dashboard/analytics` - Analytics metrics and charts
- `/dashboard/reports` - Generate security reports
- `/dashboard/users` - User management table
- `/dashboard/system/config` - System status and face recognition config
- `/dashboard/system/audit` - Audit log viewer
- `/dashboard/system/database` - Database stats

## Project Structure

```
campus-security-system-complete/
├── frontend/              # Next.js 16 app
│   ├── public/            # Static assets (iitb-logo.png)
│   ├── src/
│   │   ├── app/           # App Router pages (login, dashboard, sub-pages)
│   │   ├── components/    # UI components (shadcn/ui pattern)
│   │   ├── contexts/      # React contexts (auth, socket, notifications)
│   │   ├── hooks/         # Custom hooks
│   │   ├── lib/api/       # API client (auth.ts, face-recognition.ts, client.ts)
│   │   └── types/         # TypeScript types
│   ├── next.config.js     # Includes rewrite proxy /api/v1 → backend:8000
│   ├── package.json
│   └── tsconfig.json
├── backend_server/        # Clean Python FastAPI backend
│   ├── main.py            # All endpoints, models, seeding
│   ├── face_service.py    # Face recognition ML service
│   ├── models/            # ML model files (BlazeFace, ArcFace ONNX)
│   │   └── embeddings/    # Enrolled face embeddings (JSON)
│   └── uploads/           # Enrolled face images
├── backend/               # Original backend (reference only, not running)
└── docs/                  # Documentation
```

## Workflows

1. **Start application** - `cd campus-security-system-complete/frontend && npm run dev` (port 5000, webview)
2. **Backend API** - `cd campus-security-system-complete/backend_server && python main.py` (port 8000, console)

## API Routing

Frontend requests to `/api/v1/*` are proxied to the Python backend at `http://0.0.0.0:8000/api/v1/*` via Next.js rewrites in `next.config.js`.

## Backend Endpoints

- **Auth**: `/api/v1/auth/{login,logout,me,refresh,validate,sessions,change-password}`
- **Cameras**: `/api/v1/cameras` (CRUD, 12 seeded cameras with IIT Bombay locations)
- **Alerts**: `/api/v1/alerts` (CRUD, 25 seeded alerts)
- **Detections**: `/api/v1/detections` (100 seeded detection events)
- **Users**: `/api/v1/users` (list users)
- **System**: `/api/v1/system/{status,health,audit}`
- **Analytics**: `/api/v1/analytics`, `/api/v1/analytics/dashboard`
- **Face Recognition** (fully functional ML):
  - `POST /api/v1/face/detect` - Detect faces in uploaded image
  - `POST /api/v1/face/enroll` - Enroll person with face images
  - `POST /api/v1/face/bulk-enroll` - Bulk enroll multiple persons
  - `POST /api/v1/face/identify` - Identify unknown face against enrolled database
  - `POST /api/v1/face/verify` - Verify face matches specific person
  - `POST /api/v1/face/search-similar` - Search for similar faces
  - `GET /api/v1/face/enrolled` - List all enrolled persons
  - `GET /api/v1/face/health` - ML service health check
- **Video Analysis** (server-side OpenCV processing):
  - `POST /api/v1/video/upload-analyze` - Upload video file, get face detection report
  - `POST /api/v1/video/stream-analyze` - Upload video, get MJPEG stream with annotations
  - `POST /api/v1/video/rtsp/start` - Connect to RTSP stream for real-time processing
  - `GET /api/v1/video/rtsp/{id}/feed` - Get MJPEG feed from active RTSP stream
  - `POST /api/v1/video/rtsp/{id}/stop` - Stop an active RTSP stream
  - `GET /api/v1/video/rtsp/active` - List all active RTSP streams
  - `GET /api/v1/face/config` - Face recognition configuration
  - `GET/PATCH/DELETE /api/v1/face/persons/{id}` - Person management

## Face Recognition ML Pipeline

- **Detection**: MediaPipe BlazeFace (real-time, ~10ms per image)
- **Recognition**: ArcFace ResNet100 (ONNX, int8 quantized, ~63MB model)
- **Embeddings**: 512-dim L2-normalized vectors from ArcFace deep network
- **Matching**: Cosine similarity (verify threshold: 0.4, identify: 0.35, search: 0.25)
- **Fallback**: Handcrafted features (LBP+DCT+HOG+color histograms) when ArcFace unavailable
- **Storage**: Embeddings persisted as JSON files in `models/embeddings/`
- **Models**: BlazeFace TFLite + ArcFace ONNX in `models/` directory

## Demo Credentials

- **Admin**: admin@security.iitb.ac.in / admin123 (Prof. Rajesh Gupta)
- **Security Officer**: security@security.iitb.ac.in / security123 (Sunil Kumar Sharma)
- **Operator**: operator@security.iitb.ac.in / operator123 (Priya Deshmukh)

## Key Configuration

- **Port**: 5000 (frontend, required for Replit webview)
- **Backend Port**: 8000 (proxied through Next.js)
- **Host**: 0.0.0.0 (required for Replit proxy)
- **JWT**: Uses python-jose with HS256 tokens
- **Password Hashing**: bcrypt via passlib (bcrypt==4.0.1 for compatibility)
- **allowedDevOrigins**: Uses `REPLIT_DEV_DOMAIN` env var

## Permissions System

Backend returns granular permission strings (e.g., `camera:read`, `face:view`, `alert:read`) that match frontend `PERMISSIONS` constants in `src/types/auth.ts`. Sidebar items are filtered by these permissions per role.

## Provider Order (Important)

The React provider nesting order in `src/components/providers.tsx` must be:
```
QueryClientProvider > ThemeProvider > AuthProvider > NotificationProvider > SocketProvider
```
SocketProvider depends on NotificationProvider.

## Environment Variables

- `DATABASE_URL` - PostgreSQL connection string (auto-set by Replit)
- `JWT_SECRET` - JWT signing key (defaults to dev key)
- `REPLIT_DEV_DOMAIN` - Auto-set by Replit

## Dependencies

### Frontend (npm)
- next 16.2.1, react 19, typescript
- @radix-ui/react-slot, react-toast, react-dropdown-menu
- lucide-react, tailwindcss, axios, socket.io-client

### Backend (pip)
- fastapi, uvicorn, sqlalchemy, psycopg2-binary
- python-jose[cryptography], passlib[bcrypt], bcrypt==4.0.1
- pydantic[email], python-multipart
- mediapipe, opencv-python-headless, numpy, Pillow, scikit-learn
- onnxruntime (ArcFace model inference)

## Notes

- WebSocket shows "Disconnected" status (no WS server) - gracefully handled
- Original backend in `backend/` is reference only; `backend_server/` is the running backend
- Face recognition uses ArcFace ResNet100 ONNX for embeddings; falls back to handcrafted features if ONNX unavailable
- Old enrollments must be re-enrolled after ArcFace upgrade (embedding format changed)
- IIT Bombay branding: logo in `frontend/public/iitb-logo.png`, camera locations use real IITB buildings
- Camera locations: Main Gate, Central Library, KReSIT Building, SAC, Hostel 10, Hostel 4, Main Building, Gymkhana, Powai Lake Side perimeter
