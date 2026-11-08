import { useState } from 'react'

import { MOODS, moodInfo } from '../lib/mood'
import { useCheckins, type Checkin } from '../lib/queries'
import { MoodFace } from './MoodFace'

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })
const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
const RIBBON_MAX = 10

function when(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  const day = same(d, today) ? 'Today' : same(d, yesterday) ? 'Yesterday' : dayFmt.format(d)
  return `${day} ${timeFmt.format(d)}`
}

const CONTEXT_LABEL: Record<string, string> = {
  daily: 'daily check-in',
  after_meal: 'after a meal',
  agent: 'asked by Scout',
}

const avgOf = (xs: Checkin[]) => (xs.length ? xs.reduce((s, c) => s + c.mood, 0) / xs.length : null)

/** Parent view of the child's moods: a summary first, the full list on request. */
export function MoodCard() {
  const { data } = useCheckins(7)
  const [showAll, setShowAll] = useState(false)
  const items = data ?? [] // newest first
  const todayStr = new Date().toDateString()
  const today = items.filter((c) => new Date(c.created_at).toDateString() === todayStr)
  const avg = avgOf(today)
  const lowToday = today.filter((c) => c.mood <= 2).length
  const afterMeal = items.filter((c) => c.context === 'after_meal')
  const afterMealAvg = avgOf(afterMeal)
  const latest = items[0]
  const ribbon = today.slice(0, RIBBON_MAX).reverse() // oldest → newest
  const counts = MOODS.map((m) => ({ ...m, n: items.filter((c) => c.mood === m.value).length }))
  const maxCount = Math.max(1, ...counts.map((c) => c.n))

  return (
    <section className="card" aria-labelledby="mood-h">
      <h2 id="mood-h">Mood check-ins</h2>
      <p className="section-note">
        {today.length === 0
          ? 'No check-ins today yet.'
          : `Today: ${today.length} check-in${today.length === 1 ? '' : 's'}, average ${avg?.toFixed(1)} of 5.`}{' '}
        Moods never trigger alerts.
      </p>

      {latest ? (
        <>
          <div className="mood-latest" data-low={latest.mood <= 2 || undefined}>
            <MoodFace mood={latest.mood} size={52} />
            <div>
              <p className="mood-latest-eyebrow">Latest</p>
              <p className="mood-latest-label">
                <strong>{moodInfo(latest.mood).label}</strong> · {latest.mood}/5
              </p>
              <p className="mood-latest-meta">
                <time dateTime={latest.created_at}>{when(latest.created_at)}</time>
                {latest.context && latest.context !== 'daily' ? ` · ${CONTEXT_LABEL[latest.context]}` : ''}
              </p>
            </div>
          </div>

          {ribbon.length > 1 ? (
            <div className="mood-ribbon-wrap">
              <p className="sheet-label">Today, in order</p>
              <ol className="mood-ribbon" aria-label="Today's moods, oldest first">
                {today.length > RIBBON_MAX ? (
                  <li className="mood-ribbon-more">+{today.length - RIBBON_MAX}</li>
                ) : null}
                {ribbon.map((c) => (
                  <li key={c.id} title={`${moodInfo(c.mood).label} · ${timeFmt.format(new Date(c.created_at))}`}>
                    <MoodFace mood={c.mood} size={26} />
                    <span className="visually-hidden">
                      {moodInfo(c.mood).label} at {timeFmt.format(new Date(c.created_at))}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}

          <div className="mood-dist" aria-label="Moods over the last 7 days">
            <p className="sheet-label">Last 7 days</p>
            <ul>
              {counts.map((c) => (
                <li key={c.value} data-empty={c.n === 0 || undefined}>
                  <MoodFace mood={c.value} size={24} />
                  <span className="mood-dist-bar" aria-hidden="true">
                    <span style={{ width: `${(c.n / maxCount) * 100}%` }} />
                  </span>
                  <span className="mood-dist-n">
                    {c.n}
                    <span className="visually-hidden"> {c.label}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <p className="mood-facts">
            {lowToday > 0 ? (
              <span className="status-chip" data-tone="warn">
                {lowToday} low mood{lowToday === 1 ? '' : 's'} today
              </span>
            ) : null}
            {afterMealAvg !== null ? (
              <span className="status-chip" data-tone="muted">
                After meals: avg {afterMealAvg.toFixed(1)} ({afterMeal.length})
              </span>
            ) : null}
          </p>

          <button className="link-btn" aria-expanded={showAll} onClick={() => setShowAll((s) => !s)}>
            {showAll ? 'Hide the list' : `Show all ${items.length} check-in${items.length === 1 ? '' : 's'}`}
          </button>
          {showAll ? (
            <ul className="mood-list">
              {items.map((c) => (
                <li key={c.id} className="mood-row" data-low={c.mood <= 2 || undefined}>
                  <span className="mood-row-face" aria-hidden="true">
                    <MoodFace mood={c.mood} size={30} />
                  </span>
                  <span className="mood-row-label">
                    <strong>{c.mood}/5</strong> {moodInfo(c.mood).label}
                  </span>
                  <time className="mood-row-time" dateTime={c.created_at}>
                    {when(c.created_at)}
                  </time>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </section>
  )
}
