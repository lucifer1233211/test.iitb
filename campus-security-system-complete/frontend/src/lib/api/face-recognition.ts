import { apiClient } from './client'
import {
  FaceDetection,
  FaceEnrollment,
  PersonIdentification,
  PaginatedResponse,
  SearchFilters,
  SortOptions,
  PaginationOptions,
} from '@/types/api'

export interface EnrollFaceRequest {
  person_name: string
  person_id?: string
  images: File[]
  department?: string
  employee_id?: string
  metadata?: Record<string, any>
}

export interface EnrollFaceResponse {
  enrollment_id: string
  person_id: string
  person_name: string
  face_count: number
  quality_scores: number[]
  message: string
}

export interface IdentifyFaceRequest {
  image: File
  camera_id?: string
  threshold?: number
  return_embeddings?: boolean
}

export interface IdentifyFaceResponse {
  detected_faces: Array<{
    bbox: { x: number; y: number; width: number; height: number }
    confidence: number
    quality_score: number
    identification?: {
      person_id: string
      person_name: string
      confidence: number
      similarity_score: number
    }
    is_spoofing_detected: boolean
  }>
  processing_time: number
}

export interface VerifyFaceRequest {
  image: File
  person_id: string
  threshold?: number
}

export interface VerifyFaceResponse {
  is_match: boolean
  confidence: number
  similarity_score: number
  quality_score: number
  is_spoofing_detected: boolean
  processing_time: number
}

export interface UpdatePersonRequest {
  person_name?: string
  department?: string
  employee_id?: string
  is_active?: boolean
  metadata?: Record<string, any>
}

export interface BulkEnrollRequest {
  enrollments: Array<{
    person_name: string
    person_id?: string
    image_urls?: string[]
    image_files?: File[]
    department?: string
    employee_id?: string
    metadata?: Record<string, any>
  }>
}

export interface BulkEnrollResponse {
  total_processed: number
  successful_enrollments: number
  failed_enrollments: number
  results: Array<{
    person_name: string
    person_id?: string
    status: 'success' | 'failed'
    message: string
    enrollment_id?: string
  }>
}

export const faceRecognitionApi = {
  // Face enrollment
  async enrollFace(data: EnrollFaceRequest): Promise<EnrollFaceResponse> {
    const formData = new FormData()
    formData.append('person_name', data.person_name)
    if (data.person_id) formData.append('person_id', data.person_id)
    if (data.department) formData.append('department', data.department)
    if (data.employee_id) formData.append('employee_id', data.employee_id)
    if (data.metadata) formData.append('metadata', JSON.stringify(data.metadata))
    
    data.images.forEach((image, index) => {
      formData.append(`images`, image)
    })

    const response = await apiClient.post<EnrollFaceResponse>('/face/enroll', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  async bulkEnrollFaces(data: BulkEnrollRequest): Promise<BulkEnrollResponse> {
    const formData = new FormData()
    
    data.enrollments.forEach((enrollment, index) => {
      formData.append(`enrollments[${index}][person_name]`, enrollment.person_name)
      if (enrollment.person_id) {
        formData.append(`enrollments[${index}][person_id]`, enrollment.person_id)
      }
      if (enrollment.department) {
        formData.append(`enrollments[${index}][department]`, enrollment.department)
      }
      if (enrollment.employee_id) {
        formData.append(`enrollments[${index}][employee_id]`, enrollment.employee_id)
      }
      if (enrollment.metadata) {
        formData.append(`enrollments[${index}][metadata]`, JSON.stringify(enrollment.metadata))
      }
      if (enrollment.image_urls) {
        enrollment.image_urls.forEach((url, urlIndex) => {
          formData.append(`enrollments[${index}][image_urls][${urlIndex}]`, url)
        })
      }
      if (enrollment.image_files) {
        enrollment.image_files.forEach((file) => {
          formData.append(`enrollments[${index}][images]`, file)
        })
      }
    })

    const response = await apiClient.post<BulkEnrollResponse>('/face/bulk-enroll', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  // Face identification
  async identifyFace(data: IdentifyFaceRequest): Promise<IdentifyFaceResponse> {
    const formData = new FormData()
    formData.append('image', data.image)
    if (data.camera_id) formData.append('camera_id', data.camera_id)
    if (data.threshold) formData.append('threshold', data.threshold.toString())
    if (data.return_embeddings) formData.append('return_embeddings', data.return_embeddings.toString())

    const response = await apiClient.post<IdentifyFaceResponse>('/face/identify', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  // Face verification
  async verifyFace(data: VerifyFaceRequest): Promise<VerifyFaceResponse> {
    const formData = new FormData()
    formData.append('image', data.image)
    formData.append('person_id', data.person_id)
    if (data.threshold) formData.append('threshold', data.threshold.toString())

    const response = await apiClient.post<VerifyFaceResponse>('/face/verify', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  // Person management
  async getEnrolledPersons(
    filters?: SearchFilters,
    sort?: SortOptions,
    pagination?: PaginationOptions
  ): Promise<PaginatedResponse<FaceEnrollment>> {
    const params = new URLSearchParams()
    
    if (filters?.query) params.append('query', filters.query)
    if (filters?.start_date) params.append('start_date', filters.start_date)
    if (filters?.end_date) params.append('end_date', filters.end_date)
    if (sort?.field) params.append('sort_field', sort.field)
    if (sort?.direction) params.append('sort_direction', sort.direction)
    if (pagination?.page) params.append('page', pagination.page.toString())
    if (pagination?.size) params.append('size', pagination.size.toString())

    const response = await apiClient.get<PaginatedResponse<FaceEnrollment>>(
      `/face/persons?${params.toString()}`
    )
    return response.data
  },

  async getPersonById(personId: string): Promise<FaceEnrollment> {
    const response = await apiClient.get<FaceEnrollment>(`/face/persons/${personId}`)
    return response.data
  },

  async updatePerson(personId: string, data: UpdatePersonRequest): Promise<FaceEnrollment> {
    const response = await apiClient.patch<FaceEnrollment>(`/face/persons/${personId}`, data)
    return response.data
  },

  async deletePerson(personId: string): Promise<void> {
    await apiClient.delete(`/face/persons/${personId}`)
  },

  async addPersonImages(personId: string, images: File[]): Promise<{
    added_images: number
    quality_scores: number[]
    message: string
  }> {
    const formData = new FormData()
    images.forEach((image) => {
      formData.append('images', image)
    })

    const response = await apiClient.post(
      `/face/persons/${personId}/images`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    )
    return response.data
  },

  async removePersonImage(personId: string, imageId: string): Promise<void> {
    await apiClient.delete(`/face/persons/${personId}/images/${imageId}`)
  },

  // Detection history
  async getDetections(
    filters?: SearchFilters,
    sort?: SortOptions,
    pagination?: PaginationOptions
  ): Promise<PaginatedResponse<FaceDetection>> {
    const params = new URLSearchParams()
    
    if (filters?.query) params.append('query', filters.query)
    if (filters?.start_date) params.append('start_date', filters.start_date)
    if (filters?.end_date) params.append('end_date', filters.end_date)
    if (filters?.camera_ids) {
      filters.camera_ids.forEach(id => params.append('camera_ids', id))
    }
    if (filters?.person_ids) {
      filters.person_ids.forEach(id => params.append('person_ids', id))
    }
    if (filters?.alert_levels) {
      filters.alert_levels.forEach(level => params.append('alert_levels', level))
    }
    if (sort?.field) params.append('sort_field', sort.field)
    if (sort?.direction) params.append('sort_direction', sort.direction)
    if (pagination?.page) params.append('page', pagination.page.toString())
    if (pagination?.size) params.append('size', pagination.size.toString())

    const response = await apiClient.get<PaginatedResponse<FaceDetection>>(
      `/face/detections?${params.toString()}`
    )
    return response.data
  },

  async getDetectionById(detectionId: string): Promise<FaceDetection> {
    const response = await apiClient.get<FaceDetection>(`/face/detections/${detectionId}`)
    return response.data
  },

  async getDetectionImage(detectionId: string): Promise<Blob> {
    const response = await apiClient.get(`/face/detections/${detectionId}/image`, {
      responseType: 'blob',
    })
    return response.data
  },

  // Search and analytics
  async searchSimilarFaces(
    image: File,
    threshold?: number,
    limit?: number
  ): Promise<Array<{
    person_id: string
    person_name: string
    similarity_score: number
    last_seen: string
    detection_count: number
  }>> {
    const formData = new FormData()
    formData.append('image', image)
    if (threshold) formData.append('threshold', threshold.toString())
    if (limit) formData.append('limit', limit.toString())

    const response = await apiClient.post('/face/search-similar', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  async getPersonAnalytics(
    personId: string,
    startDate?: string,
    endDate?: string
  ): Promise<{
    total_detections: number
    unique_locations: string[]
    detection_timeline: Array<{ date: string; count: number }>
    location_frequency: Array<{ location: string; count: number }>
    peak_hours: Array<{ hour: number; count: number }>
    average_confidence: number
  }> {
    const params = new URLSearchParams()
    if (startDate) params.append('start_date', startDate)
    if (endDate) params.append('end_date', endDate)

    const response = await apiClient.get(
      `/face/persons/${personId}/analytics?${params.toString()}`
    )
    return response.data
  },

  // System configuration
  async getFaceRecognitionConfig(): Promise<{
    detection_threshold: number
    identification_threshold: number
    anti_spoofing_enabled: boolean
    quality_threshold: number
    max_faces_per_frame: number
    supported_formats: string[]
    max_image_size: number
  }> {
    const response = await apiClient.get('/face/config')
    return response.data
  },

  async updateFaceRecognitionConfig(config: {
    detection_threshold?: number
    identification_threshold?: number
    anti_spoofing_enabled?: boolean
    quality_threshold?: number
    max_faces_per_frame?: number
  }): Promise<void> {
    await apiClient.patch('/face/config', config)
  },

  // Health check
  async healthCheck(): Promise<{
    status: 'healthy' | 'degraded' | 'unhealthy'
    models_loaded: boolean
    detection_model: string
    recognition_model: string
    anti_spoofing_model: string
    processing_queue_size: number
    average_processing_time: number
  }> {
    const response = await apiClient.get('/face/health')
    return response.data
  },
}