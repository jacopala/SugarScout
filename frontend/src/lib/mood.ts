/** The 1-5 mood scale shared by the child's check-in and the parent's history. */
export const MOODS = [
  { value: 1, face: '😢', label: 'Really bad' },
  { value: 2, face: '🙁', label: 'Not great' },
  { value: 3, face: '😐', label: 'Okay' },
  { value: 4, face: '🙂', label: 'Good' },
  { value: 5, face: '😄', label: 'Great' },
] as const

export function moodInfo(value: number) {
  return MOODS.find((m) => m.value === value) ?? MOODS[2]
}
