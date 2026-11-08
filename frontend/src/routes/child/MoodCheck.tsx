import { Link, useNavigate } from 'react-router'

import { MOODS } from '../../lib/mood'
import { useChildStatus, useCreateCheckin } from '../../lib/queries'

/** The child's landing page: "How are you feeling today?" on a 1-5 scale. */
export function MoodCheck() {
  const status = useChildStatus()
  const create = useCreateCheckin()
  const navigate = useNavigate()
  const name = status.data?.first_name

  function pick(mood: number) {
    if (create.isPending) return
    create.mutate(mood, {
      onSuccess: (data) => navigate('/child/scout', { state: { greeting: data.reply } }),
    })
  }

  return (
    <main className="mood-stage">
      <h1 className="mood-question">
        {name ? `Hi ${name}! ` : ''}How are you feeling today?
      </h1>
      <div className="mood-scale" role="group" aria-label="How are you feeling, from 1 really bad to 5 great">
        {MOODS.map((m) => (
          <button
            key={m.value}
            className="mood-btn"
            data-mood={m.value}
            onClick={() => pick(m.value)}
            disabled={create.isPending}
            aria-label={`${m.value} out of 5: ${m.label}`}
          >
            <span className="mood-face" aria-hidden="true">
              {m.face}
            </span>
            <span className="mood-num" aria-hidden="true">
              {m.value}
            </span>
            <span className="mood-label">{m.label}</span>
          </button>
        ))}
      </div>
      {create.isError ? <p className="form-error">Oops, that didn’t save. Try again?</p> : null}
      <Link className="mood-skip" to="/child/scout">
        Skip for now
      </Link>
    </main>
  )
}
