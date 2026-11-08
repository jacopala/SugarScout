import { describe, expect, it } from 'vitest'

import { Segmenter } from '../lib/voice/segmenter'
import { downsample, encodeWav16 } from '../lib/voice/wav'

const RATE = 48_000
const FRAME = 1024

function frames(seconds: number, amplitude: number): Float32Array[] {
  const out: Float32Array[] = []
  const n = Math.round((seconds * RATE) / FRAME)
  for (let f = 0; f < n; f++) {
    const fr = new Float32Array(FRAME)
    for (let i = 0; i < FRAME; i++) fr[i] = amplitude * Math.sin(((f * FRAME + i) / RATE) * 2 * Math.PI * 220)
    out.push(fr)
  }
  return out
}

describe('wav helpers', () => {
  it('downsamples 48 kHz to 16 kHz', () => {
    expect(downsample(new Float32Array(48_000), 48_000).length).toBe(16_000)
  })

  it('writes a 16-bit mono WAV header', () => {
    const wav = new DataView(encodeWav16(new Float32Array(160)))
    const tag = (o: number) => String.fromCharCode(...[0, 1, 2, 3].map((i) => wav.getUint8(o + i)))
    expect(tag(0)).toBe('RIFF')
    expect(tag(8)).toBe('WAVE')
    expect(wav.getUint16(22, true)).toBe(1) // mono
    expect(wav.getUint32(24, true)).toBe(16_000)
    expect(wav.getUint16(34, true)).toBe(16) // bits
    expect(wav.getUint32(40, true)).toBe(320) // data bytes
  })
})

describe('Segmenter (voice activity detection)', () => {
  it('returns one phrase after the speaker pauses, with lead-in', () => {
    const seg = new Segmenter({ sampleRate: RATE })
    const results: Float32Array[] = []
    for (const f of [...frames(1, 0.002), ...frames(1.2, 0.3), ...frames(1, 0.002)]) {
      const r = seg.push(f)
      if (r) results.push(r)
    }
    expect(results).toHaveLength(1)
    const seconds = (results[0]?.length ?? 0) / RATE
    expect(seconds).toBeGreaterThan(1.2)
    expect(seconds).toBeLessThan(2.4)
  })

  it('ignores short blips and steady background noise', () => {
    const seg = new Segmenter({ sampleRate: RATE })
    let found = 0
    for (const f of [...frames(1, 0.002), ...frames(0.15, 0.3), ...frames(1, 0.002), ...frames(2, 0.006)]) {
      if (seg.push(f)) found++
    }
    expect(found).toBe(0)
  })

  it('cuts very long phrases at the maximum length', () => {
    const seg = new Segmenter({ sampleRate: RATE, maxMs: 2000 })
    let found = 0
    for (const f of [...frames(0.5, 0.002), ...frames(5, 0.3)]) if (seg.push(f)) found++
    expect(found).toBeGreaterThanOrEqual(2)
  })
})
