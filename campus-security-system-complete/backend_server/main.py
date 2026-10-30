import asyncio
import csv
import io
import json
import os
import queue as stdlib_queue
import random
import threading
import uuid
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Depends, status, Query, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Float, Text, ForeignKey, JSON, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func

SECRET_KEY = os.environ.get("JWT_SECRET", "campus-security-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


# ─────────────────────────────────────────────────────────────────────────────
# SSE Notification Bus
# Clients subscribe via GET /api/v1/notifications/stream.
# Any server-side event (alert fired, camera added/deleted, person enrolled/deleted,
# rfdetr object detected, stream started/stopped) pushes a JSON payload to all
# connected clients instantly.
# ─────────────────────────────────────────────────────────────────────────────

class _NotificationBus:
    """Thread-safe fan-out notification bus for SSE clients."""

    def __init__(self):
        self._lock = threading.Lock()
        # Map of client_id -> asyncio.Queue (created per SSE connection)
        self._clients: Dict[str, asyncio.Queue] = {}

    def subscribe(self) -> tuple[str, asyncio.Queue]:
        """Register a new SSE client. Returns (client_id, async_queue)."""
        client_id = str(uuid.uuid4())
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        with self._lock:
            self._clients[client_id] = q
        return client_id, q

    def unsubscribe(self, client_id: str):
        with self._lock:
            self._clients.pop(client_id, None)

    def publish(self, event_type: str, payload: dict):
        """
        Push a notification to ALL connected SSE clients.
        Safe to call from background threads (uses call_soon_threadsafe).
        """
        message = {"event": event_type, "data": payload, "ts": datetime.now(timezone.utc).isoformat()}
        encoded = json.dumps(message)

        with self._lock:
            clients = list(self._clients.items())

        for client_id, q in clients:
            # Each SSE client lives in the main event loop.
            # We can't await here (we're in a bg thread), so use put_nowait.
            try:
                q.put_nowait(encoded)
            except asyncio.QueueFull:
                pass  # Slow client — drop rather than block
            except Exception:
                pass

    def publish_from_sync(self, event_type: str, payload: dict):
        """Alias of publish — works identically (both are thread-safe)."""
        self.publish(event_type, payload)


notification_bus = _NotificationBus()


# ─────────────────────────────────────────────────────────────────────────────
# ORM Models
# ─────────────────────────────────────────────────────────────────────────────

class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, default=lambda: str(uuid.uuid4()), unique=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="operator")
    department = Column(String, default="Security")
    phone = Column(String)
    employee_id = Column(String, unique=True)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    profile_image = Column(String)


class CameraDB(Base):
    __tablename__ = "cameras"
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, default=lambda: str(uuid.uuid4()), unique=True, index=True)
    name = Column(String, nullable=False)
    location = Column(String)
    building = Column(String)
    floor = Column(String)
    camera_type = Column(String, default="fixed")
    stream_url = Column(String)
    status = Column(String, default="online")
    is_active = Column(Boolean, default=True)
    resolution = Column(String, default="1920x1080")
    fps = Column(Integer, default=30)
    last_heartbeat = Column(DateTime(timezone=True))
    configuration = Column(JSON, default={})
    capabilities = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AlertDB(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, default=lambda: str(uuid.uuid4()), unique=True, index=True)
    alert_type = Column(String, nullable=False)
    severity = Column(String, default="medium")
    title = Column(String, nullable=False)
    description = Column(Text)
    message = Column(Text)
    location = Column(String)
    camera_id = Column(Integer, ForeignKey("cameras.id"))
    camera_name = Column(String)
    person_id = Column(String)
    person_name = Column(String)
    status = Column(String, default="active")
    is_active = Column(Boolean, default=True)
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    acknowledged_at = Column(DateTime(timezone=True))
    acknowledged_by = Column(String)
    resolved_at = Column(DateTime(timezone=True))
    resolved_by = Column(String)
    resolution_notes = Column(Text)
    extra_data = Column("metadata", JSON, default={})
    image_path = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DetectionEventDB(Base):
    __tablename__ = "detection_events"
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, default=lambda: str(uuid.uuid4()), unique=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"))
    camera_name = Column(String)
    confidence_score = Column(Float)
    person_id = Column(String)
    person_name = Column(String)
    location = Column(String)
    status = Column(String, default="confirmed")
    alert_triggered = Column(Boolean, default=False)
    bounding_box = Column(JSON)
    processing_time_ms = Column(Integer)
    alert_level = Column(String, default="low")
    detection_type = Column(String, default="face")
    extra_data = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLogDB(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user_name = Column(String)
    action = Column(String, nullable=False)
    resource = Column(String)
    resource_id = Column(String)
    details = Column(JSON, default={})
    ip_address = Column(String)
    user_agent = Column(String)
    status = Column(String, default="success")
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────────────────────
# Alert helper
# ─────────────────────────────────────────────────────────────────────────────

def create_face_alert(
    db: Session,
    alert_type: str,
    severity: str,
    person_name: str,
    person_id: Optional[str],
    camera_id: Optional[int],
    camera_name: Optional[str],
    location: Optional[str],
    confidence: float,
    cooldown_seconds: int = 60,
) -> Optional[AlertDB]:
    """
    Insert an alert row, but only if we haven't fired one for this
    (person_name + alert_type + camera_id) combo within the cooldown window.
    Publishes an SSE notification when a new alert is created.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)

    existing = (
        db.query(AlertDB)
        .filter(
            AlertDB.person_name == person_name,
            AlertDB.alert_type == alert_type,
            AlertDB.camera_id == camera_id,
            AlertDB.triggered_at >= cutoff,
        )
        .first()
    )
    if existing:
        return None  # Still in cooldown

    alert = AlertDB(
        uuid=str(uuid.uuid4()),
        alert_type=alert_type,
        severity=severity,
        title=_alert_title(alert_type, person_name),
        description=_alert_description(alert_type, person_name, confidence, location),
        location=location,
        camera_id=camera_id,
        camera_name=camera_name,
        person_id=person_id,
        person_name=person_name,
        status="active",
        triggered_at=datetime.now(timezone.utc),
        extra_data={"confidence": round(confidence, 3)},
    )
    db.add(alert)
    db.commit()

    # Push SSE notification to all connected dashboard clients
    notification_bus.publish("new_alert", {
        "id": alert.uuid,
        "alert_type": alert_type,
        "severity": severity,
        "title": alert.title,
        "description": alert.description,
        "person_name": person_name,
        "location": location,
        "camera_name": camera_name,
        "timestamp": alert.triggered_at.isoformat(),
    })

    return alert


def create_rfdetr_alert(
    db: Session,
    alert_type: str,
    severity: str,
    object_label: str,
    camera_id: Optional[int],
    camera_name: Optional[str],
    location: Optional[str],
    confidence: float,
    cooldown_seconds: int = 120,
) -> Optional[AlertDB]:
    """
    Insert an alert row for RF-DETR object detections, with cooldown
    per (object_label + alert_type + camera_id) combo.
    Publishes an SSE notification when a new alert is created.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)

    existing = (
        db.query(AlertDB)
        .filter(
            AlertDB.person_name == object_label,
            AlertDB.alert_type == alert_type,
            AlertDB.camera_id == camera_id,
            AlertDB.triggered_at >= cutoff,
        )
        .first()
    )
    if existing:
        return None

    alert = AlertDB(
        uuid=str(uuid.uuid4()),
        alert_type=alert_type,
        severity=severity,
        title=_rfdetr_alert_title(alert_type, object_label),
        description=_rfdetr_alert_description(alert_type, object_label, confidence, location),
        location=location,
        camera_id=camera_id,
        camera_name=camera_name,
        person_id=None,
        person_name=object_label,
        status="active",
        triggered_at=datetime.now(timezone.utc),
        extra_data={"confidence": round(confidence, 3), "detection_type": "object"},
    )
    db.add(alert)
    db.commit()

    notification_bus.publish("new_alert", {
        "id": alert.uuid,
        "alert_type": alert_type,
        "severity": severity,
        "title": alert.title,
        "description": alert.description,
        "person_name": object_label,
        "location": location,
        "camera_name": camera_name,
        "timestamp": alert.triggered_at.isoformat(),
    })

    return alert


def create_detection_event(
    db: Session,
    person_name: str,
    person_id: Optional[str],
    camera_id: Optional[int],
    camera_name: Optional[str],
    location: Optional[str],
    confidence: float,
    bounding_box: Optional[dict] = None,
    processing_time_ms: Optional[int] = None,
    identified: bool = False,
    detection_type: str = "face",
    detection_source: str = "face",
) -> DetectionEventDB:
    status_value = "identified" if identified else "unknown"
    alert_level = "low" if identified else "high"
    event = DetectionEventDB(
        uuid=str(uuid.uuid4()),
        camera_id=camera_id,
        camera_name=camera_name,
        confidence_score=confidence,
        person_id=person_id,
        person_name=person_name,
        location=location,
        status=status_value,
        alert_triggered=not identified,
        bounding_box=bounding_box,
        processing_time_ms=processing_time_ms,
        alert_level=alert_level,
        detection_type=detection_type,
        extra_data={"detection_source": detection_source},
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    notification_bus.publish("detection_created", {
        "id": event.uuid,
        "camera_id": str(camera_id) if camera_id else None,
        "camera_name": camera_name,
        "person_id": person_id,
        "person_name": person_name,
        "location": location,
        "confidence": confidence,
        "status": status_value,
        "alert_level": alert_level,
        "detection_type": detection_type,
        "detection_source": detection_source,
        "timestamp": event.created_at.isoformat(),
    })

    return event


def _alert_title(alert_type: str, person_name: str) -> str:
    return {
        "unknown_person":       "Unknown Person Detected",
        "low_confidence_match": f"Low-Confidence Match: {person_name}",
        "face_recognized":      f"Person Identified: {person_name}",
        "unauthorized_access":  "Unauthorized Access Attempt",
    }.get(alert_type, f"Alert: {person_name}")


def _alert_description(alert_type: str, person_name: str, confidence: float, location: Optional[str]) -> str:
    pct = f"{confidence * 100:.1f}%"
    loc = location or "unknown location"
    return {
        "unknown_person":       f"Unrecognized face detected at {loc} (confidence {pct}). No match in enrolled database.",
        "low_confidence_match": f"Possible match for '{person_name}' at {loc} with low confidence ({pct}). Manual review needed.",
        "face_recognized":      f"'{person_name}' was identified at {loc} with {pct} confidence.",
        "unauthorized_access":  f"Access attempt at {loc} by unrecognized individual (confidence {pct}).",
    }.get(alert_type, f"Detection event at {loc} with confidence {pct}.")


def _rfdetr_alert_title(alert_type: str, object_label: str) -> str:
    return {
        "object_detected":      f"Object Detected: {object_label}",
        "object_high_confidence": f"High-Confidence Object: {object_label}",
        "object_suspicious":    f"Suspicious Object: {object_label}",
    }.get(alert_type, f"RF-DETR Alert: {object_label}")


def _rfdetr_alert_description(alert_type: str, object_label: str, confidence: float, location: Optional[str]) -> str:
    pct = f"{confidence * 100:.1f}%"
    loc = location or "unknown location"
    return {
        "object_detected":      f"RF-DETR detected '{object_label}' at {loc} with {pct} confidence.",
        "object_high_confidence": f"High-confidence RF-DETR detection of '{object_label}' at {loc} ({pct}).",
        "object_suspicious":    f"Suspicious object '{object_label}' detected at {loc} ({pct}). Review recommended.",
    }.get(alert_type, f"RF-DETR object '{object_label}' detected at {loc} with {pct} confidence.")


Base.metadata.create_all(bind=engine)


# ─────────────────────────────────────────────────────────────────────────────
# Permissions / Roles
# ─────────────────────────────────────────────────────────────────────────────

ALL_PERMISSIONS = [
    {"id": "perm_user_create",      "name": "user:create",      "description": "Create users",             "resource": "user",      "action": "create"},
    {"id": "perm_user_read",        "name": "user:read",        "description": "View users",               "resource": "user",      "action": "read"},
    {"id": "perm_user_update",      "name": "user:update",      "description": "Update users",             "resource": "user",      "action": "update"},
    {"id": "perm_user_delete",      "name": "user:delete",      "description": "Delete users",             "resource": "user",      "action": "delete"},
    {"id": "perm_face_enroll",      "name": "face:enroll",      "description": "Enroll faces",             "resource": "face",      "action": "enroll"},
    {"id": "perm_face_identify",    "name": "face:identify",    "description": "Identify faces",           "resource": "face",      "action": "identify"},
    {"id": "perm_face_delete",      "name": "face:delete",      "description": "Delete enrolled faces",    "resource": "face",      "action": "delete"},
    {"id": "perm_face_view",        "name": "face:view",        "description": "View face recognition data","resource": "face",     "action": "view"},
    {"id": "perm_camera_create",    "name": "camera:create",    "description": "Create cameras",           "resource": "camera",    "action": "create"},
    {"id": "perm_camera_read",      "name": "camera:read",      "description": "View cameras",             "resource": "camera",    "action": "read"},
    {"id": "perm_camera_update",    "name": "camera:update",    "description": "Update cameras",           "resource": "camera",    "action": "update"},
    {"id": "perm_camera_delete",    "name": "camera:delete",    "description": "Delete cameras",           "resource": "camera",    "action": "delete"},
    {"id": "perm_camera_control",   "name": "camera:control",   "description": "Control cameras",          "resource": "camera",    "action": "control"},
    {"id": "perm_alert_create",     "name": "alert:create",     "description": "Create alerts",            "resource": "alert",     "action": "create"},
    {"id": "perm_alert_read",       "name": "alert:read",       "description": "View alerts",              "resource": "alert",     "action": "read"},
    {"id": "perm_alert_update",     "name": "alert:update",     "description": "Update alerts",            "resource": "alert",     "action": "update"},
    {"id": "perm_alert_delete",     "name": "alert:delete",     "description": "Delete alerts",            "resource": "alert",     "action": "delete"},
    {"id": "perm_alert_acknowledge","name": "alert:acknowledge", "description": "Acknowledge alerts",       "resource": "alert",     "action": "acknowledge"},
    {"id": "perm_system_config",    "name": "system:config",    "description": "System configuration",     "resource": "system",    "action": "config"},
    {"id": "perm_system_logs",      "name": "system:logs",      "description": "View system logs",         "resource": "system",    "action": "logs"},
    {"id": "perm_system_backup",    "name": "system:backup",    "description": "System backup",            "resource": "system",    "action": "backup"},
    {"id": "perm_system_restore",   "name": "system:restore",   "description": "System restore",           "resource": "system",    "action": "restore"},
    {"id": "perm_report_view",      "name": "report:view",      "description": "View reports",             "resource": "report",    "action": "view"},
    {"id": "perm_report_export",    "name": "report:export",    "description": "Export reports",           "resource": "report",    "action": "export"},
    {"id": "perm_analytics_view",   "name": "analytics:view",   "description": "View analytics",           "resource": "analytics", "action": "view"},
    {"id": "perm_audit_view",       "name": "audit:view",       "description": "View audit logs",          "resource": "audit",     "action": "view"},
    {"id": "perm_audit_export",     "name": "audit:export",     "description": "Export audit logs",        "resource": "audit",     "action": "export"},
]


def _perms_by_name(*names):
    return [p for p in ALL_PERMISSIONS if p["name"] in names]


ROLE_PERMISSIONS = {
    "admin": list(ALL_PERMISSIONS),
    "security_officer": _perms_by_name(
        "camera:read", "camera:update", "camera:control",
        "alert:read", "alert:update", "alert:acknowledge", "alert:create",
        "face:view", "face:enroll", "face:identify",
        "analytics:view", "report:view",
        "user:read",
    ),
    "operator": _perms_by_name(
        "camera:read",
        "alert:read",
        "face:view", "face:identify",
        "analytics:view",
    ),
}

ROLE_INFO = {
    "admin":            {"id": "role_admin",    "name": "Administrator",    "description": "Full system administrator"},
    "security_officer": {"id": "role_security", "name": "Security Officer", "description": "Security monitoring and response"},
    "operator":         {"id": "role_operator", "name": "Operator",         "description": "Camera operator and monitoring"},
}


# ─────────────────────────────────────────────────────────────────────────────
# DB / Auth helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(UserDB).filter(UserDB.email == email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    return user


def optional_get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db),
):
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            return None
        user = db.query(UserDB).filter(UserDB.email == email).first()
        return user if user and user.is_active else None
    except Exception:
        return None


def require_roles(*allowed_roles):
    def checker(user: UserDB = Depends(get_current_user)):
        if user.role not in allowed_roles and not user.is_superuser:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker


def format_user_response(user: UserDB):
    role_key = user.role or "operator"
    role_info = ROLE_INFO.get(role_key, ROLE_INFO["operator"])
    permissions = ROLE_PERMISSIONS.get(role_key, ROLE_PERMISSIONS["operator"])
    return {
        "id": user.uuid,
        "email": user.email,
        "full_name": user.name,
        "department": user.department,
        "phone": user.phone,
        "employee_id": user.employee_id,
        "role": role_info,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else datetime.now(timezone.utc).isoformat(),
        "updated_at": user.updated_at.isoformat() if user.updated_at else datetime.now(timezone.utc).isoformat(),
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "permissions": permissions,
        "profile_image": user.profile_image,
    }


def _format_camera(c: CameraDB) -> dict:
    return {
        "id": c.uuid,
        "name": c.name,
        "location": c.location,
        "camera_type": c.camera_type,
        "stream_url": c.stream_url or "",
        "is_active": c.is_active,
        "status": c.status,
        "settings": {
            "resolution": c.resolution,
            "fps": c.fps,
            "quality": 80,
            "night_vision": False,
            "motion_detection": True,
            "face_detection_enabled": True,
            "person_reidentification_enabled": (c.configuration or {}).get("person_reidentification_enabled", True),
            "recording_enabled": False,
            "detection_interval": 5,
            "confidence_threshold": 0.8,
        },
        "capabilities": c.capabilities or {},
        "coordinates": None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "last_heartbeat": c.last_heartbeat.isoformat() if c.last_heartbeat else None,
        "stream_active": c.status == "online",
    }


def _analytics_days(period: str) -> int:
    return {
        "24h": 1,
        "1d": 1,
        "7d": 7,
        "30d": 30,
        "90d": 90,
    }.get(period, 7)


def _as_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_report_date(value: Optional[str], label: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{label} must be in YYYY-MM-DD format")


def _report_window(start_date: Optional[str], end_date: Optional[str]) -> tuple[Optional[datetime], Optional[datetime]]:
    start = _parse_report_date(start_date, "start_date")
    end = _parse_report_date(end_date, "end_date")
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="Start date cannot be after end date")
    return start, end + timedelta(days=1) if end else None


def _filter_between(query, column, start: Optional[datetime], end_exclusive: Optional[datetime]):
    if start:
        query = query.filter(column >= start)
    if end_exclusive:
        query = query.filter(column < end_exclusive)
    return query


def _csv_response(report_type: str, start_date: Optional[str], end_date: Optional[str], rows: list[dict]) -> Response:
    output = io.StringIO()
    headers = list(rows[0].keys()) if rows else ["message"]
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    if rows:
        writer.writerows(rows)
    else:
        writer.writerow({"message": "No records found for the selected date range"})

    safe_start = start_date or "all"
    safe_end = end_date or "latest"
    filename = f"{report_type}_{safe_start}_to_{safe_end}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="IIT Bombay Security System API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def basic_health_check():
    """Lightweight liveness check that does not require a database query."""
    return {"status": "ok", "service": "Campus Security API"}


# ─────────────────────────────────────────────────────────────────────────────
# SSE Notification endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/notifications/stream")
async def notification_stream(
    token: str = Query(None),
    user: UserDB = Depends(optional_get_current_user),
):
    """
    Server-Sent Events endpoint. The frontend connects once and receives push
    notifications for: new_alert, camera_added, camera_deleted, person_enrolled,
    person_deleted, stream_started, stream_stopped, rfdetr_detection,
    detection_created, alert_updated.

    Accepts ?token=<jwt> as a fallback for browser EventSource which can't set
    Authorization headers.
    """
    # Token-based fallback auth (EventSource can't set headers)
    if not user and token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email = payload.get("sub")
            if email:
                db = SessionLocal()
                try:
                    user = db.query(UserDB).filter(UserDB.email == email).first()
                    if user and not user.is_active:
                        user = None
                finally:
                    db.close()
        except Exception:
            pass

    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    client_id, q = notification_bus.subscribe()

    async def event_generator():
        # Send an immediate "connected" ping so the client knows the SSE is live
        yield f"data: {json.dumps({'event': 'connected', 'data': {'client_id': client_id}, 'ts': datetime.now(timezone.utc).isoformat()})}\n\n"
        try:
            while True:
                try:
                    # Wait up to 25 s then send a keepalive comment so proxies
                    # don't close the connection
                    message = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # SSE keepalive comment (ignored by browsers but keeps TCP alive)
                    yield ": keepalive\n\n"
                except asyncio.CancelledError:
                    break
        except Exception as e:
            print(f"[SSE] Client {client_id} error: {e}")
        finally:
            notification_bus.unsubscribe(client_id)
            print(f"[SSE] Client {client_id} disconnected")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auth endpoints
# ─────────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@app.post("/api/v1/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.email == req.email).first()
    if not user or not pwd_context.verify(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    access_token = create_access_token({"sub": user.email})
    refresh_token = create_refresh_token({"sub": user.email})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": format_user_response(user),
    }


@app.post("/api/v1/auth/logout")
def logout(user: UserDB = Depends(get_current_user)):
    return {"message": "Logged out successfully"}


@app.get("/api/v1/auth/me")
def get_me(user: UserDB = Depends(get_current_user)):
    return format_user_response(user)


@app.patch("/api/v1/auth/me")
def update_me(
    updates: dict,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if "full_name" in updates:
        user.name = updates["full_name"]
    if "phone" in updates:
        user.phone = updates["phone"]
    if "department" in updates:
        user.department = updates["department"]
    db.commit()
    db.refresh(user)
    return format_user_response(user)


@app.post("/api/v1/auth/refresh")
def refresh_token(req: RefreshRequest, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(req.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        email = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = db.query(UserDB).filter(UserDB.email == email).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or disabled")

    access_token = create_access_token({"sub": email})
    new_refresh = create_refresh_token({"sub": email})
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@app.get("/api/v1/auth/validate")
def validate_token(user: UserDB = Depends(get_current_user)):
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return {"valid": True, "expires_at": expires_at.isoformat()}


@app.get("/api/v1/auth/sessions")
def get_sessions(user: UserDB = Depends(get_current_user)):
    return [{
        "id": str(uuid.uuid4()),
        "ip_address": "10.0.0.1",
        "user_agent": "Mozilla/5.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_activity": datetime.now(timezone.utc).isoformat(),
        "is_current": True,
    }]


@app.delete("/api/v1/auth/sessions/{session_id}")
def revoke_session(session_id: str, user: UserDB = Depends(get_current_user)):
    return {"message": "Session revoked"}


@app.post("/api/v1/auth/revoke-all-sessions")
def revoke_all_sessions(user: UserDB = Depends(get_current_user)):
    return {"message": "All sessions revoked"}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/v1/auth/change-password")
def change_password(
    data: ChangePasswordRequest,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not pwd_context.verify(data.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    user.hashed_password = pwd_context.hash(data.new_password)
    db.commit()
    return {"message": "Password changed successfully"}


@app.post("/api/v1/auth/reset-password")
def reset_password(data: dict):
    return {"message": "If the email exists, a reset link has been sent"}


@app.post("/api/v1/auth/reset-password/confirm")
def reset_password_confirm(data: dict):
    return {"message": "Password has been reset successfully"}


@app.post("/api/v1/auth/me/profile-image")
def upload_profile_image(user: UserDB = Depends(get_current_user)):
    return {"profile_image": None}


# ─────────────────────────────────────────────────────────────────────────────
# Camera endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/cameras")
def list_cameras(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    camera_type: Optional[str] = None,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(CameraDB).filter(CameraDB.is_active == True)
    if status:
        query = query.filter(CameraDB.status == status)
    if camera_type:
        query = query.filter(CameraDB.camera_type == camera_type)

    total = query.count()
    cameras = query.offset((page - 1) * size).limit(size).all()
    pages = max(1, (total + size - 1) // size)

    return {
        "items": [_format_camera(c) for c in cameras],
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
        "has_next": page < pages,
        "has_prev": page > 1,
    }


@app.post("/api/v1/cameras")
def create_camera(
    data: dict = Body(...),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resolution_map = {"720p": "1280x720", "1080p": "1920x1080", "1440p": "2560x1440", "4K": "3840x2160"}
    camera = CameraDB(
        name=data.get("name", "New Camera"),
        location=data.get("location", ""),
        building=data.get("building", ""),
        floor=data.get("floor", ""),
        camera_type=data.get("camera_type", "fixed"),
        stream_url=data.get("stream_url", ""),
        status="online",
        is_active=True,
        resolution=resolution_map.get(data.get("resolution", "1080p"), data.get("resolution", "1920x1080")),
        fps=30,
        configuration={
            "ip_address": data.get("ip_address", ""),
            "zone": data.get("zone", ""),
            "description": data.get("description", ""),
            "person_reidentification_enabled": bool(data.get("person_reidentification_enabled", True)),
        },
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)

    # Notify all SSE clients
    notification_bus.publish("camera_added", {
        "id": camera.uuid,
        "name": camera.name,
        "location": camera.location,
        "camera_type": camera.camera_type,
        "status": camera.status,
        "added_by": user.name,
    })

    return _format_camera(camera)


@app.get("/api/v1/cameras/{camera_id}")
def get_camera(
    camera_id: str,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    camera = db.query(CameraDB).filter(CameraDB.uuid == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return _format_camera(camera)


@app.delete("/api/v1/cameras/{camera_id}")
def delete_camera(
    camera_id: str,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    camera = db.query(CameraDB).filter(CameraDB.uuid == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    camera_name = camera.name
    camera_location = camera.location

    db.delete(camera)
    db.commit()

    # Notify all SSE clients
    notification_bus.publish("camera_deleted", {
        "id": camera_id,
        "name": camera_name,
        "location": camera_location,
        "deleted_by": user.name,
    })

    return {"message": "Camera deleted successfully"}


# ─────────────────────────────────────────────────────────────────────────────
# Alert endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/alerts")
def list_alerts(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    severity: Optional[str] = None,
    alert_status: Optional[str] = Query(None, alias="status"),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(AlertDB)
    if severity:
        query = query.filter(AlertDB.severity == severity)
    if alert_status:
        query = query.filter(AlertDB.status == alert_status)

    total = query.count()
    alerts = query.order_by(AlertDB.triggered_at.desc()).offset((page - 1) * size).limit(size).all()
    pages = max(1, (total + size - 1) // size)

    items = []
    for a in alerts:
        items.append({
            "id": a.uuid,
            "type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "message": a.description or a.message or "",
            "camera_id": str(a.camera_id) if a.camera_id else None,
            "camera_name": a.camera_name,
            "person_id": a.person_id,
            "person_name": a.person_name,
            "location": a.location,
            "metadata": a.extra_data or {},
            "timestamp": a.triggered_at.isoformat() if a.triggered_at else None,
            "status": a.status,
            "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
            "acknowledged_by": a.acknowledged_by,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            "resolved_by": a.resolved_by,
            "image_path": a.image_path,
            "video_path": None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
        "has_next": page < pages,
        "has_prev": page > 1,
    }


@app.patch("/api/v1/alerts/{alert_id}")
def update_alert(
    alert_id: str,
    data: dict,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    alert = db.query(AlertDB).filter(AlertDB.uuid == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if "status" in data:
        old_status = alert.status
        alert.status = data["status"]
        if data["status"] == "acknowledged":
            alert.acknowledged_at = datetime.now(timezone.utc)
            alert.acknowledged_by = user.name
        elif data["status"] == "resolved":
            alert.resolved_at = datetime.now(timezone.utc)
            alert.resolved_by = user.name
        db.commit()

        # Notify clients of status change
        notification_bus.publish("alert_updated", {
            "id": alert_id,
            "old_status": old_status,
            "new_status": data["status"],
            "updated_by": user.name,
            "title": alert.title,
        })
    return {"message": "Alert updated"}


# ─────────────────────────────────────────────────────────────────────────────
# Detection endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/detections")
def list_detections(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(DetectionEventDB)
    total = query.count()
    events = query.order_by(DetectionEventDB.created_at.desc()).offset((page - 1) * size).limit(size).all()
    pages = max(1, (total + size - 1) // size)

    items = []
    for e in events:
        items.append({
            "id": e.uuid,
            "camera_id": str(e.camera_id) if e.camera_id else None,
            "camera_name": e.camera_name or "Unknown Camera",
            "confidence": e.confidence_score or 0,
            "quality_score": round(random.uniform(0.7, 0.99), 2),
            "person_id": e.person_id,
            "person_name": e.person_name,
            "location": e.location,
            "bbox": e.bounding_box or {"x": 100, "y": 100, "width": 150, "height": 200},
            "is_spoofing_detected": False,
            "alert_level": e.alert_level or "low",
            "timestamp": e.created_at.isoformat() if e.created_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "status": e.status,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
        "has_next": page < pages,
        "has_prev": page > 1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Report export endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/reports/{report_type}/download")
def download_report(
    report_type: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end_exclusive = _report_window(start_date, end_date)

    if report_type == "incident_log":
        query = _filter_between(db.query(AlertDB), AlertDB.triggered_at, start, end_exclusive)
        alerts = query.order_by(AlertDB.triggered_at.desc()).all()
        rows = [{
            "incident_id": a.uuid,
            "timestamp": a.triggered_at.isoformat() if a.triggered_at else "",
            "type": a.alert_type,
            "severity": a.severity,
            "status": a.status,
            "title": a.title,
            "message": a.description or a.message or "",
            "camera": a.camera_name or "",
            "location": a.location or "",
            "person_id": a.person_id or "",
            "person_name": a.person_name or "",
            "acknowledged_by": a.acknowledged_by or "",
            "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else "",
            "resolved_by": a.resolved_by or "",
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else "",
        } for a in alerts]

    elif report_type == "detection_report":
        query = _filter_between(db.query(DetectionEventDB), DetectionEventDB.created_at, start, end_exclusive)
        events = query.order_by(DetectionEventDB.created_at.desc()).all()
        rows = [{
            "detection_id": e.uuid,
            "timestamp": e.created_at.isoformat() if e.created_at else "",
            "camera": e.camera_name or "",
            "location": e.location or "",
            "person_id": e.person_id or "",
            "person_name": e.person_name or "Unknown",
            "confidence": round(e.confidence_score or 0, 4),
            "status": e.status or "",
            "alert_level": e.alert_level or "",
            "alert_triggered": "yes" if e.alert_triggered else "no",
            "processing_time_ms": e.processing_time_ms or "",
        } for e in events]

    elif report_type == "camera_status":
        detection_query = _filter_between(db.query(DetectionEventDB), DetectionEventDB.created_at, start, end_exclusive)
        alert_query = _filter_between(db.query(AlertDB), AlertDB.triggered_at, start, end_exclusive)
        cameras = db.query(CameraDB).order_by(CameraDB.name.asc()).all()
        rows = []
        for c in cameras:
            detection_count = detection_query.filter(DetectionEventDB.camera_id == c.id).count()
            alert_count = alert_query.filter(AlertDB.camera_id == c.id).count()
            rows.append({
                "camera_id": c.uuid,
                "camera_name": c.name,
                "location": c.location or "",
                "building": c.building or "",
                "floor": c.floor or "",
                "type": c.camera_type or "",
                "status": c.status,
                "active": "yes" if c.is_active else "no",
                "resolution": c.resolution or "",
                "fps": c.fps or "",
                "last_heartbeat": c.last_heartbeat.isoformat() if c.last_heartbeat else "",
                "detections_in_range": detection_count,
                "alerts_in_range": alert_count,
                "created_at": c.created_at.isoformat() if c.created_at else "",
            })

    elif report_type == "security_summary":
        alert_query = _filter_between(db.query(AlertDB), AlertDB.triggered_at, start, end_exclusive)
        detection_query = _filter_between(db.query(DetectionEventDB), DetectionEventDB.created_at, start, end_exclusive)
        alerts = alert_query.all()
        detections = detection_query.all()
        cameras = db.query(CameraDB).all()

        rows = [
            {"section": "Date Range", "metric": "Start Date", "value": start_date or "All records"},
            {"section": "Date Range", "metric": "End Date", "value": end_date or "Latest"},
            {"section": "Alerts", "metric": "Total Alerts", "value": len(alerts)},
            {"section": "Alerts", "metric": "Active Alerts", "value": sum(1 for a in alerts if a.status == "active")},
            {"section": "Alerts", "metric": "Acknowledged Alerts", "value": sum(1 for a in alerts if a.status == "acknowledged")},
            {"section": "Alerts", "metric": "Resolved Alerts", "value": sum(1 for a in alerts if a.status == "resolved")},
            {"section": "Detections", "metric": "Total Detections", "value": len(detections)},
            {"section": "Detections", "metric": "Identified Persons", "value": sum(1 for d in detections if d.status == "identified")},
            {"section": "Detections", "metric": "Unknown Persons", "value": sum(1 for d in detections if d.status == "unknown")},
            {"section": "Cameras", "metric": "Total Cameras", "value": len(cameras)},
            {"section": "Cameras", "metric": "Online Cameras", "value": sum(1 for c in cameras if c.status == "online")},
            {"section": "Cameras", "metric": "Offline Cameras", "value": sum(1 for c in cameras if c.status == "offline")},
        ]

        for severity in ["critical", "high", "medium", "low"]:
            rows.append({
                "section": "Alert Severity",
                "metric": severity.title(),
                "value": sum(1 for a in alerts if a.severity == severity),
            })

        by_camera: Dict[str, int] = {}
        for event in detections:
            camera = event.camera_name or "Unknown Camera"
            by_camera[camera] = by_camera.get(camera, 0) + 1
        for camera, count in sorted(by_camera.items(), key=lambda item: item[1], reverse=True)[:10]:
            rows.append({"section": "Top Detection Cameras", "metric": camera, "value": count})

    else:
        raise HTTPException(status_code=404, detail="Unknown report type")

    db.add(AuditLogDB(
        user_id=user.id,
        user_name=user.name,
        action="export_report",
        resource="report",
        resource_id=report_type,
        details={"start_date": start_date, "end_date": end_date, "format": "csv"},
        status="success",
        timestamp=datetime.now(timezone.utc),
    ))
    db.commit()

    return _csv_response(report_type, start_date, end_date, rows)


# ─────────────────────────────────────────────────────────────────────────────
# User endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/users")
def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total = db.query(UserDB).count()
    users = db.query(UserDB).offset((page - 1) * size).limit(size).all()
    pages = max(1, (total + size - 1) // size)
    return {
        "items": [format_user_response(u) for u in users],
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
        "has_next": page < pages,
        "has_prev": page > 1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# System endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/system/status")
def system_status(user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    active_cameras = db.query(CameraDB).filter(CameraDB.status == "online").count()
    total_cameras = db.query(CameraDB).count()
    active_alerts = db.query(AlertDB).filter(AlertDB.status == "active").count()
    total_detections = db.query(DetectionEventDB).count()

    return {
        "status": "operational",
        "uptime": round(random.uniform(99.5, 99.99), 2),
        "cpu_usage": round(random.uniform(15, 45), 1),
        "memory_usage": round(random.uniform(30, 60), 1),
        "disk_usage": round(random.uniform(20, 50), 1),
        "active_cameras": active_cameras,
        "total_cameras": total_cameras,
        "active_detections": total_detections,
        "alerts_count": {
            "active": active_alerts,
            "acknowledged": db.query(AlertDB).filter(AlertDB.status == "acknowledged").count(),
            "resolved": db.query(AlertDB).filter(AlertDB.status == "resolved").count(),
        },
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/system/health")
def health_check():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "database": db_ok,
        "redis": False,
        "ml_models": False,
        "services": {
            "database": db_ok,
            "authentication": True,
            "camera_manager": True,
            "alert_engine": True,
            "face_recognition": False,
            "stream_processor": False,
            "rfdetr_object_detection": False,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Analytics endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/analytics")
def get_analytics(
    period: str = Query("7d"),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    days = _analytics_days(period)
    start_date = now - timedelta(days=days)

    period_events = (
        db.query(DetectionEventDB)
        .filter(DetectionEventDB.created_at >= start_date)
        .all()
    )

    total_detections = len(period_events)
    all_time_detections = db.query(DetectionEventDB).count()
    total_cameras = db.query(CameraDB).count()
    active_cameras = db.query(CameraDB).filter(CameraDB.status == "online").count()
    active_alerts = (
        db.query(AlertDB)
        .filter(AlertDB.status == "active", AlertDB.triggered_at >= start_date)
        .count()
    )

    face_events = [
        event for event in period_events
        if (event.detection_type or "face") == "face"
    ]
    object_events = [
        event for event in period_events
        if event.detection_type == "object"
    ]

    rfdetr_events = [
        event for event in object_events
        if event.extra_data and event.extra_data.get("detection_source") == "rfdetr"
    ]

    identified_events = [
        event for event in face_events
        if event.person_name and event.person_name.lower() != "unknown"
    ]
    false_positive_count = sum(1 for event in period_events if event.status == "false_positive")
    unique_person_keys = {
        event.person_id or event.person_name
        for event in identified_events
        if event.person_id or event.person_name
    }

    unique_object_classes = len(
        {event.person_name for event in object_events if event.person_name}
    )
    top_object_classes = []
    if object_events:
        object_class_counts: Dict[str, int] = {}
        for event in object_events:
            label = event.person_name or "unknown"
            object_class_counts[label] = object_class_counts.get(label, 0) + 1
        top_object_classes = [
            {"label": label, "count": count}
            for label, count in sorted(
                object_class_counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:8]
        ]

    rfdetr_class_counts: Dict[str, int] = {}
    rfdetr_confidences: Dict[str, List[float]] = {}
    for event in rfdetr_events:
        label = event.person_name or "unknown"
        rfdetr_class_counts[label] = rfdetr_class_counts.get(label, 0) + 1
        conf = event.confidence_score or 0.0
        rfdetr_confidences.setdefault(label, []).append(conf)

    top_rfdetr_classes = [
        {"label": label, "count": count, "avg_confidence": round(sum(rfdetr_confidences[label]) / len(rfdetr_confidences[label]), 4)}
        for label, count in sorted(rfdetr_class_counts.items(), key=lambda item: item[1], reverse=True)[:8]
    ]

    if total_detections:
        identification_accuracy = (len(identified_events) / max(1, len(face_events))) * 100
        false_positive_rate = (false_positive_count / total_detections) * 100
    else:
        identification_accuracy = 0
        false_positive_rate = 0

    detections_over_time = []
    object_detections_over_time = []
    rfdetr_detections_over_time = []
    for i in range(days):
        d = (start_date + timedelta(days=i)).date()
        day_events = [
            event for event in period_events
            if _as_aware_utc(event.created_at) and _as_aware_utc(event.created_at).date() == d
        ]
        day_face = [
            event for event in day_events
            if (event.detection_type or "face") == "face"
        ]
        day_object = [
            event for event in day_events
            if event.detection_type == "object"
        ]
        day_rfdetr = [
            event for event in day_object
            if event.extra_data and event.extra_data.get("detection_source") == "rfdetr"
        ]
        detections_over_time.append({
            "date": d.strftime("%Y-%m-%d"),
            "count": len(day_events),
            "identified": sum(
                1 for event in day_face
                    if event.person_name and event.person_name.lower() != "unknown"
            ),
        })
        object_detections_over_time.append({
            "date": d.strftime("%Y-%m-%d"),
            "count": len(day_object),
        })
        rfdetr_detections_over_time.append({
            "date": d.strftime("%Y-%m-%d"),
            "count": len(day_rfdetr),
        })

    hourly_counts = {h: 0 for h in range(24)}
    object_hourly_counts = {h: 0 for h in range(24)}
    rfdetr_hourly_counts = {h: 0 for h in range(24)}
    location_counts: Dict[str, int] = {}

    for event in period_events:
        created_at = _as_aware_utc(event.created_at)
        if created_at:
            hourly_counts[created_at.hour] += 1
            if event.detection_type == "object":
                object_hourly_counts[created_at.hour] += 1
                if event.extra_data and event.extra_data.get("detection_source") == "rfdetr":
                    rfdetr_hourly_counts[created_at.hour] += 1

        location = event.location or event.camera_name or "Unknown"
        location_counts[location] = location_counts.get(location, 0) + 1

    peak_hours = [
        {"hour": hour, "count": hourly_counts[hour]}
        for hour in range(24)
    ]

    object_peak_hours = [
        {"hour": hour, "count": object_hourly_counts[hour]}
        for hour in range(24)
    ]

    rfdetr_peak_hours = [
        {"hour": hour, "count": rfdetr_hourly_counts[hour]}
        for hour in range(24)
    ]

    top_locations = [
        {"location": location, "count": count}
        for location, count in sorted(
            location_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
    ]

    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": now.isoformat(),
        "metrics": {
            "total_detections": total_detections,
            "all_time_detections": all_time_detections,
            "total_face_detections": len(face_events),
            "total_object_detections": len(object_events),
            "total_rfdetr_detections": len(rfdetr_events),
            "unique_object_classes": unique_object_classes,
            "unique_persons": len(unique_person_keys),
            "identification_accuracy": round(identification_accuracy, 1),
            "false_positive_rate": round(false_positive_rate, 2),
            "system_uptime": 100.0,
            "camera_uptime": round((active_cameras / max(1, total_cameras)) * 100, 1),
            "active_cameras": active_cameras,
            "total_cameras": total_cameras,
            "active_alerts": active_alerts,
        },
        "trends": {
            "detections_over_time": detections_over_time,
            "identifications_over_time": detections_over_time,
            "object_detections_over_time": object_detections_over_time,
            "rfdetr_detections_over_time": rfdetr_detections_over_time,
            "camera_status_over_time": [],
        },
        "top_locations": top_locations,
        "top_object_classes": top_object_classes,
        "top_rfdetr_classes": top_rfdetr_classes,
        "peak_hours": peak_hours,
        "object_peak_hours": object_peak_hours,
        "rfdetr_peak_hours": rfdetr_peak_hours,
        "last_updated": now.isoformat(),
    }


@app.get("/api/v1/analytics/dashboard")
def dashboard_analytics(user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_analytics(period="7d", user=user, db=db)


@app.get("/api/v1/rfdetr/analytics")
def rfdetr_analytics(
    period: str = Query("7d"),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from rfdetr_service import get_rfdetr_service
    svc = get_rfdetr_service()
    service_stats = svc.get_analytics()

    now = datetime.now(timezone.utc)
    days = _analytics_days(period)
    start_date = now - timedelta(days=days)

    cutoff = start_date.replace(tzinfo=timezone.utc) if start_date.tzinfo is None else start_date

    rfdetr_events = (
        db.query(DetectionEventDB)
        .filter(
            DetectionEventDB.detection_type == "object",
            DetectionEventDB.created_at >= cutoff,
        )
        .all()
    )
    rfdetr_events = [
        e for e in rfdetr_events
        if (e.extra_data or {}).get("detection_source") == "rfdetr"
    ]

    total_rfdetr = len(rfdetr_events)
    avg_confidence = 0.0
    if total_rfdetr > 0:
        avg_confidence = round(
            sum(e.confidence_score or 0.0 for e in rfdetr_events) / total_rfdetr, 4
        )

    class_counts: Dict[str, int] = {}
    class_confidences: Dict[str, List[float]] = {}
    for event in rfdetr_events:
        label = event.person_name or "unknown"
        class_counts[label] = class_counts.get(label, 0) + 1
        conf = event.confidence_score or 0.0
        class_confidences.setdefault(label, []).append(conf)

    top_classes = [
        {
            "label": label,
            "count": count,
            "avg_confidence": round(sum(class_confidences[label]) / len(class_confidences[label]), 4),
            "min_confidence": round(min(class_confidences[label]), 4),
            "max_confidence": round(max(class_confidences[label]), 4),
        }
        for label, count in sorted(class_counts.items(), key=lambda item: item[1], reverse=True)[:10]
    ]

    camera_counts: Dict[str, int] = {}
    for event in rfdetr_events:
        cam = event.camera_name or "Unknown Camera"
        camera_counts[cam] = camera_counts.get(cam, 0) + 1
    top_cameras = [
        {"camera": cam, "count": count}
        for cam, count in sorted(camera_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    ]

    hourly = {h: 0 for h in range(24)}
    for event in rfdetr_events:
        created_at = _as_aware_utc(event.created_at)
        if created_at:
            hourly[created_at.hour] += 1

    peak_hours = [
        {"hour": hour, "count": hourly[hour]}
        for hour in range(24)
    ]

    return {
        "period": period,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": now.isoformat(),
        "service_stats": service_stats,
        "database_stats": {
            "total_rfdetr_detections": total_rfdetr,
            "avg_confidence": avg_confidence,
        },
        "top_classes": top_classes,
        "top_cameras": top_cameras,
        "peak_hours": peak_hours,
        "last_updated": now.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Face recognition endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/face/health")
def face_health():
    from face_service import get_face_service
    return get_face_service().get_health()


@app.get("/api/v1/face/config")
def face_config(user: UserDB = Depends(get_current_user)):
    from face_service import get_face_service
    svc = get_face_service()
    return {
        "detection_threshold": 0.5,
        "recognition_threshold": 0.6,
        "max_faces_per_frame": 20,
        "model_type": "yunet_sface" if svc.yunet_loaded else "mediapipe_blazeface",
        "anti_spoofing_enabled": True,
        "liveness_detection": True,
        "models_loaded": svc.models_loaded,
        "enrolled_persons": len(svc.enrolled_faces),
        "detection_backend": "YuNet" if svc.yunet_loaded else "MediaPipe BlazeFace",
        "recognition_backend": "SFace" if svc.sface_loaded else ("ArcFace" if svc.arcface_loaded else "Fallback"),
    }


@app.get("/api/v1/face/detections")
def face_detections(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_detections(page=page, size=size, user=user, db=db)


@app.get("/api/v1/face/detections/{detection_id}")
def face_detection_detail(
    detection_id: str,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(DetectionEventDB).filter(DetectionEventDB.uuid == detection_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Detection not found")
    return {
        "id": event.uuid,
        "camera_id": str(event.camera_id) if event.camera_id else None,
        "camera_name": event.camera_name or "Unknown",
        "confidence": event.confidence_score or 0,
        "quality_score": 0.85,
        "person_id": event.person_id,
        "person_name": event.person_name,
        "location": event.location,
        "bbox": event.bounding_box or {"x": 100, "y": 100, "width": 150, "height": 200},
        "is_spoofing_detected": False,
        "alert_level": event.alert_level or "low",
        "timestamp": event.created_at.isoformat() if event.created_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "status": event.status,
    }


@app.post("/api/v1/face/detect")
async def face_detect(
    image: UploadFile = File(...),
    user: UserDB = Depends(get_current_user),
):
    from face_service import get_face_service
    svc = get_face_service()
    if not svc.models_loaded:
        raise HTTPException(status_code=503, detail="Face recognition models not loaded")
    image_bytes = await image.read()
    return svc.detect_faces(image_bytes)


@app.post("/api/v1/face/enroll")
async def face_enroll(
    person_name: str = Form(...),
    images: List[UploadFile] = File(...),
    person_id: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    employee_id: Optional[str] = Form(None),
    user: UserDB = Depends(require_roles("admin", "security_officer")),
):
    from face_service import get_face_service
    svc = get_face_service()
    if not svc.models_loaded:
        raise HTTPException(status_code=503, detail="Face recognition models not loaded")
    image_bytes_list = [await img.read() for img in images]
    result = svc.enroll_face(
        person_name=person_name,
        image_bytes_list=image_bytes_list,
        person_id=person_id,
        department=department,
        employee_id=employee_id,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Notify all clients
    notification_bus.publish("person_enrolled", {
        "person_id": result.get("person_id", person_id),
        "person_name": person_name,
        "department": department,
        "enrolled_by": user.name,
    })

    return result


@app.post("/api/v1/face/bulk-enroll")
async def face_bulk_enroll(
    persons: str = Form(...),
    images: List[UploadFile] = File(...),
    user: UserDB = Depends(require_roles("admin", "security_officer")),
):
    import json as json_mod
    from face_service import get_face_service
    svc = get_face_service()
    if not svc.models_loaded:
        raise HTTPException(status_code=503, detail="Face recognition models not loaded")
    try:
        persons_data = json_mod.loads(persons)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid persons JSON")
    all_image_bytes = [await img.read() for img in images]
    results = []
    img_idx = 0
    for person in persons_data:
        count = person.get("image_count", 1)
        person_images = all_image_bytes[img_idx:img_idx + count]
        img_idx += count
        result = svc.enroll_face(
            person_name=person["person_name"],
            image_bytes_list=person_images,
            person_id=person.get("person_id"),
            department=person.get("department"),
            employee_id=person.get("employee_id"),
        )
        results.append(result)

    notification_bus.publish("person_enrolled", {
        "person_name": f"{len(results)} persons",
        "bulk": True,
        "enrolled_by": user.name,
    })

    return {"results": results, "total": len(results)}


@app.post("/api/v1/face/identify")
async def face_identify(
    image: UploadFile = File(...),
    threshold: float = Form(0.6),
    user: UserDB = Depends(get_current_user),
):
    from face_service import get_face_service
    svc = get_face_service()
    if not svc.models_loaded:
        raise HTTPException(status_code=503, detail="Face recognition models not loaded")
    image_bytes = await image.read()
    return svc.identify_face(image_bytes, threshold)


@app.post("/api/v1/face/verify")
async def face_verify(
    image: UploadFile = File(...),
    person_id: str = Form(...),
    threshold: float = Form(0.6),
    user: UserDB = Depends(get_current_user),
):
    from face_service import get_face_service
    svc = get_face_service()
    if not svc.models_loaded:
        raise HTTPException(status_code=503, detail="Face recognition models not loaded")
    image_bytes = await image.read()
    return svc.verify_face(image_bytes, person_id, threshold)


@app.post("/api/v1/face/search-similar")
async def face_search_similar(
    image: UploadFile = File(...),
    threshold: float = Form(0.5),
    limit: int = Form(10),
    user: UserDB = Depends(get_current_user),
):
    from face_service import get_face_service
    svc = get_face_service()
    if not svc.models_loaded:
        raise HTTPException(status_code=503, detail="Face recognition models not loaded")
    image_bytes = await image.read()
    return svc.search_similar(image_bytes, threshold, limit)


@app.get("/api/v1/face/enrolled")
def face_enrolled_list(user: UserDB = Depends(get_current_user)):
    from face_service import get_face_service
    svc = get_face_service()
    persons = svc.get_enrolled_persons()
    return {
        "persons": [{
            "person_id": p["person_id"],
            "person_name": p["person_name"],
            "department": p.get("department"),
            "employee_id": p.get("employee_id"),
            "enrollment_images": p.get("enrollment_images", []),
            "quality_scores": p.get("quality_scores", []),
            "is_active": p.get("is_active", True),
            "created_at": p.get("created_at"),
        } for p in persons],
        "total": len(persons),
    }


@app.get("/api/v1/face/persons")
def face_persons(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from face_service import get_face_service
    svc = get_face_service()
    all_persons = svc.get_enrolled_persons()
    total = len(all_persons)
    pages = max(1, (total + size - 1) // size)
    start = (page - 1) * size
    page_items = all_persons[start:start + size]

    items = []
    for p in page_items:
        items.append({
            "id": p["person_id"],
            "person_id": p["person_id"],
            "person_name": p["person_name"],
            "department": p.get("department"),
            "employee_id": p.get("employee_id"),
            "enrollment_images": p.get("enrollment_images", []),
            "face_embedding": [],
            "created_at": p.get("created_at"),
            "updated_at": p.get("created_at"),
            "is_active": p.get("is_active", True),
            "quality_scores": p.get("quality_scores", []),
            "enrollment_source": p.get("enrollment_source", "api"),
            "metadata": {},
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
        "has_next": page < pages,
        "has_prev": page > 1,
    }


@app.get("/api/v1/face/persons/{person_id}")
def face_person_detail(
    person_id: str,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from face_service import get_face_service
    svc = get_face_service()
    person = svc.get_person(person_id)
    if person:
        return {
            "id": person["person_id"],
            "person_id": person["person_id"],
            "person_name": person["person_name"],
            "department": person.get("department"),
            "employee_id": person.get("employee_id"),
            "enrollment_images": person.get("enrollment_images", []),
            "face_embedding_count": len(person.get("embeddings", [])),
            "created_at": person.get("created_at"),
            "updated_at": person.get("updated_at"),
            "is_active": person.get("is_active", True),
            "quality_scores": person.get("quality_scores", []),
            "enrollment_source": person.get("enrollment_source", "api"),
            "metadata": {},
        }
    u = db.query(UserDB).filter(UserDB.uuid == person_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Person not found")
    return {
        "id": u.uuid,
        "person_id": u.employee_id or u.uuid,
        "person_name": u.name,
        "department": u.department,
        "employee_id": u.employee_id,
        "enrollment_images": [],
        "face_embedding": [],
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "updated_at": u.updated_at.isoformat() if u.updated_at else None,
        "is_active": u.is_active,
        "quality_scores": [],
        "enrollment_source": "manual",
        "metadata": {},
    }


@app.patch("/api/v1/face/persons/{person_id}")
def face_person_update(
    person_id: str,
    data: dict,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    u = db.query(UserDB).filter(UserDB.uuid == person_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Person not found")
    if "person_name" in data:
        u.name = data["person_name"]
    if "department" in data:
        u.department = data["department"]
    db.commit()
    db.refresh(u)
    return {"message": "Person updated"}


@app.delete("/api/v1/face/persons/{person_id}")
def face_person_delete(
    person_id: str,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from face_service import get_face_service
    svc = get_face_service()

    # Try to get name before deleting for the notification
    person = svc.get_person(person_id)
    person_name = person.get("person_name", "Unknown") if person else "Unknown"

    if svc.delete_person(person_id):
        notification_bus.publish("person_deleted", {
            "person_id": person_id,
            "person_name": person_name,
            "deleted_by": user.name,
        })
        return {"message": "Person deleted from face recognition system"}
    raise HTTPException(status_code=404, detail="Person not found in face recognition system")


@app.get("/api/v1/face/persons/{person_id}/analytics")
def face_person_analytics(person_id: str, user: UserDB = Depends(get_current_user)):
    return {"detections": [], "total": 0, "period": "7d"}


@app.patch("/api/v1/face/config")
def face_config_update(data: dict, user: UserDB = Depends(get_current_user)):
    return {"message": "Configuration updated"}


# ─────────────────────────────────────────────────────────────────────────────
# Video endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/video/upload-analyze")
async def video_upload_analyze(
    video: UploadFile = File(...),
    frame_interval: int = Form(5),
    user: UserDB = Depends(get_current_user),
):
    from face_service import get_face_service
    from video_processor import get_video_processor, UPLOADS_DIR

    if frame_interval < 1 or frame_interval > 100:
        raise HTTPException(400, "frame_interval must be between 1 and 100")

    MAX_SIZE = 500 * 1024 * 1024
    allowed = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".3gp"}
    ext = Path(video.filename).suffix.lower() if video.filename else ""
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported format '{ext}'. Supported: {', '.join(sorted(allowed))}")

    file_id = str(uuid.uuid4())
    file_path = UPLOADS_DIR / f"{file_id}{ext}"
    try:
        size = 0
        with open(file_path, "wb") as f:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_SIZE:
                    f.close()
                    file_path.unlink(missing_ok=True)
                    raise HTTPException(400, f"File too large. Maximum size is {MAX_SIZE // (1024 * 1024)} MB")
                f.write(chunk)

        svc = get_face_service()
        vp = get_video_processor()
        result = vp.process_video_file(str(file_path), svc, frame_interval)

        if "error" in result:
            raise HTTPException(400, result["error"])

        return result
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass


_pending_stream_files: Dict[str, dict] = {}


@app.post("/api/v1/video/stream-upload")
async def video_stream_upload(
    video: UploadFile = File(...),
    frame_interval: int = Form(3),
    user: UserDB = Depends(get_current_user),
):
    from video_processor import UPLOADS_DIR

    if frame_interval < 1 or frame_interval > 100:
        raise HTTPException(400, "frame_interval must be between 1 and 100")

    MAX_SIZE = 500 * 1024 * 1024
    allowed = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"}
    ext = Path(video.filename).suffix.lower() if video.filename else ""
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported format '{ext}'.")

    file_id = str(uuid.uuid4())
    file_path = UPLOADS_DIR / f"{file_id}{ext}"
    size = 0
    with open(file_path, "wb") as f:
        while chunk := await video.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_SIZE:
                f.close()
                file_path.unlink(missing_ok=True)
                raise HTTPException(400, f"File too large. Maximum {MAX_SIZE // (1024 * 1024)} MB")
            f.write(chunk)

    _pending_stream_files[file_id] = {
        "path": file_path,
        "frame_interval": frame_interval,
        "user_id": user.uuid,
    }
    return {"stream_id": file_id}


@app.get("/api/v1/video/stream/{stream_id}/feed")
async def video_stream_feed(stream_id: str, user: UserDB = Depends(get_current_user)):
    from face_service import get_face_service
    from video_processor import get_video_processor

    info = _pending_stream_files.get(stream_id)
    if not info:
        raise HTTPException(404, "Stream not found. Upload a video first.")

    file_path = info["path"]
    frame_interval = info["frame_interval"]

    svc = get_face_service()
    vp = get_video_processor()

    def generate_and_cleanup():
        try:
            yield from vp.generate_annotated_frames(str(file_path), svc, frame_interval)
        finally:
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass
            _pending_stream_files.pop(stream_id, None)

    return StreamingResponse(
        generate_and_cleanup(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.post("/api/v1/video/rtsp/start")
async def rtsp_stream_start(
    data: dict = Body(...),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from face_service import get_face_service
    from video_processor import get_video_processor
    from rfdetr_service import get_rfdetr_service

    rtsp_url = data.get("rtsp_url")
    stream_id = data.get("stream_id", str(uuid.uuid4()))
    frame_interval = data.get("frame_interval", 15)
    detection_mode = data.get("detection_mode", "both")

    if not rtsp_url:
        raise HTTPException(400, "rtsp_url is required")
    if not isinstance(frame_interval, int) or frame_interval < 1 or frame_interval > 100:
        raise HTTPException(400, "frame_interval must be between 1 and 100")
    if detection_mode not in ("face", "object", "both"):
        raise HTTPException(400, "detection_mode must be 'face', 'object', or 'both'")

    camera_db_id: Optional[int] = None
    camera_location: Optional[str] = None
    cam = db.query(CameraDB).filter(CameraDB.stream_url == rtsp_url).first()
    if cam:
        camera_db_id = cam.id
        camera_location = cam.location

    reidentification_enabled = bool(
        (cam.configuration or {}).get("person_reidentification_enabled", True)
    ) if cam else True

    svc = get_face_service()
    vp = get_video_processor()
    rfdetr = get_rfdetr_service()

    result = vp.start_rtsp_stream(
        stream_id=stream_id,
        rtsp_url=rtsp_url,
        face_service=svc,
        frame_interval=frame_interval,
        db_session_factory=SessionLocal,
        alert_creator=create_face_alert,
        detection_creator=create_detection_event,
        camera_db_id=camera_db_id,
        camera_name=cam.name if cam else stream_id,
        camera_location=camera_location,
        reidentification_enabled=reidentification_enabled,
        rfdetr_service=rfdetr,
        detection_mode=detection_mode,
        rfdetr_alert_creator=create_rfdetr_alert,
        notify_callback=notification_bus.publish,
    )

    if "error" in result:
        raise HTTPException(400, result["error"])

    # Notify clients that a stream started
    notification_bus.publish("stream_started", {
        "stream_id": stream_id,
        "rtsp_url": rtsp_url,
        "camera_name": cam.name if cam else stream_id,
        "location": camera_location,
        "started_by": user.name,
    })

    return result


@app.get("/api/v1/video/rtsp/{stream_id}/feed")
async def rtsp_stream_feed(
    stream_id: str,
    token: str = Query(None),
    user: UserDB = Depends(optional_get_current_user),
):
    # Allow token-based auth as fallback for browser <img> tags
    if not user and token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email = payload.get("sub")
            if email:
                db = SessionLocal()
                try:
                    user = db.query(UserDB).filter(UserDB.email == email).first()
                finally:
                    db.close()
        except Exception:
            pass
    if not user:
        raise HTTPException(401, "Not authenticated")

    from video_processor import get_video_processor
    vp = get_video_processor()
    generator = vp.get_rtsp_frame_generator(stream_id)
    if not generator:
        raise HTTPException(404, "Stream not found or not active")

    return StreamingResponse(
        generator,
        media_type="multipart/x-mixed-replace; boundary=frame",
        # These headers tell the browser this is a live stream, preventing it
        # from treating a connection close as a page-level error.
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/v1/video/rtsp/{stream_id}/snapshot")
def rtsp_stream_snapshot(stream_id: str, user: UserDB = Depends(get_current_user)):
    """Return the latest annotated JPEG from an active RTSP stream as base64."""
    import base64
    import queue as queue_module
    from video_processor import get_video_processor

    vp = get_video_processor()

    # Read under lock so we don't race with the capture thread
    with vp._lock:
        stream = vp.active_streams.get(stream_id)
        if not stream:
            raise HTTPException(404, "Stream not found or not active")
        # Capture local references under the lock
        jpeg_bytes = stream.get("last_jpeg")
        frames_read = stream["frames_read"]
        detections_count = stream["detections_count"]
        faces = list(stream.get("last_faces", []))
        fq: queue_module.Queue = stream["frame_queue"]
        stop_event: threading.Event = stream["stop_event"]

    # If no JPEG yet and stream is still alive, wait briefly for first frame
    if not jpeg_bytes and not stop_event.is_set():
        try:
            jpeg_bytes = fq.get(timeout=1.0)
            # Persist it so the next snapshot is instant
            with vp._lock:
                if stream_id in vp.active_streams:
                    vp.active_streams[stream_id]["last_jpeg"] = jpeg_bytes
        except queue_module.Empty:
            raise HTTPException(503, "Camera stream is initializing. Please retry shortly.")

    if not jpeg_bytes:
        # Stream stopped between our check and now
        raise HTTPException(404, "Stream not found or not active")

    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")

    return {
        "image": f"data:image/jpeg;base64,{b64}",
        "stream_id": stream_id,
        "frames_read": frames_read,
        "detections_count": detections_count,
        "active_faces": len(faces),
        "faces": faces,
        "objects": list(stream.get("last_objects", [])),
    }


@app.post("/api/v1/video/rtsp/{stream_id}/stop")
async def rtsp_stream_stop(
    stream_id: str,
    user: UserDB = Depends(require_roles("admin", "security_officer")),
):
    """
    Stop an RTSP stream.  The blocking thread.join() is offloaded to a thread-pool
    executor so it never stalls the uvicorn event loop.
    Returns 200 whether the stream existed or not — the frontend treats both as success.
    """
    import asyncio
    from video_processor import get_video_processor

    vp = get_video_processor()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, vp.stop_rtsp_stream, stream_id)

    if "error" in result:
        return {"stream_id": stream_id, "status": "already_stopped", "message": result["error"]}

    # Notify all clients
    notification_bus.publish("stream_stopped", {
        "stream_id": stream_id,
        "stopped_by": user.name,
        "frames_read": result.get("frames_read", 0),
        "detections_count": result.get("detections_count", 0),
    })

    return result


@app.post("/api/v1/video/rtsp/{stream_id}/mode")
async def rtsp_stream_set_mode(
    stream_id: str,
    data: dict = Body(...),
    user: UserDB = Depends(get_current_user),
):
    from video_processor import get_video_processor

    mode = data.get("mode", "both")
    vp = get_video_processor()
    result = vp.set_stream_mode(stream_id, mode)

    if "error" in result:
        raise HTTPException(400, result["error"])

    return result


@app.get("/api/v1/video/rtsp/active")
async def rtsp_active_streams(user: UserDB = Depends(get_current_user)):
    from video_processor import get_video_processor
    vp = get_video_processor()
    return {"streams": vp.list_active_streams()}


# ─────────────────────────────────────────────────────────────────────────────
# Audit log endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/system/audit")
def audit_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total = db.query(AuditLogDB).count()
    logs = db.query(AuditLogDB).order_by(AuditLogDB.timestamp.desc()).offset((page - 1) * size).limit(size).all()
    pages = max(1, (total + size - 1) // size)

    items = []
    for log in logs:
        items.append({
            "id": str(log.id),
            "user_id": str(log.user_id) if log.user_id else None,
            "user_name": log.user_name or "System",
            "action": log.action,
            "resource": log.resource,
            "resource_id": log.resource_id,
            "details": log.details or {},
            "ip_address": log.ip_address or "10.0.0.1",
            "user_agent": log.user_agent or "",
            "status": log.status,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
        "has_next": page < pages,
        "has_prev": page > 1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DB seeding
# ─────────────────────────────────────────────────────────────────────────────

def _migrate_detection_events_extra_data(db: Session) -> None:
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.get_bind())
        columns = [c['name'] for c in inspector.get_columns('detection_events')]
        if "metadata" not in columns:
            db.execute(text("ALTER TABLE detection_events ADD COLUMN metadata JSON DEFAULT '{}'"))
            db.commit()
            print("[Migration] Added detection_events.metadata column")
    except Exception as e:
        db.rollback()
        print(f"[Migration] detection_events.metadata migration error: {e}")


def seed_database():
    db = SessionLocal()
    try:
        _migrate_detection_events_extra_data(db)

        if db.query(UserDB).count() > 0:
            return

        demo_users = [
            {
                "email": "admin@security.iitb.ac.in",
                "name": "Prof. Rajesh Gupta",
                "password": "admin123",
                "role": "admin",
                "department": "Computer Science & Engineering",
                "employee_id": "IITB001",
                "is_superuser": True,
            },
            {
                "email": "security@security.iitb.ac.in",
                "name": "Sunil Kumar Sharma",
                "password": "security123",
                "role": "security_officer",
                "department": "Campus Security",
                "employee_id": "IITB002",
            },
            {
                "email": "operator@security.iitb.ac.in",
                "name": "Priya Deshmukh",
                "password": "operator123",
                "role": "operator",
                "department": "Security Operations",
                "employee_id": "IITB003",
            },
        ]

        for u in demo_users:
            user = UserDB(
                uuid=str(uuid.uuid4()),
                email=u["email"],
                name=u["name"],
                hashed_password=pwd_context.hash(u["password"]),
                role=u["role"],
                department=u["department"],
                employee_id=u["employee_id"],
                is_superuser=u.get("is_superuser", False),
            )
            db.add(user)
        db.flush()

        cameras_data = [
            {"name": "Main Gate - Entry",             "location": "Main Gate",        "building": "Main Gate",     "camera_type": "fixed",  "status": "online"},
            {"name": "Main Gate - Exit",              "location": "Main Gate",        "building": "Main Gate",     "camera_type": "ptz",    "status": "online"},
            {"name": "Central Library - Ground Floor","location": "Central Library",  "building": "Central Library","camera_type": "fixed",  "status": "online"},
            {"name": "Central Library - First Floor", "location": "Central Library",  "building": "Central Library","camera_type": "fixed",  "floor": "1", "status": "online"},
            {"name": "KReSIT Building Lobby",         "location": "KReSIT Building",  "building": "KReSIT",        "camera_type": "ptz",    "status": "online"},
            {"name": "Student Activity Centre",       "location": "SAC",              "building": "SAC",           "camera_type": "fixed",  "status": "online"},
            {"name": "Hostel 10 - Entry Gate",        "location": "Hostel 10",        "building": "H10",           "camera_type": "fixed",  "status": "online"},
            {"name": "Hostel 4 - Entry Gate",         "location": "Hostel 4",         "building": "H4",            "camera_type": "fixed",  "status": "offline"},
            {"name": "Admin Building - Main Entrance","location": "Main Building",    "building": "Main Building", "camera_type": "fixed",  "status": "online"},
            {"name": "Gymkhana - Sports Complex",     "location": "Gymkhana Grounds", "building": "Gymkhana",      "camera_type": "ptz",    "status": "online"},
            {"name": "Drone Unit 1 - Powai Lake Side","location": "Campus Perimeter", "building": "Outdoor",       "camera_type": "drone",  "status": "online"},
            {"name": "Drone Unit 2 - Hillside Area",  "location": "Campus Perimeter", "building": "Outdoor",       "camera_type": "drone",  "status": "maintenance"},
        ]

        camera_objs = []
        for c in cameras_data:
            cam = CameraDB(
                uuid=str(uuid.uuid4()),
                name=c["name"],
                location=c["location"],
                building=c.get("building"),
                floor=c.get("floor"),
                camera_type=c["camera_type"],
                status=c["status"],
                last_heartbeat=(
                    datetime.now(timezone.utc) - timedelta(minutes=random.randint(0, 30))
                    if c["status"] == "online" else None
                ),
            )
            db.add(cam)
            camera_objs.append(cam)
        db.flush()

        alert_types = ["unauthorized_access", "unknown_person", "camera_offline", "suspicious_behavior"]
        severities  = ["low", "medium", "high", "critical"]
        locations   = ["Main Gate", "Central Library", "KReSIT Building", "SAC", "Hostel 10", "Main Building"]
        statuses    = ["active", "active", "active", "acknowledged", "resolved"]

        for i in range(25):
            hours_ago = random.randint(0, 168)
            alert = AlertDB(
                uuid=str(uuid.uuid4()),
                alert_type=random.choice(alert_types),
                severity=random.choice(severities),
                title=f"Security Alert #{i + 1}",
                description=f"Automated security alert detected at {random.choice(locations)}",
                location=random.choice(locations),
                camera_id=random.choice(camera_objs).id if camera_objs else None,
                camera_name=random.choice(camera_objs).name if camera_objs else None,
                status=random.choice(statuses),
                triggered_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
            )
            db.add(alert)

        persons = ["Unknown", "Amit Patel", "Sneha Iyer", "Prof. Mehta", "Visitor"]
        for i in range(100):
            mins_ago = random.randint(0, 10080)
            cam = random.choice(camera_objs) if camera_objs else None
            detection = DetectionEventDB(
                uuid=str(uuid.uuid4()),
                camera_id=cam.id if cam else None,
                camera_name=cam.name if cam else "Unknown",
                confidence_score=round(random.uniform(0.6, 0.99), 3),
                person_name=random.choice(persons),
                location=cam.location if cam else "Unknown",
                status=random.choice(["confirmed", "confirmed", "pending", "false_positive"]),
                alert_triggered=random.random() < 0.15,
                processing_time_ms=random.randint(10, 200),
                alert_level=random.choice(["low", "low", "medium", "high"]),
                bounding_box={
                    "x": random.randint(50, 500),
                    "y": random.randint(50, 400),
                    "width": random.randint(80, 200),
                    "height": random.randint(100, 300),
                },
                created_at=datetime.now(timezone.utc) - timedelta(minutes=mins_ago),
            )
            db.add(detection)

        audit_actions = ["login", "logout", "view_camera", "acknowledge_alert", "resolve_alert", "update_config"]
        for i in range(50):
            mins_ago = random.randint(0, 10080)
            log = AuditLogDB(
                user_id=1,
                user_name="Prof. Rajesh Gupta",
                action=random.choice(audit_actions),
                resource=random.choice(["auth", "cameras", "alerts", "system", "users"]),
                resource_id=str(random.randint(1, 100)),
                details={"action_detail": "Automated audit entry"},
                ip_address=f"10.0.{random.randint(0, 5)}.{random.randint(1, 254)}",
                status="success",
                timestamp=datetime.now(timezone.utc) - timedelta(minutes=mins_ago),
            )
            db.add(log)

        db.commit()
        print("Database seeded with demo data successfully!")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
    finally:
        db.close()


@app.on_event("startup")
def startup():
    seed_database()




# ─────────────────────────────────────────────────────────────────────────────
# Mobile / smartphone live-camera streaming router
# ─────────────────────────────────────────────────────────────────────────────
from mobile_stream import router as mobile_router  # noqa: E402
app.include_router(mobile_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, workers=4)
