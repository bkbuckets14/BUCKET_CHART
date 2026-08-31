function TeamSelect({ teams, selectedTeamId, onChange, loading, error }) {
  return (
    <div className="control-group">
      <label htmlFor="team-select">Team</label>
      <select
        id="team-select"
        value={selectedTeamId}
        onChange={(e) => onChange(e.target.value)}
        disabled={loading}
      >
        <option value="">{loading ? 'Loading teams…' : 'Select a team…'}</option>
        {teams.map((team) => (
          <option key={team.team_id} value={team.team_id}>
            {team.name}
          </option>
        ))}
      </select>
      {error && <p className="field-error">{error}</p>}
    </div>
  )
}

export default TeamSelect
