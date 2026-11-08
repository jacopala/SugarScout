import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router'

import { HelpButton } from '../../components/HelpButton'
import {
  ForkKnifeIcon,
  HeartIcon,
  KeyboardIcon,
  MegaphoneIcon,
  MicIcon,
  ScoutAvatar,
  SmileIcon,
} from '../../components/Icons'
import { MealSheet } from '../../components/MealSheet'
import type { VoiceTurn } from '../../lib/api'
import { useChildStatus, useSendChat } from '../../lib/queries'
import { useScoutVoice, type VoiceState } from '../../lib/voice/useScoutVoice'

const DOUBLE_TAP_MS = 320

const HINT: Record<VoiceState, string> = {
  off: 'Tap the mic to talk',
  starting: 'Waking up…',
  idle: 'Listening… say “Hey Scout”',
  awake: 'I’m listening…',
  thinking: 'Thinking…',
  speaking: '',
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
  const [caption, setCaption] = useState<Caption>({
    you: null,
    scout: greeting ?? 'Hi! I’m Scout. Tap the mic and talk to me.',
  })
  const [typing, setTyping] = useState(false)
  const [meals, setMeals] = useState(false)
  const [draft, setDraft] = useState('')
  const greeted = useRef(false)
  const tapTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const voice = useScoutVoice((turn: VoiceTurn) => {
    setCaption({ you: turn.transcript, scout: turn.reply })
    if (turn.escalated) void qc.invalidateQueries({ queryKey: ['child', 'status'] })
  })

  // Scout says the mood (or help) reply out loud when the display opens.
  useEffect(() => {
    if (greeting && !greeted.current) {
      greeted.current = true
      void voice.say(greeting, greetingEmotion)
    }
  }, [greeting, greetingEmotion, voice])

  useEffect(
    () => () => {
      if (tapTimer.current) clearTimeout(tapTimer.current)
    },
    [],
  )

  /** One tap: start listening / talk now. Two quick taps: stop listening. */
  function onMic() {
    if (tapTimer.current) {
      clearTimeout(tapTimer.current)
      tapTimer.current = null
      voice.stop()
      return
    }
    tapTimer.current = setTimeout(() => {
      tapTimer.current = null
      voice.wake()
    }, DOUBLE_TAP_MS)
  }

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

  function openMeals() {
    voice.stop() // the meal sheet uses the mic for dictation
    setMeals(true)
  }

  const helpActive = status.data?.reminder_rule === 'help_request'
  const micState: VoiceState = send.isPending ? 'thinking' : voice.state
  const hint = send.isPending ? 'Thinking…' : voice.checking ? 'Hmm…' : HINT[voice.state]

  return (
    <main className="scout-screen">
      <div className="scout-top">
        <div className="child-band-top">
          <span className="scout-name">
            <ScoutAvatar size={40} />
            Scout
          </span>
          <HelpButton
            onSent={(reply) => {
              setCaption({ you: null, scout: reply })
              void voice.say(reply, 'calm')
            }}
          />
        </div>
        {caption.you ? <p className="bubble-you">{caption.you}</p> : null}
        {caption.scout ? (
          <p className="bubble-scout" aria-live="polite">
            {caption.scout}
          </p>
        ) : null}
      </div>

      <section className="scout-sheet" aria-label="Talk to Scout">
        {status.data?.reminder ? (
          <div className="child-reminder" role="status" data-help={helpActive || undefined}>
            {helpActive ? <MegaphoneIcon size={22} /> : <HeartIcon size={22} />}
            <p>{status.data.reminder}</p>
          </div>
        ) : null}

        <div className="mic-zone">
          {voice.supported ? (
            <>
              <div className="mic-halo" data-state={micState}>
                <button
                  className="mic-btn"
                  data-state={micState}
                  onClick={onMic}
                  aria-label={voice.micOn ? 'Talk to Scout. Double-tap to stop listening.' : 'Start talking to Scout'}
                  disabled={voice.state === 'starting'}
                >
                  <MicIcon size={74} strokeWidth={1.9} />
                </button>
              </div>
              <p className="mic-hint" aria-live="polite">
                {hint}
              </p>
              <p className="mic-sub">{voice.micOn ? 'Tap to talk · double-tap to stop' : 'Tap to start'}</p>
            </>
          ) : (
            <p className="section-note">This browser can’t use the microphone here, so you can type to Scout.</p>
          )}
          {voice.error ? (
            <p className="form-error scout-error" role="alert">
              {voice.error}
            </p>
          ) : null}
        </div>

        {typing || !voice.supported ? (
          <form className="scout-type" onSubmit={onType}>
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

        <nav className="scout-pills" aria-label="Scout controls">
          <button className="pill" onClick={() => setTyping((t) => !t)} aria-pressed={typing}>
            <KeyboardIcon size={20} />
            Type
          </button>
          <Link className="pill" to="/child">
            <SmileIcon size={20} />
            Mood
          </Link>
          <button className="pill pill-pink" onClick={openMeals}>
            <ForkKnifeIcon size={20} />
            Meals
          </button>
        </nav>
      </section>

      {meals ? (
        <MealSheet
          onClose={() => setMeals(false)}
          onLogged={(reply) => {
            setMeals(false)
            setCaption({ you: null, scout: reply })
            void voice.say(reply, 'happy')
          }}
        />
      ) : null}
    </main>
  )
}
