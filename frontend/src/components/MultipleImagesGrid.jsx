import '../styles/components/MultipleImagesGrid.css'

const MultipleImagesGrid = ({
  processedImages,
  onDownload,
  fileType,
  isLoading,
  showDownload = true
}) => {
  if (!Array.isArray(processedImages) || processedImages.length === 0) {
    return null
  }

  return (
    <div className="multiple-images-section">
      <h2 className="section-title">
        All Processed Images ({processedImages.length})
        {isLoading && (
          <span className="processing-indicator"> Processing...</span>
        )}
      </h2>

      <div className="images-grid">
        {processedImages.map((item, index) => {
          // HARD GUARDS (important)
          if (!item || !item.file) return null

          const filename = item.file?.name || `image-${index}`
          const filesize =
            typeof item.file?.size === 'number'
              ? (item.file.size / 1024).toFixed(2)
              : '—'

          return (
            <div
              key={item.imageId || `${filename}-${index}`}
              className="image-card"
            >
              <div className="image-card-header">
                <h4 className="image-card-title">{filename}</h4>
                <span className="image-card-size">{filesize} KB</span>
              </div>

              <div className="image-card-images">
                {/* ORIGINAL IMAGE */}
                <div className="image-card-item">
                  <p className="image-card-label">Original</p>
                  <div className="image-card-container">
                    {item.originalUrl ? (
                      <img
                        src={item.originalUrl}
                        alt={`Original ${filename}`}
                        loading="lazy"
                      />
                    ) : (
                      <div className="image-placeholder">Loading…</div>
                    )}
                  </div>
                </div>

                {/* PROCESSED IMAGE */}
                <div className="image-card-item">
                  <p className="image-card-label">Processed</p>
                  <div className="image-card-container">
                    {item.processedUrl ? (
                      <img
                        src={item.processedUrl}
                        alt={`Processed ${filename}`}
                        loading="lazy"
                        onError={e => {
                          console.error(
                            '[GRID] Image failed to load:',
                            filename
                          )
                          e.currentTarget.style.display = 'none'
                        }}
                      />
                    ) : (
                      <div className="image-placeholder">Processing…</div>
                    )}
                  </div>
                </div>
              </div>

              {showDownload && (
                <button
                  className="image-card-download"
                  onClick={() => onDownload(item, fileType)}
                  disabled={isLoading || !item.processedUrl}
                >
                  📥 Download
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
