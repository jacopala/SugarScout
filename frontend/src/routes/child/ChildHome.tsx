import { Link } from 'react-router'

export function ChildHome() {
  return (
    <main className="child-stage">
      <div>
        <svg className="companion" viewBox="0 0 120 120" role="img" aria-label="Your companion">
          <circle cx="60" cy="62" r="50" fill="var(--view-accent)" opacity="0.18" />
          <circle cx="60" cy="62" r="40" fill="var(--view-accent)" />
          <circle cx="46" cy="56" r="5" fill="#fff" />
          <circle cx="74" cy="56" r="5" fill="#fff" />
          <path
            d="M44 74c4.5 5 9.8 7.5 16 7.5s11.5-2.5 16-7.5"
            stroke="#fff"
            strokeWidth="5"
            fill="none"
            strokeLinecap="round"
          />
        </svg>
        <p className="bubble">Hi there! I’m getting ready. See you soon!</p>
        <p className="placeholder-note">
          Placeholder screen. Chat, check-ins, and snack logging arrive in Phases 3 and 5.{' '}
          <Link to="/">Back</Link>
        </p>
      </div>
    </main>
  )
}
