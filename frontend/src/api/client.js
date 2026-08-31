import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const client = axios.create({ baseURL: API_BASE_URL })

export async function fetchTeams() {
  const { data } = await client.get('/teams')
  return data
}

export async function fetchTeamPlayers(teamId, { dateFrom, dateTo } = {}) {
  const { data } = await client.get(`/teams/${teamId}/players`, {
    params: {
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    },
  })
  return data
}

export async function fetchShots({ playerId, teamId, dateFrom, dateTo }) {
  const { data } = await client.get('/shots', {
    params: {
      player_id: playerId,
      team_id: teamId,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    },
  })
  return data
}
