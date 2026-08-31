function DateRangeInputs({ dateFrom, dateTo, onDateFromChange, onDateToChange }) {
  return (
    <div className="control-group">
      <label htmlFor="date-from">Date range</label>
      <div className="date-range">
        <input
          id="date-from"
          type="date"
          value={dateFrom}
          onChange={(e) => onDateFromChange(e.target.value)}
          aria-label="From date"
        />
        <span>to</span>
        <input
          id="date-to"
          type="date"
          value={dateTo}
          onChange={(e) => onDateToChange(e.target.value)}
          aria-label="To date"
        />
      </div>
    </div>
  )
}

export default DateRangeInputs
