import { moodInfo } from '../lib/mood'
import { useCheckins } from '../lib/queries'

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })
const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' })

function when(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  const day = same(d, today) ? 'Today' : same(d, yesterday) ? 'Yesterday' : dayFmt.format(d)
  return `${day} ${timeFmt.format(d)}`
}

/** Parent view of the child's "How are you feeling?" answers, newest first. */
export function MoodCard() {
  const { data } = useCheckins(7)
  const items = data ?? []
  const today = items.filter((c) => new Date(c.created_at).toDateString() === new Date().toDateString())
  const avg = today.length ? today.reduce((s, c) => s + c.mood, 0) / today.length : null

  return (
    <section className="card" aria-labelledby="mood-h">
      <h2 id="mood-h">Mood check-ins</h2>
      <p className="section-note">
        {today.length === 0
          ? 'No check-ins today yet.'
          : `Today: ${today.length} check-in${today.length === 1 ? '' : 's'}, average ${avg?.toFixed(1)} of 5.`}{' '}
        Moods never trigger alerts.
      </p>
      {items.length === 0 ? null : (
        <ul className="mood-list">
          {items.slice(0, 12).map((c) => {
            const m = moodInfo(c.mood)
            return (
              <li key={c.id} className="mood-row" data-low={c.mood <= 2 || undefined}>
                <span className="mood-row-face" aria-hidden="true">
                  {m.face}
                </span>
                <span className="mood-row-label">
                  <strong>{c.mood}/5</strong> {m.label}
                </span>
                <time className="mood-row-time" dateTime={c.created_at}>
                  {when(c.created_at)}
                </time>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
