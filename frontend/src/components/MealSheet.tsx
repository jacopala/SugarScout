import { useEffect, useState, type FormEvent } from 'react'

import { useLogMeal } from '../lib/queries'
import { useDictation } from '../lib/voice/useDictation'
import { CloseIcon, FoodIcon, MicIcon } from './Icons'

const FOODS = [
  { id: 'apple', label: 'Apple' },
  { id: 'sandwich', label: 'Sandwich' },
  { id: 'juice', label: 'Juice' },
  { id: 'pasta', label: 'Pasta' },
  { id: 'cookie', label: 'Cookie' },
  { id: 'cereal', label: 'Cereal' },
]

/**
 * "What did you eat?" The child says it, taps foods, or types. The meal is saved and
 * the AI estimate (sugar, gluten) is made for the parent only; the child just hears a
 * friendly thank-you, never numbers.
 */
export function MealSheet({ onClose, onLogged }: { onClose: () => void; onLogged: (reply: string) => void }) {
  const [picked, setPicked] = useState<string[]>([])
  const [text, setText] = useState('')
  const [source, setSource] = useState<'voice' | 'tap' | 'text'>('text')
  const dictation = useDictation()
  const log = useLogMeal()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function toggle(label: string) {
    setPicked((p) => (p.includes(label) ? p.filter((x) => x !== label) : [...p, label]))
    if (!text) setSource('tap')
  }

  async function say() {
    if (dictation.recording) {
      dictation.stop()
      return
    }
    const heard = await dictation.listen()
    if (heard) {
      setText(heard)
      setSource('voice')
    }
  }

  const description = [text.trim(), ...picked.map((p) => p.toLowerCase())].filter(Boolean).join(', ')

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!description || log.isPending) return
    log.mutate({ description, source: text.trim() ? source : 'tap' }, { onSuccess: (data) => onLogged(data.reply) })
  }

  return (
    <div className="overlay" data-kind="sheet" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <form className="sheet" role="dialog" aria-modal="true" aria-labelledby="meal-title" onSubmit={submit}>
        <span className="sheet-handle" aria-hidden="true" />
        <div className="sheet-head">
          <h2 id="meal-title">What did you eat?</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
            <CloseIcon size={22} />
          </button>
        </div>

        <div className="dictate">
          <button
            type="button"
            className="dictate-btn"
            onClick={() => void say()}
            data-recording={dictation.recording || undefined}
            aria-label={dictation.recording ? 'Stop listening' : 'Say what you ate'}
            disabled={dictation.busy}
          >
            <MicIcon size={30} />
          </button>
          <p aria-live="polite">
            {dictation.recording
              ? 'Listening… tell Scout what you ate.'
              : dictation.busy
                ? 'Got it, one sec…'
                : (dictation.error ?? 'Say it, like “a turkey sandwich and apple juice”.')}
          </p>
        </div>

        <span className="sheet-label">Or tap</span>
        <div className="food-grid" role="group" aria-label="Quick foods">
          {FOODS.map((f) => (
            <button
              key={f.id}
              type="button"
              className="food-chip"
              aria-pressed={picked.includes(f.label)}
              onClick={() => toggle(f.label)}
            >
              <FoodIcon kind={f.id} />
              {f.label}
            </button>
          ))}
        </div>

        <label className="sheet-label" htmlFor="meal-text">
          Or type it
        </label>
        <input
          id="meal-text"
          type="text"
          value={text}
          maxLength={200}
          placeholder="turkey sandwich, apple juice"
          onChange={(e) => {
            setText(e.target.value)
            setSource('text')
          }}
          autoComplete="off"
        />

        {log.isError ? <p className="form-error">That didn’t save. Try again?</p> : null}
        <button className="btn btn-primary btn-block" type="submit" disabled={!description || log.isPending}>
          {log.isPending ? 'Telling Scout…' : 'Tell Scout'}
        </button>
      </form>
    </div>
  )
}
