import { useCallback, useEffect, useRef, useState } from 'react'

import { apiPost, apiPostAudio, type VoiceTurn } from '../api'
import { Segmenter } from './segmenter'
import { ASR_RATE, downsample, encodeWav16 } from './wav'

/**
 * Voice states:
 * - off:       mic not started (browsers need a tap first)
 * - idle:      listening for "Hey Scout"; clips go to the server, which ignores
 *              anything without the wake phrase
 * - awake:     Scout heard its name; the next phrase is the request
 * - thinking:  waiting for Scout's reply
 * - speaking:  Scout is talking (the mic is ignored so Scout doesn't hear itself)
 */
export type VoiceState = 'off' | 'starting' | 'idle' | 'awake' | 'thinking' | 'speaking'

export interface ScoutVoice {
  state: VoiceState
  supported: boolean
  error: string | null
  checking: boolean // a clip is being checked for the wake phrase
  micOn: boolean
  start: () => Promise<void>
  stop: () => void
  wake: () => void // tap-to-talk: skip the wake word for the next phrase
  say: (text: string, emotion?: string) => Promise<void>
}

const AWAKE_MS = 8_000

export function voiceSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof AudioWorkletNode !== 'undefined' &&
    Boolean(navigator.mediaDevices?.getUserMedia)
  )
}

function playWav(base64: string): Promise<void> {
  return new Promise((resolve) => {
    const audio = new Audio(`data:audio/wav;base64,${base64}`)
    audio.onended = () => resolve()
    audio.onerror = () => resolve()
    audio.play().catch(() => resolve())
  })
}

function browserSpeak(text: string): Promise<void> {
  return new Promise((resolve) => {
    if (typeof speechSynthesis === 'undefined') return resolve()
    const u = new SpeechSynthesisUtterance(text.replace(/\p{Extended_Pictographic}/gu, ''))
    u.rate = 1
    u.pitch = 1.15
    u.onend = () => resolve()
    u.onerror = () => resolve()
    speechSynthesis.speak(u)
  })
}

export function useScoutVoice(onTurn: (turn: VoiceTurn) => void): ScoutVoice {
  const [state, setStateRaw] = useState<VoiceState>('off')
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const [micOn, setMicOn] = useState(false)
  const supported = voiceSupported()

  const stateRef = useRef<VoiceState>('off')
  const ctxRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const segRef = useRef<Segmenter | null>(null)
  const inFlight = useRef(false)
  const awakeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onTurnRef = useRef(onTurn)
  useEffect(() => {
    onTurnRef.current = onTurn
  }, [onTurn])

  const setState = useCallback((s: VoiceState) => {
    stateRef.current = s
    setStateRaw(s)
  }, [])

  const listening = () => ctxRef.current !== null

  const goIdleOrOff = useCallback(() => {
    setState(listening() ? 'idle' : 'off')
  }, [setState])

  const goAwake = useCallback(
    (ms = AWAKE_MS) => {
      if (awakeTimer.current) clearTimeout(awakeTimer.current)
      setState('awake')
      awakeTimer.current = setTimeout(() => {
        if (stateRef.current === 'awake') goIdleOrOff()
      }, ms)
    },
    [setState, goIdleOrOff],
  )

  const speakReply = useCallback(
    async (text: string | null, audio: string | null) => {
      if (!text) return
      setState('speaking')
      segRef.current?.reset()
      if (audio) await playWav(audio)
      else await browserSpeak(text)
    },
    [setState],
  )

  const say = useCallback(
    async (text: string, emotion = 'neutral') => {
      let audio: string | null
      try {
        audio = (await apiPost<{ audio: string | null }>('/voice/speak', { text, emotion })).audio
      } catch {
        audio = null // fall back to the browser's own voice
      }
      await speakReply(text, audio)
      goIdleOrOff()
    },
    [speakReply, goIdleOrOff],
  )

  const sendClip = useCallback(
    async (clip: Float32Array, rate: number) => {
      if (inFlight.current) return
      const wasAwake = stateRef.current === 'awake'
      inFlight.current = true
      if (wasAwake) {
        if (awakeTimer.current) clearTimeout(awakeTimer.current)
        setState('thinking')
      } else {
        setChecking(true)
      }
      try {
        const wav = encodeWav16(downsample(clip, rate, ASR_RATE))
        const turn = await apiPostAudio<VoiceTurn>(`/voice/turn?awake=${wasAwake}`, wav)
        if (!turn.heard) {
          if (wasAwake) goIdleOrOff()
          return
        }
        setError(null)
        onTurnRef.current(turn)
        await speakReply(turn.reply, turn.audio)
        if (turn.awake_for_s > 0) goAwake(turn.awake_for_s * 1000)
        else goIdleOrOff()
      } catch {
        setError('Scout couldn’t hear that clearly. Try again, or type instead.')
        goIdleOrOff()
      } finally {
        inFlight.current = false
        setChecking(false)
      }
    },
    [setState, goIdleOrOff, goAwake, speakReply],
  )

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    void ctxRef.current?.close()
    ctxRef.current = null
    segRef.current = null
    if (awakeTimer.current) clearTimeout(awakeTimer.current)
    setMicOn(false)
    setState('off')
  }, [setState])

  const start = useCallback(async () => {
    if (!supported || ctxRef.current) return
    setError(null)
    setState('starting')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      const ctx = new AudioContext()
      await ctx.audioWorklet.addModule('/vad-worklet.js')
      const source = ctx.createMediaStreamSource(stream)
      const node = new AudioWorkletNode(ctx, 'scout-capture')
      const sink = ctx.createGain()
      sink.gain.value = 0 // keep the graph pulling audio without playing the mic back
      source.connect(node).connect(sink).connect(ctx.destination)
      const seg = new Segmenter({ sampleRate: ctx.sampleRate })
      node.port.onmessage = (e: MessageEvent<Float32Array>) => {
        const s = stateRef.current
        if (s === 'thinking' || s === 'speaking' || s === 'off' || s === 'starting') return
        const clip = seg.push(e.data)
        if (clip) void sendClip(clip, ctx.sampleRate)
      }
      streamRef.current = stream
      ctxRef.current = ctx
      segRef.current = seg
      if (ctx.state === 'suspended') await ctx.resume()
      setMicOn(true)
      setState('idle')
    } catch (err) {
      const denied = err instanceof DOMException && err.name === 'NotAllowedError'
      setError(denied ? 'Scout can’t hear you. Please allow the microphone.' : 'The microphone didn’t start.')
      stop()
    }
  }, [supported, setState, sendClip, stop])

  const wake = useCallback(() => {
    if (!ctxRef.current) {
      void start().then(() => goAwake())
      return
    }
    if (stateRef.current === 'idle' || stateRef.current === 'awake') goAwake()
  }, [start, goAwake])

  useEffect(() => stop, [stop])

  return { state, supported, error, checking, micOn, start, stop, wake, say }
}
