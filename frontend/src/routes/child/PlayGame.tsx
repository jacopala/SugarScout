import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { Fireworks } from '../../components/Fireworks'
import { HelpButton } from '../../components/HelpButton'
import { HeartIcon } from '../../components/Icons'
import { pickColor } from '../../lib/color'
import { useChildStatus } from '../../lib/queries'

/**
 * Sky Pop: a short, gentle tapping game. Bubbles float up; tap them to pop.
 * No way to lose, no penalties, one 30-second round at a time. The Help button
 * and any care-plan reminder stay on screen while playing.
 */

const ROUND_S = 30
const SPAWN_MS = 650
const COLORS = ['#7766C6', '#F27BA4', '#5CC28C', '#4FA3F7', '#FF8A3D']
const BEST_KEY = 'sugarscout.skypop.best'
const STAR_GOLD = '#FFC212'

interface Bubble {
  id: number
  x: number // % from the left
  size: number // px
  speed: number // px per second
  born: number // ms since round start
  color: string
  star: boolean
}

interface Pop {
  id: number
  x: number
  y: number
  points: number
  color: string
}

type Phase = 'ready' | 'playing' | 'done'

function readBest(): number {
  try {
    return Number(localStorage.getItem(BEST_KEY)) || 0
  } catch {
    return 0
  }
}

function saveBest(score: number) {
  try {
    localStorage.setItem(BEST_KEY, String(score))
  } catch {
    // Private mode or storage blocked: the best score just isn't remembered.
  }
}

export function PlayGame() {
  const navigate = useNavigate()
  const status = useChildStatus()
  const stageRef = useRef<HTMLDivElement>(null)
  const [phase, setPhase] = useState<Phase>('ready')
  const [score, setScore] = useState(0)
  const [best, setBest] = useState(readBest)
  const [newBest, setNewBest] = useState(false)
  const [bubbles, setBubbles] = useState<Bubble[]>([])
  const [pops, setPops] = useState<Pop[]>([])
  const [elapsed, setElapsed] = useState(0) // ms of play, paused while the tab is hidden
  const [fireworks, setFireworks] = useState(0)
  const nextId = useRef(1)
  const lastSpawn = useRef(0)
  const scoreRef = useRef(0)
  const elapsedRef = useRef(0)

  const reduced =
    typeof window !== 'undefined' && (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)

  const finish = useCallback(() => {
    setPhase('done')
    setBubbles([])
    const final = scoreRef.current
    if (final > readBest()) {
      saveBest(final)
      setBest(final)
      setNewBest(true)
      setFireworks((n) => n + 1)
    }
  }, [])

  // Stage height (for where bubbles start and leave), kept current on resize.
  const [stageH, setStageH] = useState(600)
  const stageHRef = useRef(600)
  useEffect(() => {
    const el = stageRef.current
    if (!el) return
    const measure = () => {
      stageHRef.current = el.clientHeight || 600
      setStageH(stageHRef.current)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const yAt = (b: Bubble, t: number, h: number) => h + b.size - ((t - b.born) / 1000) * b.speed

  // The game clock: one animation-frame loop while playing, paused while the tab is
  // hidden. Side effects stay out of state updaters so React can run them twice safely.
  useEffect(() => {
    if (phase !== 'playing') return
    let raf = 0
    let last = performance.now()
    const step = (now: number) => {
      const dt = document.hidden ? 0 : Math.min(now - last, 100)
      last = now
      const t = elapsedRef.current + dt
      if (t >= ROUND_S * 1000) {
        elapsedRef.current = ROUND_S * 1000
        setElapsed(ROUND_S * 1000)
        finish()
        return
      }
      elapsedRef.current = t
      let spawned: Bubble | null = null
      if (t - lastSpawn.current >= SPAWN_MS) {
        lastSpawn.current = t
        const star = Math.random() < 0.14
        spawned = {
          id: nextId.current++,
          x: 8 + Math.random() * 84,
          size: star ? 68 : 58 + Math.random() * 26,
          speed: (reduced ? 70 : 110) + Math.random() * (reduced ? 30 : 90),
          born: t,
          color: star ? STAR_GOLD : pickColor(COLORS),
          star,
        }
      }
      const h = stageHRef.current
      setBubbles((bs) => {
        // Bubbles that float off the top just leave: no penalty for missing one.
        const kept = bs.filter((b) => yAt(b, t, h) > -b.size)
        if (spawned) return [...kept, spawned]
        return kept.length === bs.length ? bs : kept
      })
      setElapsed(t)
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [phase, finish, reduced])

  const y = (b: Bubble) => yAt(b, elapsed, stageH)

  function start() {
    nextId.current = 1
    lastSpawn.current = -SPAWN_MS
    scoreRef.current = 0
    setScore(0)
    elapsedRef.current = 0
    setElapsed(0)
    setBubbles([])
    setPops([])
    setNewBest(false)
    setPhase('playing')
  }

  function pop(b: Bubble) {
    const points = b.star ? 3 : 1
    scoreRef.current += points
    setScore(scoreRef.current)
    setBubbles((bs) => bs.filter((o) => o.id !== b.id))
    const p: Pop = { id: b.id, x: b.x, y: y(b), points, color: b.star ? '#E0A800' : b.color }
    setPops((ps) => [...ps, p])
    setTimeout(() => setPops((ps) => ps.filter((o) => o.id !== p.id)), 600)
  }

  const left = Math.max(0, Math.ceil(ROUND_S - elapsed / 1000))

  return (
    <main className="game-screen">
      <header className="game-top">
        <Link className="game-back" to="/child/scout">
          ← Scout
        </Link>
        <div className="game-stats" aria-live="off">
          <span>
            <strong>{score}</strong> popped
          </span>
          {phase === 'playing' ? (
            <span>
              <strong>{left}</strong>s
            </span>
          ) : null}
        </div>
        <HelpButton onSent={(reply) => navigate('/child/scout', { state: { greeting: reply, emotion: 'calm' } })} />
      </header>

      {status.data?.reminder ? (
        <div className="child-reminder game-reminder" role="status">
          <HeartIcon size={22} />
          <p>{status.data.reminder}</p>
        </div>
      ) : null}

      <div className="game-stage" ref={stageRef}>
        {bubbles.map((b) => (
          <button
            key={b.id}
            type="button"
            className={b.star ? 'bubble bubble-star' : 'bubble'}
            style={{
              left: `${b.x}%`,
              width: b.size,
              height: b.size,
              transform: `translate(-50%, ${y(b)}px)`,
              ['--bubble' as string]: b.color,
            }}
            aria-label={b.star ? 'Gold star bubble, 3 points' : 'Bubble'}
            onPointerDown={(e) => {
              e.preventDefault()
              pop(b)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') pop(b)
            }}
          >
            {b.star ? '★' : null}
          </button>
        ))}
        {pops.map((p) => (
          <span
            key={p.id}
            className="bubble-pop"
            style={{ left: `${p.x}%`, top: p.y, color: p.color }}
            aria-hidden="true"
          >
            +{p.points}
          </span>
        ))}

        {phase === 'ready' ? (
          <div className="game-card">
            <h1>Sky Pop</h1>
            <p>Pop as many bubbles as you can in {ROUND_S} seconds. Gold stars are worth 3!</p>
            {best > 0 ? <p className="game-best">Your best: {best}</p> : null}
            <button className="btn btn-primary btn-block" onClick={start}>
              Play
            </button>
          </div>
        ) : null}

        {phase === 'done' ? (
          <div className="game-card" role="status">
            <h1>{newBest ? 'New best!' : 'Nice popping!'}</h1>
            <p className="game-score">
              You popped <strong>{score}</strong>
            </p>
            {!newBest && best > 0 ? <p className="game-best">Your best: {best}</p> : null}
            <button className="btn btn-primary btn-block" onClick={start}>
              Play again
            </button>
            <Link className="mood-skip" to="/child/scout">
              Back to Scout
            </Link>
          </div>
        ) : null}
      </div>
      {fireworks > 0 ? <Fireworks key={fireworks} onDone={() => setFireworks(0)} /> : null}
    </main>
  )
}
