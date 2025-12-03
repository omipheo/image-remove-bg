// ============================================
// API Configuration (for backend integration)
// ============================================
const getApiBaseUrl = () => {
  // Use environment variable if set (highest priority)
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL
  }
  
  // In development mode (npm run dev), always use localhost:8000
  // import.meta.env.DEV is true when running `npm run dev`
  // import.meta.env.PROD is true when running `npm run build` and serving the built files
  if (import.meta.env.DEV || import.meta.env.MODE === 'development') {
    return 'http://localhost:8000'
  }
  
  // In production build, use relative URLs (nginx will proxy /api to backend)
  return '' // Empty string = relative URLs
}

const API_BASE_URL = getApiBaseUrl()

// Debug logging in development
if (import.meta.env.DEV) {
  console.log('API Configuration:', {
    mode: import.meta.env.MODE,
    dev: import.meta.env.DEV,
    prod: import.meta.env.PROD,
    baseUrl: API_BASE_URL,
    uploadEndpoint: `${API_BASE_URL}/api/upload`
  })
}

export const API_CONFIG = {
  // Backend API endpoints
  BASE_URL: API_BASE_URL,
  UPLOAD_ENDPOINT: `${API_BASE_URL}/api/upload`,
  DOWNLOAD_ENDPOINT: `${API_BASE_URL}/api/download`,
  USE_BACKEND: true // Set to true to use backend, false for local mode
}

