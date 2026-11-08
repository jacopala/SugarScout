import { Link } from 'react-router'

import { ApiStatus } from '../components/ApiStatus'

export function Home() {
  return (
    <div className="shell">
      <header className="shell-header">
        <span className="brand">
          <img src="/favicon.svg" alt="" />
          SugarScout
        </span>
        <ApiStatus />
      </header>
      <p className="eyebrow">Development build</p>
      <h1>Pediatric Health Companion</h1>
      <p className="lede">
        Two separate experiences share this app. Each has its own route tree and its own access
        guard. Sign-in and device pairing arrive in Phase 2.
      </p>
      <div className="cards">
        <Link className="card" to="/child">
          <h2>Child companion</h2>
          <p>Opens on a paired device. Shows a friendly character, check-ins, and snack logging.</p>
        </Link>
        <Link className="card" to="/parent">
          <h2>Parent dashboard</h2>
          <p>Glucose history, companion notes, alerts, and settings.</p>
        </Link>
      </div>
    </div>
  )
}
