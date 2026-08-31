import { useEffect, useState } from 'react'
import { fetchTeams, fetchTeamPlayers, fetchShots } from './api/client'
import TeamSelect from './components/TeamSelect'
import DateRangeInputs from './components/DateRangeInputs'
import PlayerSelect from './components/PlayerSelect'
import StatusMessage from './components/StatusMessage'
import CourtChart from './components/CourtChart'
import './App.css'

function App() {
  const [teams, setTeams] = useState([])
  const [teamsLoading, setTeamsLoading] = useState(true)
  const [teamsError, setTeamsError] = useState(null)

  const [selectedTeamId, setSelectedTeamId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const [players, setPlayers] = useState([])
  const [playersLoading, setPlayersLoading] = useState(false)
  const [playersError, setPlayersError] = useState(null)

  const [selectedPlayerId, setSelectedPlayerId] = useState('')

  const [shots, setShots] = useState(null)
  const [shotsLoading, setShotsLoading] = useState(false)
  const [shotsError, setShotsError] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetchTeams()
      .then((data) => {
        if (!cancelled) setTeams(data)
      })
      .catch(() => {
        if (!cancelled) setTeamsError('Failed to load teams.')
      })
      .finally(() => {
        if (!cancelled) setTeamsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedTeamId) return
    let cancelled = false
    setPlayersLoading(true)
    setPlayersError(null)
    fetchTeamPlayers(selectedTeamId, { dateFrom, dateTo })
      .then((data) => {
        if (cancelled) return
        setPlayers(data)
        setSelectedPlayerId((prev) =>
          data.some((p) => String(p.player_id) === String(prev)) ? prev : '',
        )
      })
      .catch(() => {
        if (!cancelled) setPlayersError('Failed to load players for this team.')
      })
      .finally(() => {
        if (!cancelled) setPlayersLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedTeamId, dateFrom, dateTo])

  useEffect(() => {
    setShots(null)
    setShotsError(null)
  }, [selectedTeamId, selectedPlayerId, dateFrom, dateTo])

  function handleTeamChange(newTeamId) {
    setSelectedTeamId(newTeamId)
    setSelectedPlayerId('')
    if (!newTeamId) setPlayers([])
  }

  const canGenerateChart =
    Boolean(selectedTeamId) && Boolean(selectedPlayerId) && Boolean(dateFrom || dateTo)

  function handleGenerateChart() {
    if (!canGenerateChart) return
    setShotsLoading(true)
    setShotsError(null)
    fetchShots({ playerId: selectedPlayerId, teamId: selectedTeamId, dateFrom, dateTo })
      .then(setShots)
      .catch((err) => {
        const msg =
          err.response?.status === 400
            ? 'A date range is required to generate a chart.'
            : 'Failed to load shot data.'
        setShotsError(msg)
      })
      .finally(() => setShotsLoading(false))
  }

  return (
    <>
      <header>
        <h1>Bucket Chart</h1>
        <p>Pick a team, a player, and a date range to see their shot chart.</p>
      </header>

      <section className="controls">
        <TeamSelect
          teams={teams}
          selectedTeamId={selectedTeamId}
          onChange={handleTeamChange}
          loading={teamsLoading}
          error={teamsError}
        />
        <DateRangeInputs
          dateFrom={dateFrom}
          dateTo={dateTo}
          onDateFromChange={setDateFrom}
          onDateToChange={setDateTo}
        />
        <PlayerSelect
          players={players}
          selectedPlayerId={selectedPlayerId}
          onChange={setSelectedPlayerId}
          loading={playersLoading}
          error={playersError}
          disabled={!selectedTeamId}
        />
        <button
          type="button"
          className="generate-btn"
          onClick={handleGenerateChart}
          disabled={!canGenerateChart || shotsLoading}
        >
          {shotsLoading ? 'Loading…' : 'Generate Chart'}
        </button>
        {!canGenerateChart && selectedTeamId && selectedPlayerId && (
          <StatusMessage
            kind="info"
            message="Select a date range (from and/or to) to generate the chart."
          />
        )}
        {!playersLoading && !playersError && selectedTeamId && players.length === 0 && (
          <StatusMessage
            kind="empty"
            message="No players found for this team in the selected range."
          />
        )}
      </section>

      <section className="chart-section">
        <CourtChart shots={shots} loading={shotsLoading} error={shotsError} />
      </section>
    </>
  )
}

export default App
