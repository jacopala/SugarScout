import { rms } from './wav'

export interface SegmenterOptions {
  sampleRate: number
  startMs?: number // loud for this long => speech started
  silenceMs?: number // quiet for this long => phrase ended
  minMs?: number // ignore blips shorter than this
  maxMs?: number // cut very long phrases
  prerollMs?: number // keep this much audio from before speech started
  minThreshold?: number // absolute floor for the speech threshold (RMS)
  floorMultiplier?: number // threshold = noise floor x this
}

/**
 * Energy-based voice activity detection. Feed it mic frames; it returns a whole spoken
 * phrase (with a little lead-in) once the speaker pauses. Pure and synchronous, so it's
 * unit-testable without a microphone.
 */
export class Segmenter {
  private readonly o: Required<SegmenterOptions>
  private floor = -1
  private preroll: Float32Array[] = []
  private prerollSamples = 0
  private segment: Float32Array[] = []
  private segmentSamples = 0
  private loudMs = 0
  private quietMs = 0
  private speechMs = 0
  private inSpeech = false

  constructor(options: SegmenterOptions) {
    this.o = {
      startMs: 100,
      silenceMs: 700,
      minMs: 300,
      maxMs: 8000,
      prerollMs: 300,
      minThreshold: 0.012,
      floorMultiplier: 3.5,
      ...options,
    }
  }

  get speaking(): boolean {
    return this.inSpeech
  }

  get threshold(): number {
    return Math.max(this.o.minThreshold, (this.floor < 0 ? 0 : this.floor) * this.o.floorMultiplier)
  }

  reset(): void {
    this.preroll = []
    this.prerollSamples = 0
    this.segment = []
    this.segmentSamples = 0
    this.loudMs = 0
    this.quietMs = 0
    this.speechMs = 0
    this.inSpeech = false
  }

  /** Returns a finished phrase, or null. */
  push(frame: Float32Array): Float32Array | null {
    const ms = (frame.length / this.o.sampleRate) * 1000
    const level = rms(frame)
    const loud = level > this.threshold

    if (!this.inSpeech) {
      // Track background noise while nobody is talking: drop quickly to quieter rooms,
      // rise slowly so the start of speech doesn't count as "noise".
      if (this.floor < 0) this.floor = level
      else if (level < this.floor) this.floor = this.floor * 0.8 + level * 0.2
      else this.floor = this.floor * 0.995 + level * 0.005
      this.preroll.push(frame)
      this.prerollSamples += frame.length
      const maxPre = (this.o.prerollMs / 1000) * this.o.sampleRate
      while (this.prerollSamples - (this.preroll[0]?.length ?? 0) > maxPre) {
        this.prerollSamples -= this.preroll.shift()?.length ?? 0
      }
      this.loudMs = loud ? this.loudMs + ms : 0
      if (this.loudMs >= this.o.startMs) {
        this.inSpeech = true
        this.segment = [...this.preroll]
        this.segmentSamples = this.prerollSamples
        this.speechMs = this.loudMs
        this.quietMs = 0
        this.preroll = []
        this.prerollSamples = 0
      }
      return null
    }

    this.segment.push(frame)
    this.segmentSamples += frame.length
    if (loud) {
      this.speechMs += ms
      this.quietMs = 0
    } else {
      this.quietMs += ms
    }

    const totalMs = (this.segmentSamples / this.o.sampleRate) * 1000
    if (this.quietMs >= this.o.silenceMs) {
      const out = this.speechMs >= this.o.minMs ? concat(this.segment, this.segmentSamples) : null
      this.reset()
      return out
    }
    if (totalMs >= this.o.maxMs) {
      // Still talking: hand over what we have and keep listening to the rest.
      const out = concat(this.segment, this.segmentSamples)
      this.segment = []
      this.segmentSamples = 0
      this.speechMs = 0
      this.quietMs = 0
      return out
    }
    return null
  }
}

function concat(frames: Float32Array[], length: number): Float32Array {
  const out = new Float32Array(length)
  let offset = 0
  for (const f of frames) {
    out.set(f, offset)
    offset += f.length
  }
  return out
}
