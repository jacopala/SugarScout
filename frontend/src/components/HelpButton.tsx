import { useEffect, useRef, useState } from 'react'

import { useHelp } from '../lib/queries'
import { CheckIcon, MegaphoneIcon } from './Icons'

/**
 * The child's red Help button. Tap opens a confirmation; "Yes, get help" sends an
 * urgent dashboard alert and a text to the parent (deterministic, no AI involved).
 */
export function HelpButton({ onSent }: { onSent?: (reply: string) => void }) {
  const [open, setOpen] = useState(false)
  const help = useHelp()
  const yesRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    yesRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  function confirm() {
    help.mutate(undefined, { onSuccess: (data) => onSent?.(data.reply) })
  }

  function close() {
    setOpen(false)
    help.reset()
  }

  return (
    <>
      <button className="help-btn" onClick={() => setOpen(true)} aria-haspopup="dialog">
        <MegaphoneIcon size={22} />
        Help
      </button>
      {open ? (
        <div className="overlay" onClick={(e) => e.target === e.currentTarget && close()}>
          <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="help-title">
            {help.isSuccess ? (
              <>
                <span className="dialog-icon" data-done="">
                  <span>
                    <CheckIcon size={36} />
                  </span>
                </span>
                <h2 id="help-title">Your grown-up is on the way</h2>
                <p>{help.data.reply}</p>
                <button className="btn btn-primary btn-block" onClick={close} ref={yesRef}>
                  Okay
                </button>
              </>
            ) : (
              <>
                <span className="dialog-icon">
                  <span>
                    <MegaphoneIcon size={36} />
                  </span>
                </span>
                <h2 id="help-title">Tell your grown-up you need help?</h2>
                <p>Scout will send them a message right away.</p>
                <button
                  className="btn btn-danger btn-block"
                  onClick={confirm}
                  disabled={help.isPending}
                  ref={yesRef}
                >
                  {help.isPending ? 'Sending…' : 'Yes, get help'}
                </button>
                {help.isError ? (
                  <p className="form-error" role="alert">
                    That didn’t send. Try again, or go find a grown-up.
                  </p>
                ) : null}
                <button className="link-btn" onClick={close}>
                  Not now
                </button>
              </>
            )}
          </div>
        </div>
      ) : null}
    </>
  )
}
