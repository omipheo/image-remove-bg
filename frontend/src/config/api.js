// ============================================
// API Configuration (for backend integration)
// ============================================
const getApiBaseUrl = () => {
  // Use environment variable in production, fallback to localhost for development
  return import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
}

const API_BASE_URL = getApiBaseUrl()

export const API_CONFIG = {
  // Backend API endpoints
  BASE_URL: API_BASE_URL,
  UPLOAD_ENDPOINT: `${API_BASE_URL}/api/upload`,
  DOWNLOAD_ENDPOINT: `${API_BASE_URL}/api/download`,
  USE_BACKEND: true // Set to true to use backend, false for local mode
}

