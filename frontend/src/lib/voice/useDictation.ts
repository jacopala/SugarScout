import { useCallback, useEffect, useRef, useState } from 'react'

import { apiPostAudio } from '../api'
import { Segmenter } from './segmenter'
import { ASR_RATE, downsample, encodeWav16 } from './wav'
import { voiceSupported } from './useScoutVoice'

const MAX_WAIT_MS = 10_000

/**
 * One-shot dictation ("What did you eat?"): listen for a single phrase, send it to
 * /voice/transcribe (no wake word, nothing stored), return the text.
 */
export function useDictation() {
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cleanup = useRef<(() => void) | null>(null)

  const stop = useCallback(() => {
    cleanup.current?.()
    cleanup.current = null
    setRecording(false)
  }, [])

  useEffect(() => stop, [stop])

  const listen = useCallback(async (): Promise<string | null> => {
    if (!voiceSupported()) {
      setError('This browser can’t use the microphone here. You can type instead.')
      return null
    }
    stop()
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      const ctx = new AudioContext()
      await ctx.audioWorklet.addModule('/vad-worklet.js')
      const source = ctx.createMediaStreamSource(stream)
      const node = new AudioWorkletNode(ctx, 'scout-capture')
      const sink = ctx.createGain()
      sink.gain.value = 0
      source.connect(node).connect(sink).connect(ctx.destination)
      if (ctx.state === 'suspended') await ctx.resume()
      setRecording(true)

      const clip = await new Promise<Float32Array | null>((resolve) => {
        const seg = new Segmenter({ sampleRate: ctx.sampleRate })
        const timer = setTimeout(() => resolve(null), MAX_WAIT_MS)
        node.port.onmessage = (e: MessageEvent<Float32Array>) => {
          const phrase = seg.push(e.data)
          if (phrase) {
            clearTimeout(timer)
            resolve(phrase)
          }
        }
        cleanup.current = () => {
          clearTimeout(timer)
          stream.getTracks().forEach((t) => t.stop())
          void ctx.close()
          resolve(null)
        }
      })
      const rate = ctx.sampleRate
      stop()
      if (!clip) return null

      setBusy(true)
      const { transcript } = await apiPostAudio<{ transcript: string }>(
        '/voice/transcribe',
        encodeWav16(downsample(clip, rate, ASR_RATE)),
      )
      return transcript || null
    } catch (err) {
      const denied = err instanceof DOMException && err.name === 'NotAllowedError'
      setError(denied ? 'Please allow the microphone, or type instead.' : 'Scout couldn’t hear that. Try again?')
      stop()
      return null
    } finally {
      setBusy(false)
    }
  }, [stop])

  return { recording, busy, error, listen, stop }
}
