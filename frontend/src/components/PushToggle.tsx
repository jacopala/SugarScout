import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { apiGet, apiPost } from '../lib/api'
import { BellIcon, CheckIcon } from './Icons'

interface PushConfig {
  enabled: boolean
  public_key: string | null
  devices: number
}

function b64ToBytes(b64url: string): Uint8Array<ArrayBuffer> {
  const pad = '='.repeat((4 - (b64url.length % 4)) % 4)
  const raw = atob((b64url + pad).replace(/-/g, '+').replace(/_/g, '/'))
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

const pushSupported = () =>
  typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

const isIOS = () => typeof navigator !== 'undefined' && /iPhone|iPad|iPod/.test(navigator.userAgent)
const isStandalone = () =>
  typeof window !== 'undefined' &&
  (window.matchMedia?.('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true)

/** "Alert me on this device": subscribes this browser to push alerts about the child. */
export function PushToggle() {
  const qc = useQueryClient()
  const { data: cfg } = useQuery({ queryKey: ['push', 'config'], queryFn: () => apiGet<PushConfig>('/push/config') })
  const [subscribed, setSubscribed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    if (!pushSupported()) return
    void navigator.serviceWorker.getRegistration().then(async (reg) => {
      const sub = await reg?.pushManager.getSubscription()
      setSubscribed(Boolean(sub))
    })
  }, [])

  if (!cfg?.enabled) return null
  if (!pushSupported()) {
    return (
      <span className="push-note">
        {isIOS() && !isStandalone() ? 'Add to Home Screen to get alerts' : 'Alerts not supported in this browser'}
      </span>
    )
  }

  async function enable() {
    if (!cfg?.public_key) return
    setBusy(true)
    setNote(null)
    try {
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        setNote('Notifications are blocked for this site.')
        return
      }
      const reg = await navigator.serviceWorker.ready
      const sub =
        (await reg.pushManager.getSubscription()) ??
        (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(cfg.public_key) }))
      const json = sub.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } }
      await apiPost('/push/subscribe', { endpoint: json.endpoint, keys: json.keys })
      await apiPost('/push/test')
      setSubscribed(true)
      setNote('Sent a test alert to this device.')
      void qc.invalidateQueries({ queryKey: ['push', 'config'] })
    } catch {
      setNote('Couldn’t turn on alerts. Try again?')
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="push-toggle">
      {subscribed ? (
        <span className="push-on" role="status">
          <CheckIcon size={16} strokeWidth={2.6} /> Alerts on for this device
        </span>
      ) : (
        <button className="btn push-btn" onClick={() => void enable()} disabled={busy}>
          <BellIcon size={18} /> {busy ? 'Turning on…' : 'Alert me on this device'}
        </button>
      )}
      {note ? <span className="push-note">{note}</span> : null}
    </span>
  )
}
