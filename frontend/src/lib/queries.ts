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
      apiPost<{ reply: string; flagged: string | null; escalated: boolean; emotion: string }>('/chat', {
        message,
      }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['chat', 'history'] })
      void qc.invalidateQueries({ queryKey: ['child', 'status'] })
      void qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })
}

export interface SummaryItem {
  text: string
  stat_keys: string[]
  confidence: 'high' | 'medium' | 'low'
}

export interface Summary {
  id: number
  created_at: string
  model: string | null
  status: 'ok' | 'rejected' | 'error' | 'disabled'
  error: string | null
  stats: Record<string, unknown>
  content: {
    headline: string
    observations: SummaryItem[]
    patterns: SummaryItem[]
    wellbeing_notes: SummaryItem[]
    discuss_with_care_team: string[]
  } | null
}

export const useSummary = () =>
  useQuery({
    queryKey: ['summary'],
    queryFn: () => apiGet<Summary | null>('/summary'),
  })

export function useGenerateSummary() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<Summary>('/summary'),
    onSuccess: (data) => qc.setQueryData(['summary'], data),
  })
}

// ---- Mood check-ins -----------------------------------------------------------

export interface Checkin {
  id: number
  mood: number
  label: string
  source: 'tap' | 'voice'
  created_at: string
}

export const useCheckins = (days = 7) =>
  useQuery({
    queryKey: ['checkins', days],
    queryFn: () => apiGet<Checkin[]>(`/checkins?days=${days}`),
    refetchInterval: 10_000,
  })

export function useCreateCheckin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (mood: number) => apiPost<Checkin & { reply: string; emotion: string }>('/checkins', { mood }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['checkins'] }),
  })
}

// ---- Help button & meals ------------------------------------------------------------

export function useHelp() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<{ sent: boolean; already_open: boolean; reply: string }>('/help'),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['child', 'status'] })
      void qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })
}

export interface MealAnalysis {
  items: { name: string; carbs_g?: number; sugar_g: number; contains_gluten: boolean }[]
  confidence: 'high' | 'medium' | 'low'
  note: string
  total_sugar_g: number
  total_carbs_g?: number
  contains_gluten: boolean
}

export interface Meal {
  id: number
  description: string
  source: 'voice' | 'tap' | 'text'
  analysis_status: 'pending' | 'ok' | 'rejected' | 'error' | 'disabled'
  analysis: MealAnalysis | null
  created_at: string
  glucose_1h: number | null
}

export const useMeals = (days = 1) =>
  useQuery({
    queryKey: ['meals', days],
    queryFn: () => apiGet<Meal[]>(`/meals?days=${days}`),
    refetchInterval: 5_000,
  })

export function useLogMeal() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { description: string; source: 'voice' | 'tap' | 'text' }) =>
      apiPost<{ id: number; reply: string }>('/meals', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['meals'] }),
  })
}
