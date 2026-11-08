import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiStatus } from '../components/ApiStatus'
import type { AlertOut, DemoState, ReadyResponse } from '../lib/api'
import { routes } from '../router'

const READY: ReadyResponse = {
  status: 'ok',
  database: { ok: true, latency_ms: 1.2, detail: null },
  timescaledb: { ok: true, latency_ms: null, detail: 'timescaledb 2.30.2' },
  redis: { ok: true, latency_ms: 0.4, detail: null },
  worker_heartbeat: { last_seen: '2026-11-08T00:00:00+00:00', age_s: 12 },
}

const DEMO: DemoState = {
  child_name: 'Alex',
  scenario: 'steady',
  scenarios: [
    { id: 'steady', label: 'Steady' },
    { id: 'rapid_drop', label: 'Rapid drop' },
  ],
  sms_mode: 'dry_run',
  llm_enabled: false,
  access_code_required: false,
}

const URGENT: AlertOut = {
  id: 7,
  rule_type: 'urgent_low',
  label: 'urgent low',
  severity: 'urgent',
  state: 'open',
  message: "Alex's glucose is urgently low (50 mg/dL).",
  trigger_data: {},
  opened_at: '2026-11-08T12:00:00Z',
  acknowledged_at: null,
  resolved_at: null,
  read_at: null,
  notifications: [
    {
      id: 1,
      channel: 'sms',
      kind: 'opened',
      status: 'dry_run',
      body: 'x',
      error: null,
      created_at: '2026-11-08T12:00:00Z',
      sent_at: null,
    },
  ],
}

type Routes = Record<string, { status?: number; body: unknown }>

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Route fetches by path prefix; unknown paths 404. */
function mockApi(overrides: Routes = {}) {
  const table: Routes = {
    '/api/readyz': { body: READY },
    '/api/demo/state': { body: DEMO },
    '/api/glucose/latest': {
      body: { ts: new Date().toISOString(), value: 112, trend: 'flat', age_s: 2, stale: false },
    },
    '/api/glucose/live': { body: [] },
    '/api/glucose/week': { body: [] },
    '/api/alerts': { body: [] },
    '/api/child/status': { body: { first_name: 'Alex', reminder: null, reminder_rule: null } },
    '/api/chat/history': { body: [] },
    '/api/summary': { body: null },
    '/api/checkins': { body: [] },
    '/api/meals': { body: [] },
    '/api/agent/question': { body: null },
    '/api/agent/timeline': { body: [] },
    '/api/insulin': { body: [] },
    '/api/glucose/forecast': { body: { made_at: null, predicted: null, horizon_min: null, slope_per_5min: null, mae_24h: null, scored_24h: 0 } },
    ...overrides,
  }
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    const key = Object.keys(table)
      .sort((a, b) => b.length - a.length)
      .find((k) => url.startsWith(k) && (init?.method ?? 'GET') === 'GET')
    const hit = key ? table[key] : undefined
    if (hit) return json(hit.body, hit.status ?? 200)
    const other = overrides[`${init?.method ?? 'GET'} ${url}`]
    if (other) return json(other.body, other.status ?? 200)
    return json({ detail: 'not found' }, 404)
  })
}

function withClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  return render(withClient(<RouterProvider router={router} />))
}

beforeEach(() => {
  localStorage.clear()
})

describe('routing', () => {
  it('renders the child tree inside the child view scope only', async () => {
    mockApi()
    const { container } = renderAt('/child')
    expect(await screen.findByRole('heading', { name: /How are you feeling today\?/ })).toBeInTheDocument()
    expect(container.querySelector('[data-view="child"]')).not.toBeNull()
    expect(container.querySelector('[data-view="parent"]')).toBeNull()
  })

  it('renders the parent tree inside the parent view scope only', async () => {
    mockApi()
    const { container } = renderAt('/parent')
    expect(await screen.findByRole('heading', { name: 'Alex' })).toBeInTheDocument()
    expect(container.querySelector('[data-view="parent"]')).not.toBeNull()
    expect(container.querySelector('[data-view="child"]')).toBeNull()
  })

  it('shows a not-found page for unknown paths', async () => {
    renderAt('/nope')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})

describe('parent dashboard', () => {
  it('rings the bell for unread alerts and lists them in the pop-up', async () => {
    const fetchSpy = mockApi({ '/api/alerts': { body: [URGENT] }, 'POST /api/alerts/read': { body: { marked: 1 } } })
    renderAt('/parent')
    expect(await screen.findByText('112')).toBeInTheDocument()
    const bell = await screen.findByRole('button', { name: 'Alerts: 1 unread' })
    expect(bell).toHaveAttribute('data-unread')
    expect(screen.queryByText("Alex's glucose is urgently low (50 mg/dL).")).toBeNull()
    fireEvent.click(bell)
    expect(screen.getByRole('dialog', { name: 'Alerts' })).toBeInTheDocument()
    expect(screen.getByText("Alex's glucose is urgently low (50 mg/dL).")).toBeInTheDocument()
    expect(screen.getByText(/Text dry run/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Acknowledge urgent low alert' })).toBeInTheDocument()
    // An open alert can't be deleted until it's handled.
    expect(screen.queryByRole('button', { name: /Delete/ })).toBeNull()
    await waitFor(() => {
      const read = fetchSpy.mock.calls.find(([url, init]) => String(url) === '/api/alerts/read' && init?.method === 'POST')
      expect(JSON.parse(String(read?.[1]?.body))).toEqual({ ids: [7] })
    })
  })

  it('lets the parent delete a read alert', async () => {
    const seen = { ...URGENT, state: 'acknowledged', read_at: '2026-11-08T12:01:00Z' }
    const fetchSpy = mockApi({ '/api/alerts': { body: [seen] }, 'DELETE /api/alerts/7': { body: { ok: true } } })
    renderAt('/parent')
    const bell = await screen.findByRole('button', { name: 'Alerts' })
    expect(bell).not.toHaveAttribute('data-unread')
    fireEvent.click(bell)
    fireEvent.click(await screen.findByRole('button', { name: 'Delete urgent low alert' }))
    await waitFor(() =>
      expect(fetchSpy.mock.calls.some(([url, init]) => String(url) === '/api/alerts/7' && init?.method === 'DELETE')).toBe(true),
    )
  })

  it('jumps between sections from the sandwich menu', async () => {
    mockApi()
    renderAt('/parent')
    fireEvent.click(await screen.findByRole('button', { name: 'Open menu' }))
    const nav = screen.getByRole('navigation', { name: 'Dashboard sections' })
    expect(nav).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: 'Insulin' }))
    expect(screen.queryByRole('navigation', { name: 'Dashboard sections' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Open menu' }))
    expect(screen.getByRole('link', { name: 'Insulin' })).toHaveAttribute('aria-current', 'true')
  })

  it('says the sensor is silent instead of showing a stale number', async () => {
    mockApi({
      '/api/glucose/latest': { body: { ts: null, value: 140, trend: 'flat', age_s: 95, stale: true } },
    })
    renderAt('/parent')
    expect(await screen.findByText('No recent data')).toBeInTheDocument()
    expect(screen.queryByText('140')).toBeNull()
  })

  it('asks for the access code when the API requires one', async () => {
    mockApi({
      '/api/demo/state': { body: { ...DEMO, access_code_required: true } },
      'POST /api/demo/check-key': { body: { ok: true } },
    })
    renderAt('/parent')
    const input = await screen.findByLabelText('Access code')
    fireEvent.change(input, { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(localStorage.getItem('sugarscout.demoKey')).toBe('secret'))
    expect(await screen.findByRole('heading', { name: 'Alex' })).toBeInTheDocument()
  })
})

describe('ApiStatus', () => {
  it('reports connected when /readyz is ok', async () => {
    mockApi()
    render(withClient(<ApiStatus detailed />))
    expect(await screen.findByText('All systems connected')).toBeInTheDocument()
    expect(screen.getByText('timescaledb 2.30.2')).toBeInTheDocument()
    expect(screen.getByText('12s ago')).toBeInTheDocument()
  })

  it('shows degraded details from a 503 body instead of treating it as down', async () => {
    mockApi({
      '/api/readyz': {
        status: 503,
        body: { ...READY, status: 'degraded', redis: { ok: false, latency_ms: null, detail: 'unreachable' } },
      },
    })
    render(withClient(<ApiStatus detailed />))
    expect(await screen.findByText('Some services unavailable')).toBeInTheDocument()
    expect(screen.getByText('Unavailable (unreachable)')).toBeInTheDocument()
  })

  it('reports unreachable when the request fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('network down'))
    render(withClient(<ApiStatus />))
    // ApiStatus retries once (1s backoff) before reporting the API as down.
    expect(await screen.findByText('API unreachable', {}, { timeout: 4000 })).toBeInTheDocument()
  })
})

describe('mood check-in', () => {
  it('saves the mood, then opens Scout showing its gentle reply', async () => {
    const fetchSpy = mockApi({
      'POST /api/checkins': {
        body: {
          id: 1,
          mood: 2,
          label: 'disappointed',
          source: 'tap',
          created_at: new Date().toISOString(),
          reply: 'Aw, feeling disappointed is hard. Want to tell me what happened?',
        },
      },
      'POST /api/voice/speak': { body: { audio: null } },
    })
    renderAt('/child')
    fireEvent.click(await screen.findByRole('button', { name: '2 out of 5: Disappointed' }))
    // The bar swells around the chosen face; nothing is saved until "That's me".
    expect(screen.getByRole('button', { name: '2 out of 5: Disappointed' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'That’s me' }))
    expect(await screen.findByText('Aw, feeling disappointed is hard. Want to tell me what happened?')).toBeInTheDocument()
    const post = fetchSpy.mock.calls.find(([url, init]) => String(url) === '/api/checkins' && init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ mood: 2 })
    // jsdom has no microphone: the display falls back to typing.
    expect(screen.getByLabelText('Message Scout')).toBeInTheDocument()
  })

  it('lists check-ins with their time on the parent dashboard', async () => {
    const at = new Date()
    at.setHours(15, 42, 0, 0)
    mockApi({
      '/api/checkins': {
        body: [{ id: 3, mood: 1, label: 'sad', source: 'tap', created_at: at.toISOString() }],
      },
    })
    renderAt('/parent')
    expect(await screen.findByText('Sad', { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByText(/Today 3:42/)).toBeInTheDocument()
    expect(screen.getByText(/Today: 1 check-in, average 1\.0 of 5/)).toBeInTheDocument()
    expect(screen.getByText('1 low mood today')).toBeInTheDocument()
    // The full list stays folded away until asked for.
    expect(document.querySelector('.mood-list')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Show all 1 check-in' }))
    expect(document.querySelector('.mood-list')).not.toBeNull()
  })
})

describe('child safety and meals', () => {
  it('Help asks for confirmation before alerting the parent', async () => {
    const fetchSpy = mockApi({
      'POST /api/help': { body: { sent: true, already_open: false, reply: 'I told your grown-up you need help.' } },
      'POST /api/voice/speak': { body: { audio: null } },
    })
    renderAt('/child/scout')
    fireEvent.click(await screen.findByRole('button', { name: 'Help' }))
    expect(screen.getByRole('dialog', { name: 'Tell your grown-up you need help?' })).toBeInTheDocument()
    const helpCalls = () => fetchSpy.mock.calls.filter(([url]) => String(url) === '/api/help')
    expect(helpCalls()).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Yes, get help' }))
    expect(await screen.findByRole('heading', { name: 'Your grown-up is on the way' })).toBeInTheDocument()
    expect(helpCalls()).toHaveLength(1)
  })

  it('Not now closes the help dialog without sending anything', async () => {
    const fetchSpy = mockApi()
    renderAt('/child/scout')
    fireEvent.click(await screen.findByRole('button', { name: 'Help' }))
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(fetchSpy.mock.calls.some(([url]) => String(url) === '/api/help')).toBe(false)
  })

  it('logs a tapped meal and Scout thanks the child without numbers', async () => {
    const fetchSpy = mockApi({
      'POST /api/meals': { body: { id: 9, reply: "Yum! Thanks for telling me. I'll share it with your grown-up." } },
      'POST /api/voice/speak': { body: { audio: null } },
    })
    renderAt('/child/scout')
    fireEvent.click(await screen.findByRole('button', { name: 'Meals' }))
    fireEvent.click(screen.getByRole('button', { name: 'Sandwich' }))
    fireEvent.click(screen.getByRole('button', { name: 'Juice' }))
    fireEvent.click(screen.getByRole('button', { name: 'Tell Scout' }))
    expect(await screen.findByText("Yum! Thanks for telling me. I'll share it with your grown-up.")).toBeInTheDocument()
    const post = fetchSpy.mock.calls.find(([url, init]) => String(url) === '/api/meals' && init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ description: 'sandwich, juice', source: 'tap' })
  })

  it('shows meal estimates to the parent, labelled as AI estimates', async () => {
    mockApi({
      '/api/meals': {
        body: [
          {
            id: 1,
            description: 'a turkey sandwich and apple juice',
            source: 'voice',
            analysis_status: 'ok',
            analysis: {
              items: [],
              confidence: 'medium',
              note: 'Most of the sugar is from the juice.',
              total_sugar_g: 26,
              contains_gluten: true,
            },
            created_at: new Date().toISOString(),
            glucose_1h: 168,
          },
        ],
      },
    })
    renderAt('/parent')
    expect(await screen.findByText('“a turkey sandwich and apple juice”')).toBeInTheDocument()
    expect(screen.getByText('Sugar ~26 g')).toBeInTheDocument()
    expect(screen.getByText('Contains gluten')).toBeInTheDocument()
    expect(screen.getByText('Glucose 1 h later: 168')).toBeInTheDocument()
    expect(screen.getByText(/Not a carb count for dosing/)).toBeInTheDocument()
  })
})

describe('Scout agent', () => {
  it('shows Scout\'s question and sends the tapped answer', async () => {
    const fetchSpy = mockApi({
      '/api/agent/question': {
        body: {
          id: 42,
          question: 'insulin_with_meal',
          kind: 'choice',
          wording: 'Did you have your insulin with your snack?',
          options: [
            { value: 'yes', label: 'Yes' },
            { value: 'not_yet', label: 'Not yet' },
            { value: 'dont_know', label: "I don't know" },
          ],
          asked_at: new Date().toISOString(),
        },
      },
      'POST /api/agent/answer': {
        body: { reply: "Okay, thanks for telling me. Let's check your plan with a grown-up.", emotion: 'calm', open_meals: false },
      },
      'POST /api/voice/speak': { body: { audio: null } },
    })
    const { container } = renderAt('/child/scout')
    expect(await screen.findByRole('heading', { name: 'Did you have your insulin with your snack?' })).toBeInTheDocument()
    // The layout switches to its compact "question showing" mode (smaller mic on short phones).
    expect(container.querySelector('.scout-screen.has-question')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Not yet' }))
    expect(await screen.findByText("Okay, thanks for telling me. Let's check your plan with a grown-up.")).toBeInTheDocument()
    const post = fetchSpy.mock.calls.find(([url, init]) => String(url) === '/api/agent/answer' && init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ question_id: 42, answer: 'not_yet' })
  })

  it('shows the parent what the agent asked and why it sent a heads-up', async () => {
    mockApi({
      '/api/agent/timeline': {
        body: [
          {
            at: new Date().toISOString(),
            type: 'heads_up',
            text: 'Alex is rising (214) after ~54 g carbs and no insulin is logged.',
            reasons: ['rising after a snack'],
            answer: null,
            answered_at: null,
            state: 'open',
          },
          {
            at: new Date().toISOString(),
            type: 'asked',
            text: 'Did you have your insulin with your snack?',
            reasons: [],
            answer: 'Not yet',
            answered_at: new Date().toISOString(),
            state: null,
          },
        ],
      },
    })
    renderAt('/parent')
    // Minimal by default: only the latest entry, no reasons or older history.
    expect(await screen.findByText('Alex is rising (214) after ~54 g carbs and no insulin is logged.')).toBeInTheDocument()
    expect(screen.queryByText('rising after a snack')).toBeNull()
    expect(screen.queryByText('Not yet')).toBeNull()
    const toggle = screen.getByRole('button', { name: 'Show reasons and history (1 more)' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    // The parent asks for more: reasons and the full history appear.
    fireEvent.click(toggle)
    expect(screen.getByText('rising after a snack')).toBeInTheDocument()
    expect(screen.getByText('Not yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show less' })).toHaveAttribute('aria-expanded', 'true')
  })
})
