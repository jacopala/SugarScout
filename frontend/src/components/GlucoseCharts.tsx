import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { HourPoint, LivePoint } from '../lib/api'
import { BANDS } from '../lib/bands'

const Y_DOMAIN: [number, number] = [40, 320]
const Y_TICKS = [54, 70, 180, 250]

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit', second: '2-digit' })
const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short' })
const dayHourFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', hour: 'numeric' })

function Bands() {
  return (
    <>
      {/* Target range: the one band worth tinting. Others stay neutral and labelled. */}
      <ReferenceArea y1={BANDS.low} y2={BANDS.high} fill="var(--band-target)" fillOpacity={1} ifOverflow="hidden" />
      <ReferenceLine
        y={BANDS.urgentLow}
        stroke="var(--status-bad)"
        strokeDasharray="4 4"
        label={{ value: 'Urgent low 54', position: 'insideBottomLeft', fill: 'var(--text-muted)', fontSize: 11 }}
      />
      <ReferenceLine y={BANDS.low} stroke="var(--grid-strong)" strokeDasharray="2 4" />
      <ReferenceLine y={BANDS.high} stroke="var(--grid-strong)" strokeDasharray="2 4" />
      <ReferenceLine
        y={BANDS.veryHigh}
        stroke="var(--grid-strong)"
        strokeDasharray="2 4"
        label={{ value: '250', position: 'insideTopLeft', fill: 'var(--text-muted)', fontSize: 11 }}
      />
    </>
  )
}

const axisProps = {
  stroke: 'var(--text-muted)',
  tick: { fill: 'var(--text-muted)', fontSize: 12 },
  tickLine: false,
  axisLine: false,
} as const

function TooltipBox({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-title">{title}</div>
      {rows.map(([k, v]) => (
        <div key={k} className="chart-tooltip-row">
          <span>{k}</span>
          <strong>{v}</strong>
        </div>
      ))}
    </div>
  )
}

export function LiveChart({ points }: { points: LivePoint[] }) {
  const data = points.map((p) => ({ t: new Date(p.ts).getTime(), value: p.value }))
  return (
    <div className="chart" role="img" aria-label="Glucose readings over the last 10 minutes">
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <Bands />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={['dataMin', 'dataMax']}
            tickFormatter={(t: number) => timeFmt.format(t)}
            minTickGap={48}
            {...axisProps}
          />
          <YAxis domain={Y_DOMAIN} ticks={Y_TICKS} width={44} {...axisProps} />
          <Tooltip
            cursor={{ stroke: 'var(--text-muted)', strokeDasharray: '3 3' }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as { t: number; value: number } | undefined
              if (!active || !p) return null
              return <TooltipBox title={timeFmt.format(p.t)} rows={[['Glucose', `${p.value} mg/dL`]]} />
            }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5, stroke: 'var(--surface)', strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export function WeekChart({ points }: { points: HourPoint[] }) {
  const data = points.map((p) => ({
    t: new Date(p.bucket).getTime(),
    avg: p.avg,
    range: [p.min, p.max] as [number, number],
    min: p.min,
    max: p.max,
  }))
  return (
    <div className="chart" role="img" aria-label="Hourly glucose average and range over the last 7 days">
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <Bands />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={['dataMin', 'dataMax']}
            tickFormatter={(t: number) => dayFmt.format(t)}
            minTickGap={40}
            {...axisProps}
          />
          <YAxis domain={Y_DOMAIN} ticks={Y_TICKS} width={44} {...axisProps} />
          <Tooltip
            cursor={{ stroke: 'var(--text-muted)', strokeDasharray: '3 3' }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as { t: number; avg: number; min: number; max: number } | undefined
              if (!active || !p) return null
              return (
                <TooltipBox
                  title={dayHourFmt.format(p.t)}
                  rows={[
                    ['Average', `${Math.round(p.avg)} mg/dL`],
                    ['Range', `${p.min}–${p.max}`],
                  ]}
                />
              )
            }}
          />
          <Area dataKey="range" stroke="none" fill="var(--series-1)" fillOpacity={0.14} isAnimationActive={false} />
          <Line
            type="monotone"
            dataKey="avg"
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: 'var(--surface)', strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="chart-caption">Line: hourly average. Shaded: hourly min to max. Green band: target range 70–180.</p>
    </div>
  )
}
