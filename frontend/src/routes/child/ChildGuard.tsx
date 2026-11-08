import { Outlet } from 'react-router'

import { AccessGate } from '../../components/AccessGate'

/**
 * Access guard for the child route tree.
 * Phase 2: require a restricted device token from pairing. Without one, redirect
 * to a pairing-code screen. A child token must never reach /parent routes.
 */
export function ChildGuard() {
  return (
    <div data-view="child">
      <AccessGate>
        <Outlet />
      </AccessGate>
    </div>
  )
}
