import { scaleLinear } from 'd3'
import StatusMessage from './StatusMessage'
import './CourtChart.css'

const COURT_MIN_X = -25
const COURT_MAX_X = 25
const COURT_MIN_Y = 0 // baseline
const COURT_MAX_Y = 47 // half-court line
const HOOP_Y = 5.25 // hoop is 5.25ft from the baseline

const SVG_WIDTH = 500
const SVG_HEIGHT = 470
const FT_TO_PX = SVG_WIDTH / (COURT_MAX_X - COURT_MIN_X) // 10px per foot

const xScale = scaleLinear().domain([COURT_MIN_X, COURT_MAX_X]).range([0, SVG_WIDTH])
const yScale = scaleLinear().domain([COURT_MIN_Y, COURT_MAX_Y]).range([SVG_HEIGHT, 0])

function feetToSvg(locX, locY) {
  return { x: xScale(locX), y: yScale(locY) }
}

const paintTopLeft = feetToSvg(-8, 19) // paint extends 19ft from the baseline
const paintBottomRight = feetToSvg(8, COURT_MIN_Y)
const freeThrowCenter = feetToSvg(0, 19)
const backboardLeft = feetToSvg(-3, HOOP_Y - 1.25)
const backboardRight = feetToSvg(3, HOOP_Y - 1.25)
const rimCenter = feetToSvg(0, HOOP_Y)

const raLeft = feetToSvg(-4, HOOP_Y)
const raRight = feetToSvg(4, HOOP_Y)
const RA_RADIUS_PX = 4 * FT_TO_PX
const restrictedAreaPath = `M ${raLeft.x} ${raLeft.y} A ${RA_RADIUS_PX} ${RA_RADIUS_PX} 0 0 1 ${raRight.x} ${raRight.y}`

const THREE_PT_RADIUS = 23.75
const CORNER_X = 22
const CORNER_Y = HOOP_Y + Math.sqrt(THREE_PT_RADIUS ** 2 - CORNER_X ** 2)
const threeLeftBaseline = feetToSvg(-CORNER_X, COURT_MIN_Y)
const threeLeftArcStart = feetToSvg(-CORNER_X, CORNER_Y)
const threeRightArcEnd = feetToSvg(CORNER_X, CORNER_Y)
const threeRightBaseline = feetToSvg(CORNER_X, COURT_MIN_Y)
const THREE_PT_RADIUS_PX = THREE_PT_RADIUS * FT_TO_PX
const threePointPath =
  `M ${threeLeftBaseline.x} ${threeLeftBaseline.y} L ${threeLeftArcStart.x} ${threeLeftArcStart.y} ` +
  `A ${THREE_PT_RADIUS_PX} ${THREE_PT_RADIUS_PX} 0 0 1 ${threeRightArcEnd.x} ${threeRightArcEnd.y} ` +
  `L ${threeRightBaseline.x} ${threeRightBaseline.y}`

function CourtChart({ shots, loading, error }) {
  return (
    <div className="chart-wrapper">
      <svg
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        className="court-svg"
        role="img"
        aria-label="Half-court shot chart"
      >
        <rect x={0} y={0} width={SVG_WIDTH} height={SVG_HEIGHT} className="court-outline" />
        <rect
          x={paintTopLeft.x}
          y={paintTopLeft.y}
          width={paintBottomRight.x - paintTopLeft.x}
          height={paintBottomRight.y - paintTopLeft.y}
          className="court-line-shape"
        />
        <circle cx={freeThrowCenter.x} cy={freeThrowCenter.y} r={6 * FT_TO_PX} className="court-line-shape" />
        <path d={restrictedAreaPath} className="court-line-shape" />
        <line
          x1={backboardLeft.x}
          y1={backboardLeft.y}
          x2={backboardRight.x}
          y2={backboardRight.y}
          className="court-line-shape"
        />
        <circle cx={rimCenter.x} cy={rimCenter.y} r={0.75 * FT_TO_PX} className="court-rim" />
        <path d={threePointPath} className="court-line-shape" />

        {shots &&
          shots.map((shot, i) => {
            const { x, y } = feetToSvg(shot.loc_x, shot.loc_y)
            return (
              <circle
                key={i}
                cx={x}
                cy={y}
                r={3}
                className={shot.shot_made ? 'shot-made' : 'shot-missed'}
              />
            )
          })}
      </svg>

      {loading && <StatusMessage kind="info" message="Loading shot data…" />}
      {error && <StatusMessage kind="error" message={error} />}
      {!loading && !error && shots && shots.length === 0 && (
        <StatusMessage kind="empty" message="No shots recorded for this player in the selected range." />
      )}
      {!loading && !error && shots === null && (
        <div className="empty-state">
          <p>Select a team, player, and date range, then click Generate Chart.</p>
        </div>
      )}
    </div>
  )
}

export default CourtChart
