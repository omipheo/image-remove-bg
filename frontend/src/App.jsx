import { useState, useRef } from 'react'
import './App.css'
import { API_CONFIG } from './config/api'

function App() {
  const [imageUrl, setImageUrl] = useState(null) // Processed image URL
  const [originalImageUrl, setOriginalImageUrl] = useState(null) // Original image URL
  const [currentFile, setCurrentFile] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [imageId, setImageId] = useState(null) // Store image ID from backend
  const [fileType, setFileType] = useState('PNG') // PNG or JPEG
  const [backgroundColor, setBackgroundColor] = useState('transparent') // white, black, transparent
  const fileInputRef = useRef(null)

  // ============================================
  // Backend API Functions
  // ============================================
  const uploadImageToBackend = async (file, bgColor, outputFormat) => {
    const formData = new FormData()
    formData.append('image', file)
    formData.append('backgroundColor', bgColor)
    formData.append('fileType', outputFormat)
    
    try {
      const response = await fetch(API_CONFIG.UPLOAD_ENDPOINT, {
        method: 'POST',
        body: formData
      })
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Upload failed' }))
        throw new Error(errorData.detail || 'Upload failed')
      }
      
      const data = await response.json()
      return {
        imageUrl: data.imageUrl,
        imageId: data.imageId
      }
    } catch (error) {
      throw new Error(`Upload failed: ${error.message}`)
    }
  }

  const downloadImageFromBackend = async (imageId, outputFormat) => {
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

  // ============================================
  // Local File Handling
  // ============================================
  const handleImageLocally = (file) => {
    const reader = new FileReader()
    
    reader.onload = (event) => {
      setImageUrl(event.target.result)
      setIsLoading(false)
      setError(null)
    }
    
    reader.onerror = () => {
      setError('Failed to read image file')
      setIsLoading(false)
    }
    
    reader.readAsDataURL(file)
  }

  const downloadImageLocally = () => {
    if (imageUrl) {
      const link = document.createElement('a')
      link.href = imageUrl
      link.download = currentFile?.name || 'downloaded-image.png'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    }
  }

  // ============================================
  // Main Handlers
  // ============================================
  const readOriginalImage = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = (event) => resolve(event.target.result)
      reader.onerror = () => reject(new Error('Failed to read image file'))
      reader.readAsDataURL(file)
    })
  }

  const handleImageUpload = async (file) => {
    if (!file) return
    
    setCurrentFile(file)
    setIsLoading(true)
    setImageUrl(null)
    setOriginalImageUrl(null)
    setError(null)
    setImageId(null)
    
    try {
      // Read and display original image first
      const originalUrl = await readOriginalImage(file)
      setOriginalImageUrl(originalUrl)
      
      if (API_CONFIG.USE_BACKEND) {
        // Backend mode
        const result = await uploadImageToBackend(file, backgroundColor, fileType)
        setImageUrl(result.imageUrl)
        setImageId(result.imageId)
        setIsLoading(false)
      } else {
        // Local mode (current)
        handleImageLocally(file)
      }
    } catch (err) {
      setError(err.message)
      setIsLoading(false)
    }
  }

  const handleFileChange = (e) => {
    const file = e.target.files?.[0]
    if (file) {
      handleImageUpload(file)
      // Reset the input so the same file can be selected again
      e.target.value = ''
    }
  }

  const handleUploadClick = () => {
    // Clear any previous errors
    setError(null)
    // Open file picker - state will be reset in handleImageUpload when file is selected
    fileInputRef.current?.click()
  }

  // Get accept attribute based on selected file type
  const getAcceptAttribute = () => {
    if (fileType === 'PNG') {
      return 'image/png'
    } else if (fileType === 'JPEG') {
      return 'image/jpeg,image/jpg'
    }
    return 'image/*'
  }

  const handleImageDownload = async () => {
    if (!imageUrl) return
    
    try {
      if (API_CONFIG.USE_BACKEND) {
        // Backend mode
        if (!imageId) {
          throw new Error('No image ID available')
        }
        const blob = await downloadImageFromBackend(imageId, fileType)
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        // Generate filename with "no-bg" suffix and correct extension
        const originalName = currentFile?.name || 'image.png'
        const nameWithoutExt = originalName.replace(/\.[^/.]+$/, '')
        const extension = fileType.toLowerCase() === 'jpeg' ? 'jpg' : 'png'
        link.download = `${nameWithoutExt}-no-bg.${extension}`
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        window.URL.revokeObjectURL(url)
      } else {
        // Local mode (current)
        downloadImageLocally()
      }
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="container">
      <h1>Background Removal Tool</h1>
      
      <div className="upload-section">
        <input
          ref={fileInputRef}
          type="file"
          accept={getAcceptAttribute()}
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
        <button
          className="upload-btn"
          onClick={handleUploadClick}
          disabled={isLoading}
        >
          <span className="btn-icon">
            {isLoading ? '⏳' : '📤'}
          </span>
          {isLoading ? 'Processing...' : 'Upload Image'}
        </button>
      </div>

      <div className="options-section">
        <div className="option-group">
          <label className="option-label">File Type:</label>
          <select
            className="option-select"
            value={fileType}
            onChange={(e) => setFileType(e.target.value)}
            disabled={isLoading}
          >
            <option value="PNG">PNG</option>
            <option value="JPEG">JPEG</option>
          </select>
        </div>

        <div className="option-group">
          <label className="option-label">Background Color:</label>
          <select
            className="option-select"
            value={backgroundColor}
            onChange={(e) => setBackgroundColor(e.target.value)}
            disabled={isLoading}
          >
            <option value="transparent">Transparent</option>
            <option value="white">White</option>
            <option value="black">Black</option>
          </select>
        </div>
      </div>

      {error && (
        <div className="error-message">
          Error: {error}
        </div>
      )}

      {(originalImageUrl || imageUrl) && (
        <>
          <div className="image-section">
            <div className="images-comparison">
              {originalImageUrl && (
                <div className="image-wrapper">
                  <h3 className="image-label">Original Image</h3>
                  <div className="image-container">
                    <img src={originalImageUrl} alt="Original image" />
                  </div>
                </div>
              )}
              
              {imageUrl && (
                <div className="image-wrapper">
                  <h3 className="image-label">Processed Image</h3>
                  <div className="image-container">
                    <img src={imageUrl} alt="Processed image" />
                  </div>
                </div>
              )}
            </div>
            
            {currentFile && (
              <div className="image-info">
                <div className="image-info-item">
                  <span className="image-info-label">Filename:</span>
                  {currentFile.name}
                </div>
                <div className="image-info-item">
                  <span className="image-info-label">Size:</span>
                  {(currentFile.size / 1024).toFixed(2)} KB
                </div>
                <div className="image-info-item">
                  <span className="image-info-label">Type:</span>
                  {currentFile.type || 'Unknown'}
                </div>
              </div>
            )}
          </div>

          {imageUrl && (
            <div className="download-section">
              <button
                className="download-btn"
                onClick={handleImageDownload}
                disabled={isLoading}
              >
                <span className="btn-icon">📥</span>
                Download Processed Image
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default App

