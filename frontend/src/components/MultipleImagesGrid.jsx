import '../styles/components/MultipleImagesGrid.css'

const MultipleImagesGrid = ({ processedImages, onDownload, fileType, isLoading }) => {
  if (!processedImages || processedImages.length === 0) return null

  return (
    <div className="multiple-images-section">
      <h2 className="section-title">
        Additional Processed Images ({processedImages.length})
        {isLoading && <span className="processing-indicator">Processing...</span>}
      </h2>
      <div className="images-grid">
        {processedImages.map((item, index) => (
          <div key={item.imageId || `${item.file.name}-${index}`} className="image-card">
            <div className="image-card-header">
              <h4 className="image-card-title">{item.file.name}</h4>
              <span className="image-card-size">{(item.file.size / 1024).toFixed(2)} KB</span>
            </div>
            <div className="image-card-images">
              <div className="image-card-item">
                <p className="image-card-label">Original</p>
                <div className="image-card-container">
                  <img src={item.originalUrl} alt={`Original ${item.file.name}`} />
                </div>
              </div>
              <div className="image-card-item">
                <p className="image-card-label">Processed</p>
                <div className="image-card-container">
                  <img src={item.processedUrl} alt={`Processed ${item.file.name}`} />
                </div>
              </div>
            </div>
            <button
              className="image-card-download"
              onClick={() => onDownload(item, fileType)}
              disabled={isLoading}
            >
              <span className="btn-icon">📥</span>
              Download
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

export default MultipleImagesGrid

