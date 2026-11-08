import type { AlertOut } from './api'

/** Plain-language "why did this fire?" built from the alert's recorded evidence. */
export function alertWhy(alert: AlertOut): string[] {
  const t = alert.trigger_data as {
    readings?: { value_mg_dl: number }[]
    config?: Record<string, number>
    forecast?: { predicted: number; horizon_min: number; slope_per_5min: number }
    drop_mg_dl?: number
    gap_seconds?: number | null
    symptom?: string
    category?: string
    reasons?: string[]
    source?: string
  }
  const lines: string[] = []
  const values = t.readings?.map((r) => r.value_mg_dl) ?? []
  if (values.length) lines.push(`Readings: ${values.join(' → ')} mg/dL`)
  const c = t.config ?? {}
  switch (alert.rule_type) {
    case 'urgent_low':
      lines.push(`Rule: below ${c.urgent_low ?? 54} mg/dL`)
      break
    case 'low':
      lines.push(`Rule: below ${c.low ?? 70} for ${c.low_consecutive ?? 2} readings in a row`)
      break
    case 'high':
      lines.push(`Rule: above ${c.high ?? 250} for ${c.high_consecutive ?? 4} readings in a row`)
      break
    case 'rapid_drop':
      lines.push(`Rule: fell ${c.rapid_drop_mg_dl ?? 25}+ mg/dL within ${c.rapid_drop_window ?? 4} readings (fell ${t.drop_mg_dl ?? '?'})`)
      break
    case 'data_gap':
      lines.push(t.gap_seconds ? `No sensor reading for ${Math.round(t.gap_seconds)} seconds` : 'No sensor readings')
      break
    case 'predicted_low':
    case 'predicted_urgent_low':
      if (t.forecast) {
        lines.push(
          `Forecast: about ${t.forecast.predicted} mg/dL in ~${t.forecast.horizon_min} min (changing ${t.forecast.slope_per_5min} per 5 min)`,
        )
      }
      break
    case 'symptoms_reported':
      if (t.symptom) lines.push(`Alex said they feel ${t.symptom}`)
      break
    case 'help_request':
      lines.push('Alex pressed the Help button and confirmed')
      break
    case 'emergency_language':
      if (t.category) lines.push(`Scout heard words about ${t.category.replace('_', ' ')}; the AI was skipped`)
      break
    case 'agent_heads_up':
      for (const r of t.reasons ?? []) lines.push(r)
      break
  }
  return lines
}
