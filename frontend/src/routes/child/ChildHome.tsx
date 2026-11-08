import { useEffect, useRef, useState, type FormEvent } from 'react'

import { AccessGate } from '../../components/AccessGate'
import { useChatHistory, useChildStatus, useSendChat } from '../../lib/queries'

const QUICK_REPLIES = ['I feel fine', 'I feel shaky', 'I had a snack', 'Tell me a joke']

function Companion({ talking }: { talking: boolean }) {
  return (
    <svg className="companion" viewBox="0 0 120 120" role="img" aria-label="Your companion">
      <circle cx="60" cy="62" r="50" fill="var(--view-accent)" opacity="0.18" />
      <circle cx="60" cy="62" r="40" fill="var(--view-accent)" />
      <circle cx="46" cy="56" r="5" fill="#fff" />
      <circle cx="74" cy="56" r="5" fill="#fff" />
      {talking ? (
        <ellipse cx="60" cy="77" rx="9" ry="6" fill="#fff" />
      ) : (
        <path
          d="M44 74c4.5 5 9.8 7.5 16 7.5s11.5-2.5 16-7.5"
          stroke="#fff"
          strokeWidth="5"
          fill="none"
          strokeLinecap="round"
        />
      )}
    </svg>
  )
}

export function ChildHome() {
  return (
    <AccessGate>
      <ChildChat />
    </AccessGate>
  )
}

function ChildChat() {
  const status = useChildStatus()
  const history = useChatHistory()
  const send = useSendChat()
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const name = status.data?.first_name ?? 'friend'
  const messages = history.data ?? []

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' })
  }, [messages.length, pending])

  function submit(text: string) {
    const message = text.trim()
    if (!message || send.isPending) return
    setPending(message)
    setDraft('')
    send.mutate(message, { onSettled: () => setPending(null) })
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    submit(draft)
  }

  return (
    <main className="child-app">
      <header className="child-top">
        <Companion talking={send.isPending} />
        <div>
          <p className="child-greeting">Hi {name}!</p>
          <p className="child-sub">I’m Scout. I’m here to keep you company.</p>
        </div>
      </header>

      {status.data?.reminder ? (
        <div className="child-reminder" role="status" aria-live="polite">
          <span aria-hidden="true">💜</span>
          <p>{status.data.reminder}</p>
        </div>
      ) : null}

      <section className="chat-thread" aria-label="Chat with Scout" aria-live="polite">
        {messages.length === 0 && !pending ? (
          <p className="chat-bubble companion">How are you feeling today?</p>
        ) : null}
        {messages.map((m) => (
          <p key={m.id} className={`chat-bubble ${m.role}`}>
            {m.content}
          </p>
        ))}
        {pending ? (
          <>
            <p className="chat-bubble child">{pending}</p>
            <p className="chat-bubble companion typing" aria-label="Scout is typing">
              <span />
              <span />
              <span />
            </p>
          </>
        ) : null}
        {send.isError ? (
          <p className="chat-bubble companion">Oops, I couldn’t hear that. Can you try again?</p>
        ) : null}
        <div ref={endRef} />
      </section>

      <div className="child-footer">
      <div className="quick-replies" role="group" aria-label="Quick replies">
        {QUICK_REPLIES.map((q) => (
          <button key={q} className="btn chip" onClick={() => submit(q)} disabled={send.isPending}>
            {q}
          </button>
        ))}
      </div>

      <form className="chat-input" onSubmit={onSubmit}>
        <label htmlFor="chat-msg" className="visually-hidden">
          Message Scout
        </label>
        <input
          id="chat-msg"
          type="text"
          placeholder="Type a message…"
          value={draft}
          maxLength={500}
          onChange={(e) => setDraft(e.target.value)}
          autoComplete="off"
        />
        <button className="btn btn-primary" type="submit" disabled={send.isPending || !draft.trim()}>
          Send
        </button>
      </form>
      </div>
    </main>
  )
}
