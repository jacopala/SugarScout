import { useEffect, useRef, useState } from 'react'

import { alertWhy } from '../lib/alertWhy'
import type { AlertOut, NotificationOut } from '../lib/api'
import { useAckAlert, useAlerts, useDismissAlert, useMarkAlertsRead } from '../lib/queries'
import { AlertIcon, BellIcon, CheckIcon, CloseIcon, PhoneIcon, TrashIcon } from './Icons'

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })

const SMS_STATUS: Record<NotificationOut['status'], string> = {
  queued: 'sending…',
  sent: 'sent',
  dry_run: 'dry run',
  skipped: 'skipped (cooldown)',
  failed: 'failed',
}

/** One line on how the parent was told: push and text, for the alert opening. */
function delivery(notifications: NotificationOut[]): string | null {
  const parts: string[] = []
  const push = notifications.find((n) => n.channel === 'push' && n.kind === 'opened')
  const sms = notifications.find((n) => n.channel === 'sms' && n.kind === 'opened')
  if (push) parts.push(`Push ${SMS_STATUS[push.status]}`)
  if (sms) parts.push(`Text ${SMS_STATUS[sms.status]}${sms.status === 'failed' && sms.error ? `: ${sms.error}` : ''}`)
  return parts.length ? parts.join(' · ') : null
}

/** The bell in the parent header: red and ringing while there are unread alerts. */
export function AlertsBell({ onOpen }: { onOpen: () => void }) {
  const { data } = useAlerts()
  const unread = (data ?? []).filter((a) => a.read_at === null).length
  return (
    <button
      className="bell-btn"
      data-unread={unread > 0 || undefined}
      onClick={onOpen}
      aria-label={unread > 0 ? `Alerts: ${unread} unread` : 'Alerts'}
      aria-haspopup="dialog"
    >
      <span className="bell-icon">
        <BellIcon size={22} />
      </span>
      {unread > 0 ? <span className="bell-badge">{unread > 99 ? '99+' : unread}</span> : null}
    </button>
  )
}

function InboxRow({ alert, isNew }: { alert: AlertOut; isNew: boolean }) {
  const ack = useAckAlert()
  const dismiss = useDismissAlert()
  const tone = alert.state === 'resolved' ? 'muted' : alert.severity === 'urgent' ? 'bad' : 'warn'
  const why = alertWhy(alert)
  const told = delivery(alert.notifications)
  const canDelete = alert.read_at !== null && alert.state !== 'open'
  return (
    <li className="alert-row" data-tone={tone}>
      <div className="alert-main">
        <div className="alert-title">
          {isNew ? <span className="new-dot" aria-label="New" /> : null}
          <span className="status-chip" data-tone={tone}>
            {alert.state === 'open' ? <AlertIcon size={14} strokeWidth={2.6} /> : <CheckIcon size={14} strokeWidth={2.6} />}
            {alert.state === 'resolved' ? 'Cleared' : alert.state === 'acknowledged' ? 'Seen' : 'Open'}
          </span>
          <strong>{alert.label}</strong>
          <span className="alert-time">
            {timeFmt.format(new Date(alert.opened_at))}
            {alert.resolved_at ? ` → ${timeFmt.format(new Date(alert.resolved_at))}` : ''}
          </span>
        </div>
        <p className="alert-message">{alert.message}</p>
        {why.length > 0 ? (
          <details className="alert-why">
            <summary>Why did this fire?</summary>
            <ul className="why-list">
              {why.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </details>
        ) : null}
        {told ? (
          <p className="alert-sms">
            <PhoneIcon size={14} /> {told}
          </p>
        ) : null}
      </div>
      <div className="alert-actions">
        {alert.state === 'open' ? (
          <button className="btn" onClick={() => ack.mutate(alert.id)} disabled={ack.isPending} aria-label={`Acknowledge ${alert.label} alert`}>
            {alert.rule_type === 'help_request' ? 'I’m on my way' : 'Acknowledge'}
          </button>
        ) : null}
        {canDelete ? (
          <button
            className="icon-btn"
            onClick={() => dismiss.mutate(alert.id)}
            disabled={dismiss.isPending}
            aria-label={`Delete ${alert.label} alert`}
            title="Delete"
          >
            <TrashIcon size={18} />
          </button>
        ) : null}
      </div>
    </li>
  )
}

/** Alerts pop-up. Opening it marks everything shown as read; read alerts can be deleted. */
export function AlertsPopup({ onClose }: { onClose: () => void }) {
  const { data } = useAlerts()
  const markRead = useMarkAlertsRead()
  const closeRef = useRef<HTMLButtonElement>(null)
  // Remember which were unread when the pop-up opened, so they still show as new.
  const [newIds] = useState<Set<number>>(() => new Set((data ?? []).filter((a) => a.read_at === null).map((a) => a.id)))

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const unreadIds = (data ?? []).filter((a) => a.read_at === null).map((a) => a.id)
  const unreadKey = unreadIds.join(',')
  useEffect(() => {
    if (unreadKey) markRead.mutate(unreadKey.split(',').map(Number))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mark each new batch once
  }, [unreadKey])

  const alerts = data ?? []
  const active = alerts.filter((a) => a.state !== 'resolved')
  const earlier = alerts.filter((a) => a.state === 'resolved')

  return (
    <div className="overlay" data-kind="sheet" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet inbox" role="dialog" aria-modal="true" aria-labelledby="inbox-h">
        <span className="sheet-handle" aria-hidden="true" />
        <div className="sheet-head">
          <h2 id="inbox-h">Alerts</h2>
          <button ref={closeRef} className="icon-btn" onClick={onClose} aria-label="Close alerts">
            <CloseIcon size={22} />
          </button>
        </div>
        <p className="section-note">Decided by fixed rules on raw readings. The AI never triggers an urgent alert.</p>
        {alerts.length === 0 ? <p className="empty">No alerts. All quiet.</p> : null}
        {active.length > 0 ? (
          <>
            <h3 className="inbox-group">Needs attention</h3>
            <ul className="alert-list">
              {active.map((a) => (
                <InboxRow key={a.id} alert={a} isNew={newIds.has(a.id)} />
              ))}
            </ul>
          </>
        ) : null}
        {earlier.length > 0 ? (
          <>
            <h3 className="inbox-group">Earlier</h3>
            <ul className="alert-list">
              {earlier.map((a) => (
                <InboxRow key={a.id} alert={a} isNew={newIds.has(a.id)} />
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </div>
  )
}
