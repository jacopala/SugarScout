import { useAgentTimeline } from '../lib/queries'
import { BellIcon, SparkleIcon } from './Icons'

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })

/** What the Scout agent asked, what the child said, and every heads-up it sent, with reasons. */
export function AgentTimeline() {
  const { data } = useAgentTimeline()
  const items = data ?? []
  return (
    <section className="card" aria-labelledby="agent-h">
      <h2 id="agent-h">Scout agent</h2>
      <p className="ai-note">
        <SparkleIcon size={16} color="#7766C6" />
        AI picks what to ask and drafts heads-ups. Urgent alerts always come from fixed rules.
      </p>
      {items.length === 0 ? (
        <p className="empty">Nothing yet. Scout asks questions when the data says they’ll help.</p>
      ) : (
        <ol className="timeline">
          {items.map((t, i) => (
            <li key={`${t.type}-${t.at}-${i}`} className="timeline-item" data-type={t.type}>
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
                {t.reasons.length > 0 ? (
                  <div className="tags">
                    {t.reasons.slice(0, 3).map((r) => (
                      <span key={r} className="tag">
                        {r}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
