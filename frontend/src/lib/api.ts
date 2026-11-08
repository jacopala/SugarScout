/**
 * Thin fetch wrapper for the FastAPI service.
 * Local dev: requests go to /api/*, which Vite proxies to http://localhost:8000.
 * Deployed: VITE_API_BASE_URL is the Render API service URL.
 */
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api'

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(`API request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  })
  const body: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, body)
  return body as T
}

export interface CheckResult {
  ok: boolean
  latency_ms: number | null
  detail: string | null
}

export interface ReadyResponse {
  status: 'ok' | 'degraded'
  database: CheckResult
  timescaledb: CheckResult
  redis: CheckResult
  worker_heartbeat: { last_seen: string | null; age_s: number | null }
}

/** /readyz answers 503 with a full body when degraded; surface that body instead of throwing. */
export async function getReadiness(): Promise<ReadyResponse> {
  try {
    return await apiGet<ReadyResponse>('/readyz')
  } catch (err) {
    if (err instanceof ApiError && err.status === 503 && err.body) {
      return err.body as ReadyResponse
    }
    throw err
  }
}

// ---- Demo access code (stand-in for auth; see backend api/deps.py) ----------------

const KEY_STORAGE = 'sugarscout.demoKey'

export function getDemoKey(): string | null {
  try {
    return localStorage.getItem(KEY_STORAGE)
  } catch {
    return null
  }
}

export function setDemoKey(key: string | null): void {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key)
    else localStorage.removeItem(KEY_STORAGE)
  } catch {
    /* storage unavailable: the key lives only for this page view */
  }
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const key = getDemoKey()
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(key ? { 'X-Demo-Key': key } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

// ---- Domain types ------------------------------------------------------------

export type Trend = 'flat' | 'up' | 'down' | 'double_up' | 'double_down'

export interface LatestReading {
  ts: string | null
  value: number | null
  trend: Trend | null
  age_s: number | null
  stale: boolean
}

export interface LivePoint {
  ts: string
  value: number
  trend: Trend | null
}

export interface HourPoint {
  bucket: string
  avg: number
  min: number
  max: number
  n: number
}

export interface NotificationOut {
  id: number
  channel: 'dashboard' | 'sms'
  kind: 'opened' | 'resolved'
  status: 'queued' | 'sent' | 'failed' | 'dry_run' | 'skipped'
  body: string
  error: string | null
  created_at: string
  sent_at: string | null
}

export interface AlertOut {
  id: number
  rule_type: string
  label: string
  severity: 'urgent' | 'warning' | 'info'
  state: 'open' | 'acknowledged' | 'resolved'
  message: string
  trigger_data: Record<string, unknown>
  opened_at: string
  acknowledged_at: string | null
  resolved_at: string | null
  notifications: NotificationOut[]
}

export interface DemoState {
  child_name: string
  scenario: string
  scenarios: { id: string; label: string }[]
  sms_mode: 'live' | 'dry_run'
  llm_enabled: boolean
  access_code_required: boolean
}

export interface ChildStatus {
  first_name: string
  reminder: string | null
  reminder_rule: string | null
}

/** POST raw audio (a WAV clip) with the demo key. */
export async function apiPostAudio<T>(path: string, wav: ArrayBuffer): Promise<T> {
  const key = getDemoKey()
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'audio/wav',
      ...(key ? { 'X-Demo-Key': key } : {}),
    },
    body: wav,
  })
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

export interface VoiceTurn {
  heard: boolean
  woke: boolean
  awake_for_s: number
  transcript: string | null
  reply: string | null
  flagged: string | null
  escalated: boolean
  audio: string | null
}
