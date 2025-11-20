import '../styles/components/ErrorMessage.css'

const ErrorMessage = ({ error, onDismiss }) => {
  if (!error) return null

  return (
    <div className="error-message">
      <span className="error-text">Error: {error}</span>
      {onDismiss && (
        <button className="error-dismiss" onClick={onDismiss}>×</button>
      )}
    </div>
  )
}

export default ErrorMessage

