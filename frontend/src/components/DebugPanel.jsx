import { useState, useEffect } from 'react'
import { API_CONFIG } from '../config/api'
import '../styles/components/DebugPanel.css'

const DebugPanel = ({ frontendProcessedImages }) => {
  const [backendImages, setBackendImages] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [expanded, setExpanded] = useState(false)

  const fetchBackendImages = async () => {
    setLoading(true)
    setError(null)
    try {
      const url = `${API_CONFIG.BASE_URL}/api/debug/processed-images`
      console.log('[DEBUG] Fetching backend images from:', url)
      const response = await fetch(url)
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      const data = await response.json()
      console.log('[DEBUG] Backend API response:', data)
      setBackendImages(data)
    } catch (err) {
      setError(err.message)
      console.error('[DEBUG] Error fetching backend images:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (expanded) {
      // Small delay to ensure backend has finished storing images
      const timer = setTimeout(() => {
        fetchBackendImages()
      }, 500)
      return () => clearTimeout(timer)
    }
  }, [expanded])
  
  // Also refresh when frontend images change
  useEffect(() => {
    if (expanded && frontendProcessedImages?.length > 0) {
      // Refresh backend data after a short delay when frontend receives new images
      const timer = setTimeout(() => {
        fetchBackendImages()
      }, 1000)
      return () => clearTimeout(timer)
    }
  }, [expanded, frontendProcessedImages?.length])

  return (
    <div className="debug-panel">
      <div className="debug-panel-header" onClick={() => setExpanded(!expanded)}>
        <h3>🐛 Debug Panel</h3>
        <span className="debug-toggle">{expanded ? '▼' : '▶'}</span>
      </div>
      
      {expanded && (
        <div className="debug-panel-content">
          <div className="debug-section">
            <h4>Frontend State ({frontendProcessedImages?.length || 0} images)</h4>
            <button onClick={fetchBackendImages} disabled={loading} className="debug-refresh-btn">
              {loading ? 'Loading...' : '🔄 Refresh Backend Data'}
            </button>
            
            {frontendProcessedImages && frontendProcessedImages.length > 0 ? (
              <div className="debug-images-list">
                {frontendProcessedImages.map((img, idx) => (
                  <div key={img.imageId || idx} className="debug-image-item">
                    <div className="debug-image-info">
                      <strong>{img.file?.name || 'Unknown'}</strong>
                      <div className="debug-image-details">
                        <span>ID: {img.imageId}</span>
                        <span>URL: {img.processedUrl?.substring(0, 60)}...</span>
                      </div>
                    </div>
                    {img.processedUrl && (
                      <img 
                        src={img.processedUrl} 
                        alt={img.file?.name}
                        className="debug-thumbnail"
                        onError={(e) => {
                          e.target.style.display = 'none'
                          e.target.nextSibling.textContent = '❌ Failed to load'
                        }}
                      />
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="debug-empty">No images in frontend state</p>
            )}
          </div>

          <div className="debug-section">
            <h4>Backend API ({backendImages?.total_images || 0} images)</h4>
            
            {error && (
              <div className="debug-error">
                ❌ Error: {error}
              </div>
            )}
            
            {backendImages && backendImages.images && backendImages.images.length > 0 ? (
              <div className="debug-images-list">
                {backendImages.images.map((img, idx) => (
                  <div key={img.imageId || idx} className="debug-image-item">
                    <div className="debug-image-info">
                      <strong>{img.filename}</strong>
                      <div className="debug-image-details">
                        <span>ID: {img.imageId}</span>
                        <span>Size: {(img.size_bytes / 1024).toFixed(2)} KB</span>
                        <span>Format: {img.format}</span>
                        <span>Pre-uploaded: {img.pre_uploaded ? 'Yes' : 'No'}</span>
                      </div>
                      <a 
                        href={`${API_CONFIG.BASE_URL}${img.downloadUrl}`} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="debug-download-link"
                      >
                        🔗 Download
                      </a>
                    </div>
                    <img 
                      src={`${API_CONFIG.BASE_URL}${img.downloadUrl}`}
                      alt={img.filename}
                      className="debug-thumbnail"
                      onError={(e) => {
                        e.target.style.display = 'none'
                        e.target.nextSibling.textContent = '❌ Failed to load'
                      }}
                    />
                  </div>
                ))}
              </div>
            ) : backendImages && backendImages.total_images === 0 ? (
              <p className="debug-empty">No images in backend storage</p>
            ) : null}
          </div>

          <div className="debug-section">
            <h4>Comparison</h4>
            <div className="debug-comparison">
              <div className="comparison-item">
                <span>Frontend Count:</span>
                <strong>{frontendProcessedImages?.length || 0}</strong>
              </div>
              <div className="comparison-item">
                <span>Backend Count:</span>
                <strong>{backendImages?.total_images || 0}</strong>
              </div>
              <div className="comparison-item">
                <span>Match:</span>
                <strong className={frontendProcessedImages?.length === backendImages?.total_images ? 'match-yes' : 'match-no'}>
                  {frontendProcessedImages?.length === backendImages?.total_images ? '✅' : '❌'}
                </strong>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default DebugPanel

