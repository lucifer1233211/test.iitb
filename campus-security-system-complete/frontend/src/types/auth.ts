export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  department?: string
  is_active: boolean
  created_at: string
  updated_at: string
  last_login?: string
  permissions: Permission[]
  profile_image?: string
  phone?: string
  employee_id?: string
}

export interface UserRole {
  id: string
  name: string
  description: string
  permissions: Permission[]
}

export interface Permission {
  id: string
  name: string
  description: string
  resource: string
  action: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface RefreshTokenRequest {
  refresh_token: string
}

export interface RefreshTokenResponse {
  access_token: string
  refresh_token?: string
  token_type: string
  expires_in: number
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
  confirm_password: string
}

export interface ResetPasswordRequest {
  email: string
}

export interface ResetPasswordConfirmRequest {
  token: string
  new_password: string
  confirm_password: string
}

export interface UpdateProfileRequest {
  full_name?: string
  phone?: string
  department?: string
  profile_image?: string
}

// Permission constants
export const PERMISSIONS = {
  // User management
  USER_CREATE: 'user:create',
  USER_READ: 'user:read',
  USER_UPDATE: 'user:update',
  USER_DELETE: 'user:delete',
  
  // Face recognition
  FACE_ENROLL: 'face:enroll',
  FACE_IDENTIFY: 'face:identify',
  FACE_DELETE: 'face:delete',
  FACE_VIEW: 'face:view',
  
  // Camera management
  CAMERA_CREATE: 'camera:create',
  CAMERA_READ: 'camera:read',
  CAMERA_UPDATE: 'camera:update',
  CAMERA_DELETE: 'camera:delete',
  CAMERA_CONTROL: 'camera:control',
  
  // Alert management
  ALERT_CREATE: 'alert:create',
  ALERT_READ: 'alert:read',
  ALERT_UPDATE: 'alert:update',
  ALERT_DELETE: 'alert:delete',
  ALERT_ACKNOWLEDGE: 'alert:acknowledge',
  
  // System administration
  SYSTEM_CONFIG: 'system:config',
  SYSTEM_LOGS: 'system:logs',
  SYSTEM_BACKUP: 'system:backup',
  SYSTEM_RESTORE: 'system:restore',
  
  // Reports and analytics
  REPORT_VIEW: 'report:view',
  REPORT_EXPORT: 'report:export',
  ANALYTICS_VIEW: 'analytics:view',
  
  // Audit logs
  AUDIT_VIEW: 'audit:view',
  AUDIT_EXPORT: 'audit:export',
} as const

// Role constants
export const ROLES = {
  SUPER_ADMIN: 'super_admin',
  ADMIN: 'admin',
  SECURITY_OFFICER: 'security_officer',
  OPERATOR: 'operator',
  VIEWER: 'viewer',
} as const

export type PermissionKey = keyof typeof PERMISSIONS
export type RoleKey = keyof typeof ROLES