import { Link } from 'react-router'

import { AccessGate } from '../../components/AccessGate'
import { AgentTimeline } from '../../components/AgentTimeline'
import { ApiStatus } from '../../components/ApiStatus'
import { AlertsPanel, DemoControls, GlucoseHero } from '../../components/Dashboard'
import { LiveChart, WeekChart } from '../../components/GlucoseCharts'
import { InsulinCard } from '../../components/InsulinCard'
import { MealsCard } from '../../components/MealsCard'
import { MoodCard } from '../../components/MoodCard'
import { PushToggle } from '../../components/PushToggle'
import { SummaryCard } from '../../components/SummaryCard'
import { useDemoState, useForecast, useLive, useWeek } from '../../lib/queries'

export function ParentHome() {
  const { data: demo } = useDemoState()
  const live = useLive(10)
  const forecast = useForecast()
  const week = useWeek()
  const name = demo?.child_name ?? 'your child'

  return (
    <AccessGate>
      <header className="parent-band">
        <div className="parent-band-inner">
          <div className="shell-header">
            <Link className="brand" to="/">
              <img src="/favicon.svg" alt="" />
              SugarScout
            </Link>
            <div className="band-actions">
              <PushToggle />
              <ApiStatus />
            </div>
          </div>
          <div>
            <p className="eyebrow">Parent dashboard</p>
            <h1>{name}</h1>
          </div>
        </div>
      </header>
      <div className="parent-body">
        <div className="dash-grid">
          <div className="dash-main">
            <GlucoseHero />
            <section className="card" aria-labelledby="live-h">
              <h2 id="live-h">Last 10 minutes</h2>
              {live.data && live.data.length > 0 ? (
                <LiveChart points={live.data} forecast={forecast.data} />
              ) : (
                <p className="empty">Waiting for readings…</p>
              )}
            </section>
            <section className="card" aria-labelledby="week-h">
              <h2 id="week-h">Last 7 days</h2>
              {week.data && week.data.length > 0 ? (
                <WeekChart points={week.data} />
              ) : (
                <p className="empty">No history yet.</p>
              )}
            </section>
            <SummaryCard />
          </div>
          <aside className="dash-side">
            <DemoControls />
            <AlertsPanel />
            <AgentTimeline />
            <MealsCard />
            <InsulinCard />
            <MoodCard />
          </aside>
        </div>
      </div>
    </AccessGate>
  )
}
