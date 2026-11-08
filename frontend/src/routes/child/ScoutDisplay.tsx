import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router'

import type { VoiceTurn } from '../../lib/api'
import { useChildStatus, useSendChat } from '../../lib/queries'
import { useScoutVoice, type VoiceState } from '../../lib/voice/useScoutVoice'

const HINT: Record<VoiceState, string> = {
  off: 'Tap “Start listening” so Scout can hear you',
  starting: 'Waking up…',
  idle: 'Say “Hey Scout”',
  awake: 'I’m listening…',
  thinking: 'Thinking…',
  speaking: '',
}

function Character({ state, onTap }: { state: VoiceState; onTap: () => void }) {
  return (
    <button
      className="scout-character"
      data-state={state}
      onClick={onTap}
      aria-label="Scout. Tap to talk without saying Hey Scout."
    >
      <svg viewBox="0 0 160 160" aria-hidden="true">
        <circle className="ring" cx="80" cy="80" r="74" />
        <circle className="glow" cx="80" cy="80" r="64" />
        <circle className="body" cx="80" cy="80" r="54" />
        <g className="eyes">
          <circle cx="61" cy="72" r="7" />
          <circle cx="99" cy="72" r="7" />
        </g>
        <path className="mouth smile" d="M58 96c6 7 13.5 10.5 22 10.5s16-3.5 22-10.5" />
        <ellipse className="mouth talk" cx="80" cy="101" rx="11" ry="8" />
      </svg>
    </button>
  )
}

interface Caption {
  you: string | null
  scout: string | null
}

export function ScoutDisplay() {
  const location = useLocation()
  const nav = location.state as { greeting?: string; emotion?: string } | null
  const greeting = nav?.greeting ?? null
  const greetingEmotion = nav?.emotion ?? 'neutral'
  const qc = useQueryClient()
  const status = useChildStatus()
  const send = useSendChat()
  const [caption, setCaption] = useState<Caption>({ you: null, scout: greeting })
  const [typing, setTyping] = useState(false)
  const [draft, setDraft] = useState('')
  const greeted = useRef(false)

  const voice = useScoutVoice((turn: VoiceTurn) => {
    setCaption({ you: turn.transcript, scout: turn.reply })
    if (turn.escalated) void qc.invalidateQueries({ queryKey: ['child', 'status'] })
  })

  // Scout says the mood reply out loud when the display opens.
  useEffect(() => {
    if (greeting && !greeted.current) {
      greeted.current = true
      void voice.say(greeting, greetingEmotion)
    }
  }, [greeting, greetingEmotion, voice])

  const showText = typing || !voice.supported

  function onType(e: FormEvent) {
    e.preventDefault()
    const message = draft.trim()
    if (!message || send.isPending) return
    setDraft('')
    setCaption({ you: message, scout: null })
    send.mutate(message, {
      onSuccess: (data) => {
        setCaption({ you: message, scout: data.reply })
        void voice.say(data.reply, data.emotion)
      },
    })
  }

  const hint = send.isPending ? 'Thinking…' : voice.checking ? 'Hmm…' : HINT[voice.state]

  return (
    <main className="scout-display">
      {status.data?.reminder ? (
        <div className="child-reminder" role="status" aria-live="polite">
          <span aria-hidden="true">💜</span>
          <p>{status.data.reminder}</p>
        </div>
      ) : null}

      <div className="scout-center">
        <Character state={send.isPending ? 'thinking' : voice.state} onTap={voice.wake} />
        <p className="scout-hint" aria-live="polite">
          {hint}
        </p>
      </div>

      <section className="scout-captions" aria-live="polite" aria-label="Conversation">
        {caption.you ? <p className="caption you">“{caption.you}”</p> : null}
        {caption.scout ? <p className="caption scout">{caption.scout}</p> : null}
      </section>

      {voice.error ? (
        <p className="form-error scout-error" role="alert">
          {voice.error}
        </p>
      ) : null}
      {!voice.supported ? (
        <p className="section-note">This browser can’t use the microphone here, so you can type to Scout.</p>
      ) : null}

      {showText ? (
        <form className="chat-input" onSubmit={onType}>
          <label htmlFor="scout-msg" className="visually-hidden">
            Message Scout
          </label>
          <input
            id="scout-msg"
            type="text"
            placeholder="Type to Scout…"
            value={draft}
            maxLength={500}
            onChange={(e) => setDraft(e.target.value)}
            autoComplete="off"
          />
          <button className="btn btn-primary" type="submit" disabled={send.isPending || !draft.trim()}>
            Send
          </button>
        </form>
      ) : null}

      <nav className="scout-controls" aria-label="Scout controls">
        {voice.supported ? (
          !voice.micOn ? (
            <button className="btn btn-primary" onClick={() => void voice.start()} disabled={voice.state === 'starting'}>
              🎤 Start listening
            </button>
          ) : (
            <button className="btn" onClick={voice.stop}>
              ⏸ Stop listening
            </button>
          )
        ) : null}
        {voice.supported ? (
          <button className="btn" onClick={() => setTyping((t) => !t)} aria-pressed={typing}>
            ⌨️ {typing ? 'Hide keyboard' : 'Type instead'}
          </button>
        ) : null}
        <Link className="btn" to="/child">
          😊 How I feel
        </Link>
      </nav>
    </main>
  )
}
