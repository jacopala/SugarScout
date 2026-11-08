import type { AlertOut, NotificationOut, Trend } from '../lib/api'
import { AlertIcon, ArrowRightIcon, CheckIcon, PhoneIcon } from './Icons'
import { useAckAlert, useAlerts, useDemoState, useForecast, useLatest, useSetScenario } from '../lib/queries'
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

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit', second: '2-digit' })

function smsSummary(notifications: NotificationOut[]): string | null {
  const sms = notifications.filter((n) => n.channel === 'sms')
  if (sms.length === 0) return null
  return sms
    .map((n) => {
      const what = n.kind === 'opened' ? 'Alert text' : 'All-clear text'
      const how: Record<NotificationOut['status'], string> = {
        queued: 'sending…',
        sent: 'delivered to Twilio',
        dry_run: 'dry run (Twilio not configured)',
        skipped: 'skipped (cooldown)',
        failed: `failed${n.error ? `: ${n.error}` : ''}`,
      }
      return `${what}: ${how[n.status]}`
    })
    .join(' · ')
}

function AlertRow({ alert }: { alert: AlertOut }) {
  const ack = useAckAlert()
  const sms = smsSummary(alert.notifications)
  const tone = alert.state === 'resolved' ? 'muted' : alert.severity === 'urgent' ? 'bad' : 'warn'
  return (
    <li className="alert-row" data-tone={tone}>
      <div className="alert-main">
        <div className="alert-title">
          <span className="status-chip" data-tone={tone}>
            {alert.state === 'open' ? <AlertIcon size={14} strokeWidth={2.6} /> : <CheckIcon size={14} strokeWidth={2.6} />}
            {alert.state === 'resolved' ? 'Cleared' : alert.state === 'acknowledged' ? 'Seen' : 'Open'}
          </span>
          <strong>{alert.label}</strong>
          <span className="alert-time">
            {timeFmt.format(new Date(alert.opened_at))}
            {alert.resolved_at ? ` → ${timeFmt.format(new Date(alert.resolved_at))}` : ''}
          </span>
        </div>
        <p className="alert-message">{alert.message}</p>
        {sms ? (
          <p className="alert-sms" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <PhoneIcon size={14} /> {sms}
          </p>
        ) : null}
        <details className="alert-why">
          <summary>Why did this fire?</summary>
          <pre>{JSON.stringify(alert.trigger_data, null, 2)}</pre>
        </details>
      </div>
      {alert.state === 'open' ? (
        <button
          className="btn"
          onClick={() => ack.mutate(alert.id)}
          disabled={ack.isPending}
          aria-label={`Acknowledge ${alert.label} alert`}
        >
          {alert.rule_type === 'help_request' ? 'I’m on my way' : 'Acknowledge'}
        </button>
      ) : null}
    </li>
  )
}

export function AlertsPanel() {
  const { data } = useAlerts()
  const active = data?.filter((a) => a.state !== 'resolved') ?? []
  const history = data?.filter((a) => a.state === 'resolved').slice(0, 8) ?? []
  return (
    <section className="card" aria-labelledby="alerts-h">
      <h2 id="alerts-h">Alerts</h2>
      <p className="section-note">Decided by fixed rules on raw readings. The AI never triggers an alert.</p>
      {active.length === 0 ? (
        <p className="empty">No open alerts.</p>
      ) : (
        <ul className="alert-list">
          {active.map((a) => (
            <AlertRow key={a.id} alert={a} />
          ))}
        </ul>
      )}
      {history.length > 0 ? (
        <>
          <h3>Recent</h3>
          <ul className="alert-list">
            {history.map((a) => (
              <AlertRow key={a.id} alert={a} />
            ))}
          </ul>
        </>
      ) : null}
    </section>
  )
}

export function DemoControls() {
  const { data } = useDemoState()
  const setScenario = useSetScenario()
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
      {setScenario.isError ? <p className="form-error">Couldn’t change the scenario.</p> : null}
    </section>
  )
}
