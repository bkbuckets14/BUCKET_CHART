function PlayerSelect({ players, selectedPlayerId, onChange, loading, error, disabled }) {
  return (
    <div className="control-group">
      <label htmlFor="player-select">Player</label>
      <select
        id="player-select"
        value={selectedPlayerId}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || loading}
      >
        <option value="">
          {loading ? 'Loading players…' : 'Select a player…'}
        </option>
        {players.map((player) => (
          <option key={player.player_id} value={player.player_id}>
            {player.full_name}
          </option>
        ))}
      </select>
      {error && <p className="field-error">{error}</p>}
    </div>
  )
}

export default PlayerSelect
