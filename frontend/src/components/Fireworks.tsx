import { useEffect, useRef } from 'react'

import { pickColor } from '../lib/color'

const DURATION_MS = 2600

interface Spark {
  x: number
  y: number
  vx: number
  vy: number
  life: number
  color: string
  size: number
}

function burst(sparks: Spark[], x: number, y: number, count: number) {
  const color = pickColor()
  for (let i = 0; i < count; i++) {
    const angle = (Math.PI * 2 * i) / count + Math.random() * 0.2
    const speed = 2.2 + Math.random() * 3.2
    sparks.push({
      x,
      y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      life: 1,
      color: Math.random() < 0.25 ? pickColor() : color,
      size: 2 + Math.random() * 2.5,
    })
  }
}

/**
 * A short full-screen fireworks show. Mount it with a new `key` to play it again;
 * it calls `onDone` when finished. Never blocks taps (pointer-events: none), and
 * with reduced motion it shows a single gentle burst instead of a show.
 */
export function Fireworks({ onDone }: { onDone?: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const done = useRef(onDone)
  useEffect(() => {
    done.current = onDone
  }, [onDone])

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) {
      done.current?.()
      return
    }
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const w = window.innerWidth
    const h = window.innerHeight
    canvas.width = w * dpr
    canvas.height = h * dpr
    ctx.scale(dpr, dpr)

    const sparks: Spark[] = []
    const shots = reduced ? 1 : 6
    const timers: ReturnType<typeof setTimeout>[] = []
    for (let i = 0; i < shots; i++) {
      timers.push(
        setTimeout(
          () => burst(sparks, w * (0.2 + Math.random() * 0.6), h * (0.15 + Math.random() * 0.35), reduced ? 24 : 46),
          reduced ? 0 : i * 320,
        ),
      )
    }

    let raf = 0
    const start = performance.now()
    const tick = (now: number) => {
      ctx.clearRect(0, 0, w, h)
      for (const s of sparks) {
        s.vy += 0.06 // gravity
        s.vx *= 0.985
        s.vy *= 0.985
        s.x += s.vx
        s.y += s.vy
        s.life -= reduced ? 0.012 : 0.016
        if (s.life <= 0) continue
        ctx.globalAlpha = s.life
        ctx.fillStyle = s.color
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.size, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalAlpha = 1
      if (now - start < DURATION_MS) {
        raf = requestAnimationFrame(tick)
      } else {
        done.current?.()
      }
    }
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      timers.forEach(clearTimeout)
    }
  }, [])

  return <canvas ref={canvasRef} className="fireworks" aria-hidden="true" />
}
