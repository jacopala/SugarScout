/** Audio helpers for voice turns: resample mic audio to 16 kHz and wrap it as WAV. */

export const ASR_RATE = 16_000

/** Averaging resampler (good enough for speech; input rate is usually 44.1 or 48 kHz). */
export function downsample(input: Float32Array, inRate: number, outRate = ASR_RATE): Float32Array {
  if (inRate === outRate) return input
  if (inRate < outRate) throw new Error(`cannot upsample ${inRate} -> ${outRate}`)
  const ratio = inRate / outRate
  const outLength = Math.floor(input.length / ratio)
  const out = new Float32Array(outLength)
  for (let i = 0; i < outLength; i++) {
    const start = Math.floor(i * ratio)
    const end = Math.min(input.length, Math.floor((i + 1) * ratio))
    let sum = 0
    for (let j = start; j < end; j++) sum += input[j] ?? 0
    out[i] = end > start ? sum / (end - start) : 0
  }
  return out
}

/** 16-bit PCM mono WAV. */
export function encodeWav16(samples: Float32Array, rate = ASR_RATE): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const v = new DataView(buffer)
  const str = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(offset + i, s.charCodeAt(i))
  }
  str(0, 'RIFF')
  v.setUint32(4, 36 + samples.length * 2, true)
  str(8, 'WAVE')
  str(12, 'fmt ')
  v.setUint32(16, 16, true) // PCM chunk size
  v.setUint16(20, 1, true) // PCM
  v.setUint16(22, 1, true) // mono
  v.setUint32(24, rate, true)
  v.setUint32(28, rate * 2, true) // byte rate
  v.setUint16(32, 2, true) // block align
  v.setUint16(34, 16, true) // bits per sample
  str(36, 'data')
  v.setUint32(40, samples.length * 2, true)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i] ?? 0))
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return buffer
}

export function rms(frame: Float32Array): number {
  let sum = 0
  for (let i = 0; i < frame.length; i++) sum += (frame[i] ?? 0) ** 2
  return Math.sqrt(sum / Math.max(1, frame.length))
}
