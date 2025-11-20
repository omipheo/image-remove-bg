import '../styles/components/OptionsSection.css'

const OptionsSection = ({ fileType, backgroundColor, downloadMethod, onFileTypeChange, onBackgroundColorChange, onDownloadMethodChange, isLoading }) => {
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
        <label className="option-label">Download Method:</label>
        <select
          className="option-select"
          value={downloadMethod}
          onChange={(e) => onDownloadMethodChange(e.target.value)}
          disabled={isLoading}
        >
          <option value="individual">Individual Files</option>
          <option value="zip">ZIP File</option>
        </select>
      </div>
    </div>
  )
}

export default OptionsSection

