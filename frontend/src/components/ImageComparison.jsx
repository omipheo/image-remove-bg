import '../styles/components/ImageComparison.css'

const ImageComparison = ({ originalImageUrl, processedImageUrl, currentFile, onDownload, isLoading, showDownload = true }) => {
  if (!originalImageUrl && !processedImageUrl) return null

  return (
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
          
          {processedImageUrl && (
            <div className="image-wrapper">
              <h3 className="image-label">Processed Image</h3>
              <div className="image-container">
                <img src={processedImageUrl} alt="Processed image" />
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

      {processedImageUrl && showDownload && (
        <div className="download-section">
          <button
            className="download-btn"
            onClick={onDownload}
            disabled={isLoading}
          >
            <span className="btn-icon">📥</span>
            Download Processed Image
          </button>
        </div>
      )}
    </>
  )
}

export default ImageComparison

