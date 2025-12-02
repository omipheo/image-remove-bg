import { useState, useEffect } from 'react'
import '../styles/components/OptionsSection.css'

const OptionsSection = ({ fileType, backgroundColor, downloadMethod, watermark, downloadMode, concurrency, onFileTypeChange, onBackgroundColorChange, onDownloadMethodChange, onWatermarkChange, onDownloadModeChange, onConcurrencyChange, isLoading }) => {
  const [concurrencyInput, setConcurrencyInput] = useState(concurrency.toString())

  // Update local state when prop changes
  useEffect(() => {
    setConcurrencyInput(concurrency.toString())
  }, [concurrency])

  const handleConcurrencyChange = (e) => {
    const value = e.target.value
    // Allow empty string for deletion
    if (value === '') {
      setConcurrencyInput('')
      return
    }
    
    // Only allow numeric input
    if (/^\d*$/.test(value)) {
      setConcurrencyInput(value)
    }
  }

  const handleConcurrencyBlur = (e) => {
    const value = e.target.value.trim()
    
    if (value === '') {
      // If empty, reset to current concurrency value
      setConcurrencyInput(concurrency.toString())
      return
    }
    
    const numValue = parseInt(value)
    if (isNaN(numValue) || numValue < 1) {
      // If invalid, set to minimum (1)
      const validValue = 1
      setConcurrencyInput(validValue.toString())
      onConcurrencyChange(validValue)
    } else if (numValue > 100) {
      // If too large, set to maximum (100)
      const validValue = 100
      setConcurrencyInput(validValue.toString())
      onConcurrencyChange(validValue)
    } else {
      // Valid value, update parent state
      onConcurrencyChange(numValue)
    }
  }

  return (
    <div className="options-section">
      <div className="option-group">
        <label className="option-label">File Type:</label>
        <select
          className="option-select"
          value={fileType}
          onChange={(e) => onFileTypeChange(e.target.value)}
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
          onChange={(e) => onBackgroundColorChange(e.target.value)}
          disabled={isLoading}
        >
          <option value="transparent">Transparent</option>
          <option value="white">White</option>
          <option value="black">Black</option>
        </select>
      </div>

      <div className="option-group">
        <label className="option-label">Watermark:</label>
        <select
          className="option-select"
          value={watermark}
          onChange={(e) => onWatermarkChange(e.target.value)}
          disabled={isLoading}
        >
          <option value="none">None</option>
          <option value="blog">Blog</option>
        </select>
      </div>

      <div className="option-group">
        <label className="option-label">Concurrent Processing:</label>
        <input
          type="text"
          inputMode="numeric"
          className="option-input"
          min="1"
          max="100"
          value={concurrencyInput}
          onChange={handleConcurrencyChange}
          onBlur={handleConcurrencyBlur}
          disabled={isLoading}
          title="Number of images to process simultaneously (1-10)"
        />
      </div>

      <div className="option-group">
        <label className="option-label">Download Mode:</label>
        <select
          className="option-select"
          value={downloadMode}
          onChange={(e) => onDownloadModeChange(e.target.value)}
          disabled={isLoading}
        >
          <option value="manual">Manual</option>
          <option value="automatic">Automatic</option>
        </select>
      </div>

      <div className="option-group">
        <label className="option-label">Download Method:</label>
        <select
          className="option-select"
          value={downloadMethod}
          onChange={(e) => onDownloadMethodChange(e.target.value)}
          disabled={isLoading || downloadMode === 'automatic'}
        >
          <option value="individual">Individual Files</option>
          <option value="zip">ZIP File</option>
        </select>
      </div>
    </div>
  )
}

export default OptionsSection

