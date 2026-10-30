// Common API response types
export interface ApiResponse<T = any> {
  success: boolean
  data: T
  message?: string
  errors?: Record<string, string[]>
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  size: number
  pages: number
  has_next: boolean
  has_prev: boolean
}

export interface ApiError {
  detail: string
  status_code: number
  error_code?: string
  field_errors?: Record<string, string[]>
}

// Face recognition types
export interface FaceDetection {
  id: string
  camera_id: string
  camera_name: string
  timestamp: string
  bbox: BoundingBox
  confidence: number
  face_embedding?: number[]
  image_path?: string
  person_id?: string
  person_name?: string
  alert_level: AlertLevel
  is_spoofing_detected: boolean
  quality_score: number
  created_at: string
}

export interface BoundingBox {
  x: number
  y: number
  width: number
  height: number
}

export interface FaceEnrollment {
  id: string
  person_id: string
  person_name: string
  face_embedding: number[]
  enrollment_images: string[]
  created_at: string
  updated_at: string
  is_active: boolean
  quality_scores: number[]
  enrollment_source: 'manual' | 'automatic'
}

export interface PersonIdentification {
  person_id: string
  person_name: string
  confidence: number
  similarity_score: number
  last_seen: string
  detection_count: number
  locations: string[]
}

// Camera types
export interface Camera {
  id: string
  name: string
  location: string
  camera_type: CameraType
  stream_url: string
  status: CameraStatus
  is_active: boolean
  created_at: string
  updated_at: string
  last_heartbeat?: string
  settings: CameraSettings
  capabilities: CameraCapabilities
  coordinates?: {
    latitude: number
    longitude: number
  }
}

export interface CameraSettings {
  resolution: string
  fps: number
  quality: number
  night_vision: boolean
  motion_detection: boolean
  face_detection_enabled: boolean
  recording_enabled: boolean
  alert_zones?: AlertZone[]
}

export interface CameraCapabilities {
  pan_tilt: boolean
  zoom: boolean
  night_vision: boolean
  audio: boolean
  two_way_audio: boolean
  motion_detection: boolean
  face_detection: boolean
}

export interface AlertZone {
  id: string
  name: string
  coordinates: Array<{ x: number; y: number }>
  alert_level: AlertLevel
  is_active: boolean
}

export type CameraType = 'fixed' | 'ptz' | 'drone' | 'mobile'
export type CameraStatus = 'online' | 'offline' | 'error' | 'maintenance'

// Alert types
export interface Alert {
  id: string
  type: AlertType
  severity: AlertLevel
  title: string
  message: string
  camera_id?: string
  camera_name?: string
  person_id?: string
  person_name?: string
  location?: string
  timestamp: string
  acknowledged_at?: string
  acknowledged_by?: string
  resolved_at?: string
  resolved_by?: string
  status: AlertStatus
  metadata?: Record<string, any>
  image_path?: string
  video_path?: string
  created_at: string
  updated_at: string
}

export type AlertType = 
  | 'face_detected'
  | 'person_identified'
  | 'unauthorized_access'
  | 'camera_offline'
  | 'system_error'
  | 'suspicious_behavior'
  | 'restricted_area_access'
  | 'unknown_person'

export type AlertLevel = 'low' | 'medium' | 'high' | 'critical'
export type AlertStatus = 'active' | 'acknowledged' | 'resolved' | 'dismissed'

// System monitoring types
export interface SystemStatus {
  status: 'healthy' | 'warning' | 'error'
  uptime: number
  cpu_usage: number
  memory_usage: number
  disk_usage: number
  active_cameras: number
  total_cameras: number
  active_detections: number
  alerts_count: {
    active: number
    acknowledged: number
    resolved: number
  }
  last_updated: string
}

export interface SystemMetrics {
  timestamp: string
  cpu_usage: number
  memory_usage: number
  disk_usage: number
  network_io: {
    bytes_sent: number
    bytes_recv: number
  }
  face_detections_per_minute: number
  identifications_per_minute: number
  active_streams: number
  processing_latency: number
}

// Analytics types
export interface AnalyticsData {
  period: 'hour' | 'day' | 'week' | 'month'
  start_date: string
  end_date: string
  metrics: {
    total_detections: number
    unique_persons: number
    identification_accuracy: number
    false_positive_rate: number
    system_uptime: number
    camera_uptime: number
  }
  trends: {
    detections_over_time: Array<{ timestamp: string; count: number }>
    identifications_over_time: Array<{ timestamp: string; count: number }>
    camera_status_over_time: Array<{ timestamp: string; online: number; offline: number }>
  }
  top_locations: Array<{ location: string; detection_count: number }>
  peak_hours: Array<{ hour: number; detection_count: number }>
}

// Audit log types
export interface AuditLog {
  id: string
  user_id: string
  user_name: string
  action: string
  resource: string
  resource_id?: string
  details: Record<string, any>
  ip_address: string
  user_agent: string
  timestamp: string
  status: 'success' | 'failure'
}

// WebSocket message types
export interface WebSocketMessage {
  type: string
  data: any
  timestamp: string
}

export interface FaceDetectionMessage extends WebSocketMessage {
  type: 'face_detected'
  data: FaceDetection
}

export interface PersonIdentificationMessage extends WebSocketMessage {
  type: 'person_identified'
  data: PersonIdentification & { camera_name: string; timestamp: string }
}

export interface SecurityAlertMessage extends WebSocketMessage {
  type: 'security_alert'
  data: Alert
}

export interface CameraStatusMessage extends WebSocketMessage {
  type: 'camera_status'
  data: {
    camera_id: string
    camera_name: string
    status: CameraStatus
    was_offline?: boolean
  }
}

export interface SystemStatusMessage extends WebSocketMessage {
  type: 'system_status'
  data: SystemStatus
}

// Search and filter types
export interface SearchFilters {
  query?: string
  start_date?: string
  end_date?: string
  camera_ids?: string[]
  person_ids?: string[]
  alert_levels?: AlertLevel[]
  alert_types?: AlertType[]
  status?: AlertStatus[]
  location?: string
}

export interface SortOptions {
  field: string
  direction: 'asc' | 'desc'
}

export interface PaginationOptions {
  page: number
  size: number
}

// File upload types
export interface FileUpload {
  file: File
  progress: number
  status: 'pending' | 'uploading' | 'success' | 'error'
  error?: string
}

export interface UploadResponse {
  file_id: string
  file_name: string
  file_size: number
  file_type: string
  file_path: string
  upload_url?: string
}

// Configuration types
export interface SystemConfig {
  face_recognition: {
    detection_threshold: number
    identification_threshold: number
    anti_spoofing_enabled: boolean
    quality_threshold: number
    max_faces_per_frame: number
  }
  alerts: {
    email_notifications: boolean
    sms_notifications: boolean
    webhook_url?: string
    retention_days: number
  }
  cameras: {
    max_concurrent_streams: number
    recording_retention_days: number
    thumbnail_generation: boolean
    motion_detection_sensitivity: number
  }
  system: {
    log_level: 'debug' | 'info' | 'warning' | 'error'
    backup_enabled: boolean
    backup_schedule: string
    maintenance_window: string
  }
}

// Export/Import types
export interface ExportRequest {
  format: 'csv' | 'json' | 'pdf'
  data_type: 'detections' | 'alerts' | 'users' | 'cameras' | 'audit_logs'
  filters?: SearchFilters
  date_range?: {
    start_date: string
    end_date: string
  }
}

export interface ExportResponse {
  export_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  file_url?: string
  created_at: string
  expires_at: string
}