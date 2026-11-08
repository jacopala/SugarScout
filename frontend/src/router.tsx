import type { RouteObject } from 'react-router'

import { ChildGuard } from './routes/child/ChildGuard'
import { MoodCheck } from './routes/child/MoodCheck'
import { ScoutDisplay } from './routes/child/ScoutDisplay'
import { Home } from './routes/Home'
import { NotFound, RouteError } from './routes/NotFound'
import { ParentGuard } from './routes/parent/ParentGuard'
import { ParentHome } from './routes/parent/ParentHome'

/**
 * Child and parent experiences are separate route trees with separate guards
 * (design doc Section 10.3), so neither can render inside the other's layout.
 */
export const routes: RouteObject[] = [
  { path: '/', element: <Home />, errorElement: <RouteError /> },
  {
    path: '/child',
    element: <ChildGuard />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <MoodCheck /> },
      { path: 'scout', element: <ScoutDisplay /> },
    ],
  },
  {
    path: '/parent',
    element: <ParentGuard />,
    errorElement: <RouteError />,
    children: [{ index: true, element: <ParentHome /> }],
  },
  { path: '*', element: <NotFound /> },
]
