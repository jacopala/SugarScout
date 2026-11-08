/** The 1-5 mood scale shared by the child's check-in and the parent's history.
 *  Names and characters follow the team's mood art (components/MoodFace.tsx). */
export const MOODS = [
  { value: 1, label: 'Sad' },
  { value: 2, label: 'Disappointed' },
  { value: 3, label: 'Normal' },
  { value: 4, label: 'Peaceful' },
  { value: 5, label: 'Happy' },
] as const

export function moodInfo(value: number) {
  return MOODS.find((m) => m.value === value) ?? MOODS[2]
}
