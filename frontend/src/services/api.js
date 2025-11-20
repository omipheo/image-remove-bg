import { API_CONFIG } from '../config/api'

/**
 * Upload image to backend for processing
 */
export const uploadImageToBackend = async (file, bgColor, outputFormat, signal = null) => {
  const formData = new FormData()
  formData.append('image', file)
  formData.append('backgroundColor', bgColor)
  formData.append('fileType', outputFormat)
  
  try {
    console.log('Uploading to:', API_CONFIG.UPLOAD_ENDPOINT)
    const fetchOptions = {
      method: 'POST',
      body: formData
    }
    
    if (signal) {
      fetchOptions.signal = signal
    }
    
    const response = await fetch(API_CONFIG.UPLOAD_ENDPOINT, fetchOptions)
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(errorData.detail || `Upload failed with status ${response.status}`)
    }
    
    const data = await response.json()
    return {
      imageUrl: data.imageUrl,
      imageId: data.imageId
    }
  } catch (error) {
    // Handle abort error
    if (error.name === 'AbortError') {
      throw error
    }
    // More detailed error message
    if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
      throw new Error(`Cannot connect to backend. Make sure the backend is running on ${API_CONFIG.BASE_URL || 'http://localhost:8000'}`)
    }
    throw new Error(`Upload failed: ${error.message}`)
  }
}

/**
 * Download processed image from backend
 */
export const downloadImageFromBackend = async (imageId, outputFormat) => {
  try {
    const response = await fetch(`${API_CONFIG.DOWNLOAD_ENDPOINT}?imageId=${encodeURIComponent(imageId)}&fileType=${encodeURIComponent(outputFormat)}`)
    if (!response.ok) {
      throw new Error('Download failed')
    }
    const blob = await response.blob()
    return blob
  } catch (error) {
    throw new Error(`Download failed: ${error.message}`)
  }
}

