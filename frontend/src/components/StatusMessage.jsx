function StatusMessage({ kind = 'info', message }) {
  if (!message) return null
  return <p className={`status-message status-${kind}`}>{message}</p>
}

export default StatusMessage
