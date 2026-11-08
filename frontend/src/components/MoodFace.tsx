/**
 * The team's mood characters (pastel blobs with simple line faces), redrawn as SVG.
 * 1 sad · 2 disappointed · 3 normal · 4 peaceful · 5 happy
 */

const INK = '#2b2622'

interface FaceProps {
  mood: number
  size?: number
  title?: string
}

function Sad() {
  return (
    <>
      <path
        d="M24 52C24 31 39 21 60 21c23 0 36 12 36 34 0 26-13 43-37 43-24 0-36-15-35-46Z"
        fill="#7096DF"
      />
      {/* eyes with little tears */}
      <path d="M47 49v8M73 49v8" stroke={INK} strokeWidth="4.5" strokeLinecap="round" />
      <path d="M45 62.5c0 2.2 1 3.8 2.2 3.8s2.2-1.6 2.2-3.8L47.2 59Z" fill="#fff" opacity=".9" />
      <path d="M71 62.5c0 2.2 1 3.8 2.2 3.8s2.2-1.6 2.2-3.8L73.2 59Z" fill="#fff" opacity=".9" />
      <path d="M56 59h8" stroke={INK} strokeWidth="4" strokeLinecap="round" />
    </>
  )
}

function Disappointed() {
  return (
    <>
      <path
        d="M29 47c-2-17 12-27 27-26 5-6 15-5 19 1 19 4 28 21 25 40-3 23-20 38-42 38-22 0-37-15-37-35 0-7 3-13 8-18Z"
        fill="#F2D27C"
      />
      {/* droopy closed eyes */}
      <path d="M39 57c3-5 8-7 12-5M69 52c4-2 9 0 12 5" stroke={INK} strokeWidth="4" strokeLinecap="round" fill="none" />
      <path d="M53 75c4-5 10-5 14 0" stroke={INK} strokeWidth="4" strokeLinecap="round" fill="none" />
    </>
  )
}

function Normal() {
  return (
    <>
      <path
        d="M20 61c0-24 18-41 41-41 23 0 39 17 39 40 0 23-17 40-40 40-23 0-40-16-40-39Z"
        fill="#CDDCE3"
      />
      <circle cx="47" cy="58" r="3.6" fill={INK} />
      <circle cx="73" cy="56" r="3.6" fill={INK} />
      <path d="M56 65h8" stroke={INK} strokeWidth="4" strokeLinecap="round" />
    </>
  )
}

function Peaceful() {
  return (
    <>
      <path
        d="M23 58c0-23 16-38 37-38s37 15 37 38v27c0 11-9 15-15 9-4-4-9-4-13 2-4 6-13 6-17 0-4-6-9-6-13-2-7 6-16 2-16-9V58Z"
        fill="#A8C3A0"
      />
      {/* closed, smiling eyes */}
      <path d="M41 54c3 5 9 5 12 0M67 54c3 5 9 5 12 0" stroke={INK} strokeWidth="4" strokeLinecap="round" fill="none" />
      <path d="M56 64c2 3 6 3 8 0" stroke={INK} strokeWidth="4" strokeLinecap="round" fill="none" />
    </>
  )
}

function Happy() {
  return (
    <>
      <path
        d="M27 39c4-19 33-24 54-17 20 7 25 29 18 49-7 21-26 33-45 29-19-4-32-21-32-39 0-9 2-16 5-22Z"
        fill="#EDB5BD"
      />
      {/* squinting >ᴗ< */}
      <path d="M40 51l9 6-9 6M80 51l-9 6 9 6" stroke={INK} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <path d="M55 59c2 5 8 5 10 0" stroke={INK} strokeWidth="4" strokeLinecap="round" fill="none" />
    </>
  )
}

const FACES: Record<number, () => React.JSX.Element> = {
  1: Sad,
  2: Disappointed,
  3: Normal,
  4: Peaceful,
  5: Happy,
}

export function MoodFace({ mood, size = 72, title }: FaceProps) {
  const Face = FACES[mood] ?? Normal
  return (
    <svg
      className="mood-face-svg"
      width={size}
      height={size}
      viewBox="0 0 120 120"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <Face />
    </svg>
  )
}
