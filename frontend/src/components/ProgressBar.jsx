import '../styles/components/ProgressBar.css'

const ProgressBar = ({ progress, isLoading }) => {
  if (!isLoading || progress.total === 0) {
    return null
  }

  const { processed, total, percentage, currentBatch, totalBatches } = progress

  return (
    <div className="progress-bar-container">
      <div className="progress-bar-header">
        <span className="progress-text">
          Processing: {processed} / {total} images ({percentage}%)
        </span>
        {totalBatches > 0 && (
          <span className="progress-batch-info">
            Batch {currentBatch} / {totalBatches}
          </span>
        )}
      </div>
      <div className="progress-bar-wrapper">
        <div 
          className="progress-bar-fill" 
          style={{ width: `${percentage}%` }}
        >
          <div className="progress-bar-shine"></div>
        </div>
      </div>
    </div>
  )
}

export default ProgressBar

