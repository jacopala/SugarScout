import type { AgentQuestion } from '../lib/queries'
import { MoodFace } from './MoodFace'
import { SparkleIcon } from './Icons'

/** A question Scout is asking the child, with big answer buttons (they can also say it). */
export function QuestionCard({
  question,
  onAnswer,
  busy,
}: {
  question: AgentQuestion
  onAnswer: (value: string) => void
  busy: boolean
}) {
  const mood = question.kind === 'mood'
  return (
    <section className="question-card" aria-labelledby="q-text" aria-live="polite">
      <p className="question-eyebrow">
        <SparkleIcon size={16} /> Scout is asking
      </p>
      <h2 id="q-text" className="question-text">
        {question.wording}
      </h2>
      <div className={mood ? 'question-moods' : 'question-options'} role="group" aria-label="Answers">
        {question.options.map((o) => (
          <button
            key={o.value}
            className={mood ? 'mood-bar-item question-mood' : 'question-option'}
            onClick={() => onAnswer(o.value)}
            disabled={busy}
            aria-label={mood ? o.label : undefined}
          >
            {mood ? <MoodFace mood={Number(o.value)} size={44} /> : o.label}
          </button>
        ))}
      </div>
      <p className="question-hint">Tap an answer, or just say it.</p>
    </section>
  )
}
