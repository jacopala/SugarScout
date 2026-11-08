import { useQuery } from '@tanstack/react-query'

import { getReadiness, type ReadyResponse } from '../lib/api'

type State = 'ok' | 'degraded' | 'down' | 'loading'

function stateOf(data: ReadyResponse | undefined, isError: boolean): State {
  if (isError) return 'down'
  if (!data) return 'loading'
  return data.status
}

const LABEL: Record<State, string> = {
  ok: 'All systems connected',
  degraded: 'Some services unavailable',
  down: 'API unreachable',
  loading: 'Checking connection…',
}

export function ApiStatus({ detailed = false }: { detailed?: boolean }) {
  const { data, isError } = useQuery({
    queryKey: ['readiness'],
    queryFn: getReadiness,
    refetchInterval: 15_000,
    retry: 1,
  })
  const state = stateOf(data, isError)

  return (
    <div>
      <span className="api-status" data-state={state} role="status" aria-live="polite">
        <span className="dot" aria-hidden="true" />
        {LABEL[state]}
      </span>
      {detailed && data ? (
        <table className="status-table">
          <thead>
            <tr>
              <th scope="col">Dependency</th>
              <th scope="col">Status</th>
              <th scope="col">Latency</th>
            </tr>
          </thead>
          <tbody>
            <Row name="Database" check={data.database} />
            <Row name="TimescaleDB" check={data.timescaledb} />
            <Row name="Redis" check={data.redis} />
            <tr>
              <td>Worker heartbeat</td>
              <td>{data.worker_heartbeat.age_s === null ? 'No heartbeat yet' : 'Seen'}</td>
              <td className="num">
                {data.worker_heartbeat.age_s === null ? '—' : `${data.worker_heartbeat.age_s}s ago`}
              </td>
            </tr>
          </tbody>
        </table>
      ) : null}
    </div>
  )
}

function Row({ name, check }: { name: string; check: ReadyResponse['database'] }) {
  return (
    <tr>
      <td>{name}</td>
      <td>{check.ok ? (check.detail ?? 'Connected') : `Unavailable (${check.detail ?? 'error'})`}</td>
      <td className="num">{check.latency_ms === null ? '—' : `${check.latency_ms} ms`}</td>
    </tr>
  )
}
