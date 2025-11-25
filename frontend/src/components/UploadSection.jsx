import { useRef, useState } from 'react'
import '../styles/components/UploadSection.css'

const UploadSection = ({ onFilesSelected, isLoading, onDownloadAll, hasProcessedImages, onStop, showDownload = true }) => {
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef(null)
  const dropZoneRef = useRef(null)

  const handleDragEnter = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDrop = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)

    const files = Array.from(e.dataTransfer.files || [])
    if (files.length > 0) {
      onFilesSelected(files)
    }
  }

  const handleFileChange = (e) => {
    const files = Array.from(e.target.files || [])
    if (files.length > 0) {
      onFilesSelected(files)
      e.target.value = '' // Reset input
    }
  }

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  return (
    <div className="upload-section">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        onChange={handleFileChange}
        multiple
        style={{ display: 'none' }}
      />
      <div
        ref={dropZoneRef}
        className={`drop-zone ${isDragging ? 'dragging' : ''}`}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className="drop-zone-content">
          <span className="drop-zone-icon">📁</span>
          <p className="drop-zone-text">
            {isDragging ? 'Drop images here' : 'Drag and drop images here'}
          </p>
          <p className="drop-zone-subtext">or</p>
          <div className="button-group">
            {!isLoading ? (
              <>
                <button
                  className="upload-btn"
                  onClick={handleUploadClick}
                  disabled={isLoading}
                >
                  <span className="btn-icon">📤</span>
                  Browse Images
                </button>
                {hasProcessedImages && showDownload && (
                  <button
                    className="download-all-btn"
                    onClick={onDownloadAll}
                    disabled={isLoading}
                  >
                    <span className="btn-icon">📥</span>
                    Download All
                  </button>
                )}
              </>
            ) : (
              <button
                className="stop-btn"
                onClick={onStop}
              >
                <span className="btn-icon">⏹️</span>
                Stop Processing
              </button>
            )}
          </div>
          <p className="drop-zone-hint">You can select one or more images</p>
        </div>
      </div>
    </div>
  )
}

export default UploadSection

