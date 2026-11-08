/** The bright palette shared by the child's fireworks and Sky Pop. */
export const PLAY_COLORS = ['#FFC212', '#7766C6', '#F27BA4', '#5CC28C', '#4FA3F7', '#FF8A3D'] as const

export const pickColor = (colors: readonly string[] = PLAY_COLORS): string =>
  colors[Math.floor(Math.random() * colors.length)] ?? '#7766C6'
