import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  apiGet,
  apiPost,
  type AlertOut,
  type ChildStatus,
  type DemoState,
  type HourPoint,
  type LatestReading,
  type LivePoint,
} from './api'

/** Live data polls every few seconds: simpler and sturdier than SSE for a demo. */
export const LIVE_POLL_MS = 3_000

export const useLatest = () =>
  useQuery({
    queryKey: ['glucose', 'latest'],
    queryFn: () => apiGet<LatestReading>('/glucose/latest'),
    refetchInterval: LIVE_POLL_MS,
  })

export const useLive = (minutes = 10) =>
  useQuery({
    queryKey: ['glucose', 'live', minutes],
    queryFn: () => apiGet<LivePoint[]>(`/glucose/live?minutes=${minutes}`),
    refetchInterval: LIVE_POLL_MS,
  })

export const useWeek = () =>
  useQuery({
    queryKey: ['glucose', 'week'],
    queryFn: () => apiGet<HourPoint[]>('/glucose/week'),
    refetchInterval: 60_000,
  })

export const useAlerts = () =>
  useQuery({
    queryKey: ['alerts'],
    queryFn: () => apiGet<AlertOut[]>('/alerts'),
    refetchInterval: LIVE_POLL_MS,
  })

export const useDemoState = () =>
  useQuery({
    queryKey: ['demo', 'state'],
    queryFn: () => apiGet<DemoState>('/demo/state'),
    refetchInterval: LIVE_POLL_MS,
  })

export const useChildStatus = () =>
  useQuery({
    queryKey: ['child', 'status'],
    queryFn: () => apiGet<ChildStatus>('/child/status'),
    refetchInterval: LIVE_POLL_MS,
  })

export function useAckAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiPost(`/alerts/${id}/ack`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })
}

export function useSetScenario() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (scenario: string) => apiPost<DemoState>('/demo/scenario', { scenario }),
    onSuccess: (data) => qc.setQueryData(['demo', 'state'], data),
  })
}

export interface ChatMessage {
  id: number
  role: 'child' | 'companion'
  content: string
  flagged: string | null
  created_at: string
}

export const useChatHistory = () =>
  useQuery({
    queryKey: ['chat', 'history'],
    queryFn: () => apiGet<ChatMessage[]>('/chat/history'),
    refetchInterval: 10_000,
  })

export function useSendChat() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (message: string) =>
      apiPost<{ reply: string; flagged: string | null; escalated: boolean }>('/chat', { message }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['chat', 'history'] })
      void qc.invalidateQueries({ queryKey: ['child', 'status'] })
      void qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })
}
