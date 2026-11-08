import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { Fireworks } from '../../components/Fireworks'
import { HelpButton } from '../../components/HelpButton'
import { MoodFace } from '../../components/MoodFace'
import { MOODS, moodInfo } from '../../lib/mood'
import { useChildStatus, useCreateCheckin } from '../../lib/queries'

const dayPart = () => {
  const h = new Date().getHours()
  const day = new Date().toLocaleDateString(undefined, { weekday: 'long' })
  return `${day} ${h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening'}`
}

/** Peaceful (4) and Happy (5) get fireworks; the other faces never do. */
const HAPPY_FROM = 4

/** The child's landing page: pick a face on the mood bar, then "That's me". */
export function MoodCheck() {
  const status = useChildStatus()
  const create = useCreateCheckin()
  const navigate = useNavigate()
  const [mood, setMood] = useState<number | null>(null)
  // Each happy tap restarts the show (a new key remounts the canvas).
  const [show, setShow] = useState(0)
  const name = status.data?.first_name

  function confirm() {
    if (mood === null || create.isPending) return
    create.mutate(mood, {
      onSuccess: (data) =>
        navigate('/child/scout', {
          state: {
            greeting: data.reply,
            emotion: data.emotion,
            callOffer: data.suggest_call ? { phone: data.guardian_phone ?? null } : null,
          },
        }),
    })
  }

  return (
    <main className="mood-page">
      <header className="child-band">
        <div className="child-band-top">
          <span className="child-chip">{dayPart()}</span>
          <HelpButton
            onSent={(reply) => navigate('/child/scout', { state: { greeting: reply, emotion: 'calm' } })}
          />
        </div>
        <p className="child-hello">{name ? `Hi ${name}!` : 'Hi!'}</p>
        <h1 className="child-question">How are you feeling today?</h1>
      </header>

      <div className="mood-body">
        <div className="mood-hero" aria-live="polite">
          <span className="mood-hero-face">
            {mood === null ? (
              <span style={{ opacity: 0.35, lineHeight: 0 }}>
                <MoodFace mood={3} size={138} />
              </span>
            ) : (
              <MoodFace mood={mood} size={138} />
            )}
          </span>
          <span className="mood-hero-label">{mood === null ? 'Tap a face' : moodInfo(mood).label}</span>
        </div>

        <div className="mood-bar" role="group" aria-label="How are you feeling, from 1 sad to 5 happy">
          {MOODS.map((m) => (
            <button
              key={m.value}
              className="mood-bar-item"
              aria-pressed={mood === m.value}
              aria-label={`${m.value} out of 5: ${m.label}`}
              onClick={() => {
                setMood(m.value)
                if (m.value >= HAPPY_FROM) setShow((n) => n + 1)
              }}
            >
              <MoodFace mood={m.value} size={44} />
            </button>
          ))}
        </div>
        <div className="mood-bar-ends" aria-hidden="true">
          <span>Sad</span>
          <span>Happy</span>
        </div>

        {create.isError ? <p className="form-error">Oops, that didn’t save. Try again?</p> : null}
        <div className="mood-actions">
          <button className="btn btn-primary btn-block" onClick={confirm} disabled={mood === null || create.isPending}>
            {create.isPending ? 'Saving…' : 'That’s me'}
          </button>
          <Link className="mood-skip" to="/child/scout">
            Skip for now
          </Link>
        </div>
      </div>
      {show > 0 ? <Fireworks key={show} onDone={() => setShow(0)} /> : null}
    </main>
  )
}
