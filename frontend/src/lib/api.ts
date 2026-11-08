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
