import { useCallback, useState } from 'react'
import { Link } from 'react-router'

import { AccessGate } from '../../components/AccessGate'
import { AlertsBell, AlertsPopup } from '../../components/AlertsInbox'
import { AgentTimeline } from '../../components/AgentTimeline'
import { ApiStatus } from '../../components/ApiStatus'
import { DemoControls, GlucoseHero } from '../../components/Dashboard'
import { LiveChart, WeekChart } from '../../components/GlucoseCharts'
import { InsulinCard } from '../../components/InsulinCard'
import { MealsCard } from '../../components/MealsCard'
import { MoodCard } from '../../components/MoodCard'
import { PushToggle } from '../../components/PushToggle'
import { SectionMenu, type MenuSection } from '../../components/SectionMenu'
import { SummaryCard } from '../../components/SummaryCard'
import { useDemoState, useForecast, useLive, useWeek } from '../../lib/queries'

const SECTIONS: MenuSection[] = [
  { id: 'live-h', label: 'Now' },
  { id: 'agent-h', label: 'Scout agent' },
  { id: 'meals-h', label: 'Meals' },
  { id: 'insulin-h', label: 'Insulin' },
  { id: 'mood-h', label: 'Moods' },
  { id: 'summary-h', label: 'Summary' },
  { id: 'demo-h', label: 'Demo controls' },
]

export function ParentHome() {
  const [inbox, setInbox] = useState(false)
  const openInbox = useCallback(() => setInbox(true), [])
  const closeInbox = useCallback(() => setInbox(false), [])
  const { data: demo } = useDemoState()
  const live = useLive(10)
  const forecast = useForecast()
  const week = useWeek()
  const name = demo?.child_name ?? 'your child'

  return (
    <AccessGate>
      <div className="parent-topbar">
        <div className="parent-topbar-inner">
          <SectionMenu sections={SECTIONS} extra={[{ label: 'Alerts', onSelect: openInbox }]} />
          <Link className="brand" to="/">
            <img src="/favicon.svg" alt="" />
            SugarScout
          </Link>
          <div className="band-actions">
            <ApiStatus />
            <AlertsBell onOpen={openInbox} />
          </div>
        </div>
      </div>
      <header className="parent-band">
        <div className="parent-band-inner parent-band-row">
          <div>
            <p className="eyebrow">Parent dashboard</p>
            <h1>{name}</h1>
          </div>
          <PushToggle />
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
            <AgentTimeline />
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
            <MealsCard />
            <InsulinCard />
            <MoodCard />
          </aside>
        </div>
      </div>
      {inbox ? <AlertsPopup onClose={closeInbox} /> : null}
    </AccessGate>
  )
}
