import type { Trend } from '../lib/api'
import { AlertIcon, ArrowRightIcon, CheckIcon } from './Icons'
import {
  useDemoEvent,
  useDemoState,
  useForecast,
  useLatest,
  useSetScenario,
} from '../lib/queries'
import { BANDS } from '../lib/bands'

// Arrow rotation per CGM trend (flat icon, rotated like a CGM's trend arrow).
const TREND_ROTATE: Record<Trend, number> = {
  double_up: -90,
  up: -45,
  flat: 0,
  down: 45,
  double_down: 90,
}
const TREND_LABEL: Record<Trend, string> = {
  double_up: 'rising fast',
  up: 'rising',
  flat: 'steady',
  down: 'falling',
  double_down: 'falling fast',
}

function zone(value: number): { label: string; tone: 'ok' | 'warn' | 'bad' } {
  if (value < BANDS.urgentLow) return { label: 'Urgent low', tone: 'bad' }
  if (value < BANDS.low) return { label: 'Low', tone: 'warn' }
  if (value > BANDS.veryHigh) return { label: 'Very high', tone: 'warn' }
  if (value > BANDS.high) return { label: 'Above range', tone: 'warn' }
  return { label: 'In range', tone: 'ok' }
}

export function GlucoseHero() {
  const { data } = useLatest()
  const { data: fc } = useForecast()
  if (!data) return <div className="hero card">Loading…</div>
  if (data.value === null || data.stale) {
    return (
      <div className="hero card" data-tone="bad">
        <p className="eyebrow">Current glucose</p>
        <p className="hero-value">No recent data</p>
        <p className="hero-meta">
          <span className="status-chip" data-tone="bad">
            <AlertIcon size={14} strokeWidth={2.6} /> Sensor silent
          </span>
          {data.age_s !== null ? ` Last reading ${Math.round(data.age_s)}s ago` : null}
        </p>
      </div>
    )
  }
  const z = zone(data.value)
  const trend = data.trend ?? 'flat'
  return (
    <div className="hero card">
      <p className="eyebrow">Current glucose</p>
      <p className="hero-value">
        {data.value}
        <span className="hero-unit">mg/dL</span>
        <span className="hero-trend" aria-label={TREND_LABEL[trend]} title={TREND_LABEL[trend]}>
          <span style={{ display: 'inline-flex', transform: `rotate(${TREND_ROTATE[trend]}deg)` }}>
            <ArrowRightIcon size={24} strokeWidth={2.4} />
          </span>
        </span>
      </p>
      <p className="hero-meta">
        <span className="status-chip" data-tone={z.tone}>
          {z.tone === 'ok' ? <CheckIcon size={14} strokeWidth={2.6} /> : <AlertIcon size={14} strokeWidth={2.6} />}{' '}
          {z.label}
        </span>{' '}
        {TREND_LABEL[trend]} · updated {Math.round(data.age_s ?? 0)}s ago
      </p>
      {fc?.predicted != null && fc.slope_per_5min != null && Math.abs(fc.slope_per_5min) >= 2 ? (
        <p className="hero-meta">
          <span className="status-chip" data-tone={fc.predicted < BANDS.low || fc.predicted > BANDS.veryHigh ? 'warn' : 'ok'}>
            Heading to ~{fc.predicted} in ~{fc.horizon_min} min
          </span>
        </p>
      ) : null}
    </div>
  )
}

export function DemoControls() {
  const { data } = useDemoState()
  const setScenario = useSetScenario()
  const event = useDemoEvent()
  if (!data) return null
  return (
    <section className="card demo-controls" aria-labelledby="demo-h">
      <h2 id="demo-h">Demo controls</h2>
      <p className="section-note">
        Fake CGM: one reading every 5 seconds. SMS: <strong>{data.sms_mode === 'live' ? 'live' : 'dry run'}</strong>
        {' · '}AI: <strong>{data.llm_enabled ? 'on' : 'off'}</strong>
      </p>
      <div className="scenario-buttons" role="group" aria-label="Glucose scenario">
        {data.scenarios.map((s) => (
          <button
            key={s.id}
            className="btn"
            aria-pressed={data.scenario === s.id}
            onClick={() => setScenario.mutate(s.id)}
            disabled={setScenario.isPending}
          >
            {s.label}
          </button>
        ))}
      </div>
      <h3>Events</h3>
      <div className="scenario-buttons">
        <button className="btn" onClick={() => event.mutate('snack_no_insulin')} disabled={event.isPending}>
          Big snack, no insulin
        </button>
        <button className="btn" onClick={() => event.mutate('exercise')} disabled={event.isPending}>
          Exercise drop
        </button>
      </div>
      {setScenario.isError || event.isError ? <p className="form-error">Couldn’t change the scenario.</p> : null}
    </section>
  )
}
