import { useId, useState } from 'react'

import { useAgentTimeline, type TimelineItem } from '../lib/queries'
import { BellIcon, SparkleIcon } from './Icons'

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })

function Entry({ t, detailed }: { t: TimelineItem; detailed: boolean }) {
  return (
    <li className="timeline-item" data-type={t.type}>
      <span className="timeline-dot" aria-hidden="true">
        {t.type === 'heads_up' ? <BellIcon size={14} /> : <SparkleIcon size={14} />}
      </span>
      <div className="timeline-body">
        <div className="meal-row-meta">
          <time dateTime={t.at}>{timeFmt.format(new Date(t.at))}</time>
          <span>{t.type === 'heads_up' ? `Heads-up sent${t.state === 'resolved' ? ' · seen' : ''}` : 'Asked Alex'}</span>
        </div>
        <p className="timeline-text">{t.type === 'asked' ? `“${t.text}”` : t.text}</p>
        {t.type === 'asked' ? (
          <p className="timeline-answer">
            {t.answer ? (
              <>
                Alex answered: <strong>{t.answer}</strong>
              </>
            ) : (
              'No answer yet'
            )}
          </p>
        ) : null}
        {detailed && t.reasons.length > 0 ? (
          <ul className="reasons" aria-label="Why Scout did this">
            {t.reasons.slice(0, 3).map((r) => (
              <li key={r} className="reason">
                {r}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </li>
  )
}

/**
 * What the Scout agent asked, what the child said, and every heads-up it sent.
 * Minimal by default (the latest entry only); the parent opens the history and reasons.
 */
export function AgentTimeline() {
  const { data } = useAgentTimeline()
  const [open, setOpen] = useState(false)
  const listId = useId()
  const items = data ?? []
  const shown = open ? items : items.slice(0, 1)

  return (
    <section className="card agent-card" aria-labelledby="agent-h">
      <div className="card-head">
        <h2 id="agent-h">Scout agent</h2>
        {items.length > 0 ? (
          <span className="card-head-meta">
            {items.length} {items.length === 1 ? 'entry' : 'entries'}
          </span>
        ) : null}
      </div>
      {open ? (
        <p className="ai-note">
          <SparkleIcon size={16} color="#7766C6" />
          AI picks what to ask and drafts heads-ups. Urgent alerts always come from fixed rules.
        </p>
      ) : null}
      {items.length === 0 ? (
        <p className="empty">Nothing yet. Scout asks questions when the data says they’ll help.</p>
      ) : (
        <>
          <ol className="timeline" id={listId}>
            {shown.map((t, i) => (
              <Entry key={`${t.type}-${t.at}-${i}`} t={t} detailed={open} />
            ))}
          </ol>
          <button
            type="button"
            className="link-button agent-toggle"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? 'Show less' : items.length > 1 ? `Show reasons and history (${items.length - 1} more)` : 'Show reasons'}
          </button>
        </>
      )}
    </section>
  )
}
