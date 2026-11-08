import { useState, type FormEvent, type ReactNode } from 'react'

import { ApiError, apiPost, getDemoKey, setDemoKey } from '../lib/api'
import { useDemoState } from '../lib/queries'

/**
 * Hackathon stand-in for sign-in: asks once for the shared demo access code when the
 * API requires one, and keeps it in localStorage. Read-only views render regardless.
 */
export function AccessGate({ children }: { children: ReactNode }) {
  const { data } = useDemoState()
  const [hasKey, setHasKey] = useState(() => Boolean(getDemoKey()))
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!data?.access_code_required || hasKey) return <>{children}</>

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setDemoKey(code.trim())
    try {
      await apiPost('/demo/check-key')
      setHasKey(true)
    } catch (err) {
      setDemoKey(null)
      setError(err instanceof ApiError && err.status === 401 ? 'That code didn’t work.' : 'Could not reach the API.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="shell">
      <form className="card access-form" onSubmit={submit}>
        <h2>Enter the demo access code</h2>
        <p>This keeps strangers from sending texts or using model credits on the public demo.</p>
        <label htmlFor="demo-code">Access code</label>
        <input
          id="demo-code"
          type="password"
          autoComplete="off"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          required
        />
        {error ? <p role="alert" className="form-error">{error}</p> : null}
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? 'Checking…' : 'Continue'}
        </button>
      </form>
    </div>
  )
}
