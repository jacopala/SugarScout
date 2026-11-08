import { useHelp } from '../lib/queries'
import { MegaphoneIcon, PhoneIcon } from './Icons'

/** What the API says when a child's words (or the sad face) carry enough concern. */
export interface ConcernOffer {
  concern_level?: string
  suggest_call?: boolean
  guardian_phone?: string | null
}

/**
 * Shown when Scout suggests calling a grown-up. "Call" opens the phone's dialer
 * with the parent's number; "Ask for help" sends the same alert as the Help button.
 * The child can always say they're okay.
 */
export function CallGrownUp({
  phone,
  onHelpSent,
  onDismiss,
}: {
  phone: string | null | undefined
  onHelpSent: (reply: string) => void
  onDismiss: () => void
}) {
  const help = useHelp()
  return (
    <div className="call-card" role="region" aria-labelledby="call-title">
      <p id="call-title" className="call-title">
        Want to talk to your grown-up?
      </p>
      <div className="call-actions">
        {phone ? (
          <a className="btn btn-call btn-block" href={`tel:${phone}`}>
            <PhoneIcon size={22} />
            Call my grown-up
          </a>
        ) : null}
        <button
          type="button"
          className={phone ? 'btn btn-block' : 'btn btn-call btn-block'}
          onClick={() => help.mutate(undefined, { onSuccess: (d) => onHelpSent(d.reply) })}
          disabled={help.isPending || help.isSuccess}
        >
          <MegaphoneIcon size={20} />
          {help.isSuccess ? 'Message sent' : help.isPending ? 'Sending…' : 'Ask them to come'}
        </button>
      </div>
      {help.isError ? (
        <p className="form-error" role="alert">
          That didn’t send. Please go find a grown-up.
        </p>
      ) : null}
      <button type="button" className="link-btn" onClick={onDismiss}>
        I’m okay
      </button>
    </div>
  )
}
