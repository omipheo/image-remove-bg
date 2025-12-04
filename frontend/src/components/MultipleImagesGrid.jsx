import '../styles/components/MultipleImagesGrid.css'

const MultipleImagesGrid = ({ processedImages, onDownload, fileType, isLoading, showDownload = true }) => {
  if (!processedImages || processedImages.length === 0) return null

  return (
    <div className="multiple-images-section">
      <h2 className="section-title">
        Additional Processed Images ({processedImages.length})
        {isLoading && <span className="processing-indicator">Processing...</span>}
      </h2>
      <div className="images-grid">
        {processedImages.map((item, index) => {
          // Handle case where file might be null
          const fileName = item.file?.name || item.filename || `Image ${index + 1}`
          const fileSize = item.file?.size ? `${(item.file.size / 1024).toFixed(2)} KB` : 'N/A'
          
          return (
            <div key={item.imageId || `${fileName}-${index}`} className="image-card">
              <div className="image-card-header">
                <h4 className="image-card-title">{fileName}</h4>
                <span className="image-card-size">{fileSize}</span>
              </div>
              <div className="image-card-images">
                <div className="image-card-item">
                  <p className="image-card-label">Original</p>
                  <div className="image-card-container">
                    {item.originalUrl ? (
                      <img src={item.originalUrl} alt={`Original ${fileName}`} />
                    ) : (
                      <div className="image-placeholder">Original image not available</div>
                    )}
                  </div>
                </div>
                <div className="image-card-item">
                  <p className="image-card-label">Processed</p>
                  <div className="image-card-container">
                    {item.processedUrl ? (
                      <img src={item.processedUrl} alt={`Processed ${fileName}`} />
                    ) : (
                      <div className="image-placeholder">Processed image not available</div>
                    )}
                  </div>
                </div>
              </div>
            {showDownload && (
              <button
                className="image-card-download"
                onClick={() => onDownload(item, fileType)}
                disabled={isLoading}
              >
                <span className="btn-icon">📥</span>
                Download
              </button>
            )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default MultipleImagesGrid

