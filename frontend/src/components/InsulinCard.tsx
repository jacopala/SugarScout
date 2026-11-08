import { useState, type FormEvent } from 'react'

import { useDoses, useLogDose, type Dose } from '../lib/queries'

const KINDS: { id: Dose['kind']; label: string }[] = [
  { id: 'meal', label: 'With a meal' },
  { id: 'correction', label: 'Correction' },
  { id: 'long_acting', label: 'Long-acting' },
]
const KIND_LABEL: Record<Dose['kind'], string> = {
  meal: 'With a meal',
  correction: 'Correction',
  long_acting: 'Long-acting',
  unknown: 'Insulin',
}
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })

/** Parent's insulin log. Record-only: SugarScout never calculates or suggests a dose. */
export function InsulinCard() {
  const { data } = useDoses()
  const log = useLogDose()
  const [kind, setKind] = useState<Dose['kind']>('meal')
  const [units, setUnits] = useState('')
  const [minutesAgo, setMinutesAgo] = useState(0)

  function submit(e: FormEvent) {
    e.preventDefault()
    const u = units.trim() ? Number(units) : undefined
    if (u !== undefined && (!Number.isFinite(u) || u <= 0 || u > 100)) return
    log.mutate(
      {
        kind,
        units: u,
        given_at: minutesAgo ? new Date(Date.now() - minutesAgo * 60_000).toISOString() : undefined,
      },
      { onSuccess: () => setUnits('') },
    )
  }

  return (
    <section className="card" aria-labelledby="insulin-h">
      <h2 id="insulin-h">Insulin</h2>
      <p className="section-note">Record what was given. SugarScout never calculates or suggests doses.</p>
      <form className="insulin-form" onSubmit={submit}>
        <div className="seg" role="group" aria-label="Kind of dose">
          {KINDS.map((k) => (
            <button key={k.id} type="button" className="seg-btn" aria-pressed={kind === k.id} onClick={() => setKind(k.id)}>
              {k.label}
            </button>
          ))}
        </div>
        <div className="insulin-row">
          <label className="field">
            <span>Units (optional)</span>
            <input type="text" inputMode="decimal" value={units} onChange={(e) => setUnits(e.target.value)} placeholder="e.g. 3.5" />
          </label>
          <label className="field">
            <span>When</span>
            <select value={minutesAgo} onChange={(e) => setMinutesAgo(Number(e.target.value))}>
              <option value={0}>Just now</option>
              <option value={15}>15 min ago</option>
              <option value={30}>30 min ago</option>
              <option value={60}>1 hour ago</option>
            </select>
          </label>
        </div>
        {log.isError ? <p className="form-error">That didn’t save. Check the units and try again.</p> : null}
        <button className="btn btn-primary" type="submit" disabled={log.isPending}>
          {log.isPending ? 'Saving…' : 'Log insulin'}
        </button>
      </form>
      {data && data.length > 0 ? (
        <ul className="meal-list" style={{ marginTop: 12 }}>
          {data.slice(0, 6).map((d) => (
            <li key={d.id} className="meal-row">
              <div className="meal-row-meta">
                <time dateTime={d.given_at}>{timeFmt.format(new Date(d.given_at))}</time>
                <span>{d.source === 'parent' ? 'logged by you' : 'reported by your child'}</span>
              </div>
              <span className="meal-row-desc">
                {KIND_LABEL[d.kind]}
                {d.units ? ` · ${Number(d.units)} units` : ''}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
