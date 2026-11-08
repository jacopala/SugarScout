import { Link } from 'react-router'

import { ApiStatus } from '../../components/ApiStatus'

export function ParentHome() {
  return (
    <div className="shell">
      <header className="shell-header">
        <Link className="brand" to="/">
          <img src="/favicon.svg" alt="" />
          SugarScout
        </Link>
      </header>
      <p className="eyebrow">Parent dashboard</p>
      <h1>System status</h1>
      <p className="lede">
        The dashboard is built in Phase 3. For now this page confirms that the API, database,
        Redis, and worker are connected.
      </p>
      <ApiStatus detailed />
    </div>
  )
}
