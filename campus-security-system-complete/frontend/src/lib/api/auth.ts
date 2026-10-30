import { apiClient } from './client'
import {
  LoginRequest,
  LoginResponse,
  RefreshTokenRequest,
  RefreshTokenResponse,
  ChangePasswordRequest,
  ResetPasswordRequest,
  ResetPasswordConfirmRequest,
  UpdateProfileRequest,
  User,
} from '@/types/auth'

export const authApi = {
  // Authentication
  async login(data: LoginRequest): Promise<LoginResponse> {
    const response = await apiClient.post<LoginResponse>('/auth/login', data)
    return response.data
  },

  async logout(): Promise<void> {
    await apiClient.post('/auth/logout')
  },

  async refreshToken(refreshToken: string): Promise<RefreshTokenResponse> {
    const response = await apiClient.post<RefreshTokenResponse>('/auth/refresh', {
      refresh_token: refreshToken,
    })
    return response.data
  },

  // User profile
  async getCurrentUser(): Promise<User> {
    const response = await apiClient.get<User>('/auth/me')
    return response.data
  },

  async updateProfile(data: UpdateProfileRequest): Promise<User> {
    const response = await apiClient.patch<User>('/auth/me', data)
    return response.data
  },

  async uploadProfileImage(file: File): Promise<{ profile_image: string }> {
    const formData = new FormData()
    formData.append('file', file)
    
    const response = await apiClient.post<{ profile_image: string }>(
      '/auth/me/profile-image',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    )
    return response.data
  },

  // Password management
  async changePassword(data: ChangePasswordRequest): Promise<void> {
    await apiClient.post('/auth/change-password', data)
  },

  async resetPassword(data: ResetPasswordRequest): Promise<void> {
    await apiClient.post('/auth/reset-password', data)
  },

  async resetPasswordConfirm(data: ResetPasswordConfirmRequest): Promise<void> {
    await apiClient.post('/auth/reset-password/confirm', data)
  },

  // Session management
  async validateToken(): Promise<{ valid: boolean; expires_at: string }> {
    const response = await apiClient.get<{ valid: boolean; expires_at: string }>('/auth/validate')
    return response.data
  },

  async revokeAllSessions(): Promise<void> {
    await apiClient.post('/auth/revoke-all-sessions')
  },

  async getActiveSessions(): Promise<Array<{
    id: string
    ip_address: string
    user_agent: string
    created_at: string
    last_activity: string
    is_current: boolean
  }>> {
    const response = await apiClient.get('/auth/sessions')
    return response.data
  },

  async revokeSession(sessionId: string): Promise<void> {
    await apiClient.delete(`/auth/sessions/${sessionId}`)
  },
}