import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import type { ReadyResponse } from '../lib/api'
import { routes } from '../router'

const READY: ReadyResponse = {
  status: 'ok',
  database: { ok: true, latency_ms: 1.2, detail: null },
  timescaledb: { ok: true, latency_ms: null, detail: 'timescaledb 2.30.2' },
  redis: { ok: true, latency_ms: 0.4, detail: null },
  worker_heartbeat: { last_seen: '2026-11-08T00:00:00+00:00', age_s: 12 },
}

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  )
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('routing', () => {
  it('renders the child tree inside the child view scope only', async () => {
    mockFetch(200, READY)
    const { container } = renderAt('/child')
    expect(await screen.findByRole('img', { name: 'Your companion' })).toBeInTheDocument()
    expect(container.querySelector('[data-view="child"]')).not.toBeNull()
    expect(container.querySelector('[data-view="parent"]')).toBeNull()
  })

  it('renders the parent tree inside the parent view scope only', async () => {
    mockFetch(200, READY)
    const { container } = renderAt('/parent')
    expect(await screen.findByRole('heading', { name: 'System status' })).toBeInTheDocument()
    expect(container.querySelector('[data-view="parent"]')).not.toBeNull()
    expect(container.querySelector('[data-view="child"]')).toBeNull()
  })

  it('shows a not-found page for unknown paths', async () => {
    renderAt('/nope')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})

describe('ApiStatus', () => {
  it('reports connected when /readyz is ok', async () => {
    const fetchSpy = mockFetch(200, READY)
    renderAt('/parent')
    expect(await screen.findByText('All systems connected')).toBeInTheDocument()
    expect(screen.getByText('timescaledb 2.30.2')).toBeInTheDocument()
    expect(screen.getByText('12s ago')).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledWith('/api/readyz', expect.anything())
  })

  it('shows degraded details from a 503 body instead of treating it as down', async () => {
    mockFetch(503, { ...READY, status: 'degraded', redis: { ok: false, latency_ms: null, detail: 'unreachable' } })
    renderAt('/parent')
    expect(await screen.findByText('Some services unavailable')).toBeInTheDocument()
    expect(screen.getByText('Unavailable (unreachable)')).toBeInTheDocument()
  })

  it('reports unreachable when the request fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('network down'))
    renderAt('/')
    // ApiStatus retries once (1s backoff) before reporting the API as down.
    expect(await screen.findByText('API unreachable', {}, { timeout: 4000 })).toBeInTheDocument()
  })
})
