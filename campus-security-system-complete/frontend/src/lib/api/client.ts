import axios, { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios'
import { ApiResponse, ApiError } from '@/types/api'

// Helper to safely check if we are on the client side (browser)
const isClient = typeof window !== 'undefined'

// Create axios instance
const apiClient: AxiosInstance = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor to add auth token
apiClient.interceptors.request.use(
  (config) => {
    // Only access localStorage on the browser
    const token = isClient ? localStorage.getItem('access_token') : null
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor to handle common errors
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    return response
  },
  async (error) => {
    // 1. 🔥 SILENCE INTENTIONAL CANCELLATIONS GLOBALLY
    // If the request was aborted via AbortController, bypass interceptor error logging completely
    if (axios.isCancel(error) || error?.message === 'canceled' || error?.code === 'ERR_CANCELED') {
      return Promise.reject(error)
    }

    const originalRequest = error.config

    // Handle 401 errors (unauthorized)
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true

      try {
        const refreshToken = isClient ? localStorage.getItem('refresh_token') : null
        if (refreshToken) {
          const response = await axios.post(
            `${process.env.NEXT_PUBLIC_API_URL || '/api/v1'}/auth/refresh`,
            { refresh_token: refreshToken }
          )

          const { access_token, refresh_token: newRefreshToken } = response.data
          
          if (isClient) {
            localStorage.setItem('access_token', access_token)
            if (newRefreshToken) {
              localStorage.setItem('refresh_token', newRefreshToken)
            }
          }

          // Retry original request with new token
          originalRequest.headers.Authorization = `Bearer ${access_token}`
          return apiClient(originalRequest)
        }
      } catch (refreshError) {
        // Refresh failed, clear tokens and redirect to login if on client side
        if (isClient) {
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          window.location.href = '/login'
        }
        return Promise.reject(refreshError)
      }
    }

    // Handle 403 errors (forbidden)
    if (error.response?.status === 403) {
      console.error('Access forbidden:', error.response.data)
    }

    // Handle network errors
    if (!error.response) {
      console.error('Network error:', error.message)
      return Promise.reject({
        detail: 'Network error. Please check your connection.',
        status_code: 0,
      } as ApiError)
    }

    // Transform error response
    const apiError: ApiError = {
      detail: error.response.data?.detail || error.response.data?.message || 'An error occurred',
      status_code: error.response.status,
      error_code: error.response.data?.error_code,
      field_errors: error.response.data?.field_errors,
    }

    return Promise.reject(apiError)
  }
)

// Generic API methods
export const api = {
  get: <T = any>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> =>
    apiClient.get(url, config),

  post: <T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> =>
    apiClient.post(url, data, config),

  put: <T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> =>
    apiClient.put(url, data, config),

  patch: <T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> =>
    apiClient.patch(url, data, config),

  delete: <T = any>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> =>
    apiClient.delete(url, config),
}

// Utility functions for handling API responses
export const handleApiResponse = <T>(response: AxiosResponse<ApiResponse<T>>): T => {
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'API request failed')
}

export const handleApiError = (error: any): ApiError => {
  // Respect cancellation down the handler tree as well
  if (axios.isCancel(error) || error?.message === 'canceled') {
    return {
      detail: 'Request was canceled',
      status_code: 0,
    }
  }

  if (error.response) {
    return {
      detail: error.response.data?.detail || error.response.data?.message || 'An error occurred',
      status_code: error.response.status,
      error_code: error.response.data?.error_code,
      field_errors: error.response.data?.field_errors,
    }
  }
  
  return {
    detail: error.message || 'Network error',
    status_code: 0,
  }
}

// File upload utility
export const uploadFile = async (
  url: string,
  file: File,
  onProgress?: (progress: number) => void
): Promise<AxiosResponse> => {
  const formData = new FormData()
  formData.append('file', file)

  return apiClient.post(url, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent) => {
      if (onProgress && progressEvent.total) {
        const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        onProgress(progress)
      }
    },
  })
}

// Download file utility
export const downloadFile = async (url: string, filename?: string): Promise<void> => {
  if (!isClient) return // Don't run download logic on Next.js server pre-renders

  const response = await apiClient.get(url, {
    responseType: 'blob',
  })

  const blob = new Blob([response.data])
  const downloadUrl = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = downloadUrl
  link.download = filename || 'download'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(downloadUrl)
}

// WebSocket connection utility
export const createWebSocketUrl = (path: string): string => {
  if (!isClient) return '' // Safe fallback for server compilation
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsHost = process.env.NEXT_PUBLIC_WS_HOST || window.location.host
  return `${wsProtocol}//${wsHost}${path}`
}

export { apiClient }
