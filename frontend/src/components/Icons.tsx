/** Flat stroke icons (24px grid). Decorative unless a `title` is given. */

interface IconProps {
  size?: number
  color?: string
  strokeWidth?: number
  title?: string
}

function Svg({ size = 22, color = 'currentColor', strokeWidth = 2, title, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      {children}
    </svg>
  )
}

export const MicIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z" />
    <path d="M19 11a7 7 0 0 1-14 0M12 18v3" />
  </Svg>
)
export const KeyboardIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="6" width="18" height="12" rx="2" />
    <path d="M7 10h.01M11 10h.01M15 10h.01M7 14h10" />
  </Svg>
)
export const SmileIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M8.5 14a4.5 4.5 0 0 0 7 0M9 9.5h.01M15 9.5h.01" />
  </Svg>
)
export const MegaphoneIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 10.5v3A1.5 1.5 0 0 0 4.5 15H6l9 4.5v-15L6 9H4.5A1.5 1.5 0 0 0 3 10.5Z" />
    <path d="M7 15l1.2 4.5h2.6L9.8 16" />
    <path d="M19 9a4 4 0 0 1 0 6" />
  </Svg>
)
export const ForkKnifeIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10" />
    <path d="M17 21V3c-2 1.5-3 4-3 7v3h3" />
  </Svg>
)
export const HeartIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z" />
  </Svg>
)
export const BellIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15Z" />
    <path d="M10 20a2 2 0 0 0 4 0" />
  </Svg>
)
export const CheckIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
)
export const ArrowRightIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Svg>
)
export const SparkleIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z" />
  </Svg>
)
export const CloseIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
)
export const AlertIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 7v6M12 17h.01" />
  </Svg>
)
export const MenuIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Svg>
)
export const TrashIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 7h16M10 11v6M14 11v6" />
    <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" />
  </Svg>
)
export const PhoneIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="7" y="2.5" width="10" height="19" rx="2.5" />
    <path d="M11 18.5h2" />
  </Svg>
)

/** Small flat food illustrations for the meal picker (filled, not stroked). */
export function FoodIcon({ kind, size = 32 }: { kind: string; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 32 32', 'aria-hidden': true } as const
  switch (kind) {
    case 'apple':
      return (
        <svg {...common}>
          <path d="M16 10c-3-3-10-2-10 6 0 7 5 12 10 10 5 2 10-3 10-10 0-8-7-9-10-6Z" fill="#F07A7A" />
          <path d="M16 10c0-3 1-5 3-6" stroke="#6B4A2A" strokeWidth="2" strokeLinecap="round" fill="none" />
          <path d="M17 7c2-2 5-2 6 0-2 2-5 2-6 0Z" fill="#8BC48A" />
        </svg>
      )
    case 'sandwich':
      return (
        <svg {...common}>
          <path d="M4 22L16 6l12 16Z" fill="#F3D9A4" />
          <path d="M6 22h20v4H6Z" fill="#E6BE78" />
          <path d="M8 19h16" stroke="#8BC48A" strokeWidth="3" strokeLinecap="round" />
        </svg>
      )
    case 'juice':
      return (
        <svg {...common}>
          <path d="M9 9h14v19H9Z" fill="#FFC212" />
          <path d="M9 9l3-4h8l3 4Z" fill="#F2A900" />
          <path d="M19 5V1" stroke="#7766C6" strokeWidth="2" strokeLinecap="round" />
          <circle cx="16" cy="19" r="4" fill="#F07A7A" />
        </svg>
      )
    case 'pasta':
      return (
        <svg {...common}>
          <path d="M4 16h24a12 10 0 0 1-24 0Z" fill="#7766C6" />
          <path d="M8 15c2-4 4 0 6-4s4 0 6-4 4 2 4 8" stroke="#F3D9A4" strokeWidth="2.5" fill="none" strokeLinecap="round" />
        </svg>
      )
    case 'cookie':
      return (
        <svg {...common}>
          <circle cx="16" cy="16" r="12" fill="#D9A066" />
          <circle cx="12" cy="12" r="2" fill="#6B4A2A" />
          <circle cx="20" cy="14" r="2" fill="#6B4A2A" />
          <circle cx="14" cy="21" r="2" fill="#6B4A2A" />
        </svg>
      )
    case 'cereal':
      return (
        <svg {...common}>
          <path d="M4 15h24a12 11 0 0 1-24 0Z" fill="#F9B0C3" />
          <circle cx="11" cy="12" r="3" fill="#FFC212" />
          <circle cx="17" cy="11" r="3" fill="#F3D9A4" />
          <circle cx="22" cy="13" r="2.5" fill="#FFC212" />
        </svg>
      )
    default:
      return null
  }
}

/** Scout's little avatar (yellow, as in the Option B design). */
export function ScoutAvatar({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="20" fill="#FFC212" />
      <circle cx="14.5" cy="18" r="2.4" fill="#46467A" />
      <circle cx="25.5" cy="18" r="2.4" fill="#46467A" />
      <path d="M14 24c3.5 3.5 8.5 3.5 12 0" stroke="#46467A" strokeWidth="2.4" fill="none" strokeLinecap="round" />
    </svg>
  )
}
