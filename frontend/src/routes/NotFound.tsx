import { isRouteErrorResponse, Link, useRouteError } from 'react-router'

function Message({ title }: { title: string }) {
  return (
    <div className="shell">
      <h1>{title}</h1>
      <p className="lede">
        <Link to="/">Go to the start page</Link>
      </p>
    </div>
  )
}

export function NotFound() {
  return <Message title="Page not found" />
}

/** errorElement for route trees: loader/render errors land here. */
export function RouteError() {
  const error = useRouteError()
  const notFound = isRouteErrorResponse(error) && error.status === 404
  return <Message title={notFound ? 'Page not found' : 'Something went wrong'} />
}
