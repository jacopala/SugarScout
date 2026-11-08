import { Outlet } from 'react-router'

/**
 * Access guard for the parent route tree.
 * Phase 2: require an authenticated parent session; redirect to /parent/login otherwise.
 */
export function ParentGuard() {
  return (
    <div data-view="parent">
      <Outlet />
    </div>
  )
}
