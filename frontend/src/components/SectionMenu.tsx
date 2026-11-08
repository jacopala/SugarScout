import { useEffect, useRef, useState } from 'react'

import { CloseIcon, MenuIcon } from './Icons'

export interface MenuSection {
  id: string // heading id to jump to
  label: string
}

/** Sandwich menu for the parent dashboard: plain text items; the section you're on glows. */
export function SectionMenu({
  sections,
  extra,
}: {
  sections: MenuSection[]
  extra?: { label: string; onSelect: () => void }[]
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState<string>(sections[0]?.id ?? '')
  const wrapRef = useRef<HTMLDivElement>(null)

  // Scroll spy: the heading nearest the top of the screen is the current section.
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return
    const visible = new Map<string, number>()
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) visible.set(e.target.id, e.boundingClientRect.top)
          else visible.delete(e.target.id)
        }
        const top = [...visible.entries()].sort((a, b) => a[1] - b[1])[0]
        if (top) setActive(top[0])
      },
      { rootMargin: '0px 0px -55% 0px' },
    )
    for (const s of sections) {
      const el = document.getElementById(s.id)
      if (el) obs.observe(el)
    }
    return () => obs.disconnect()
  }, [sections])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  function go(id: string) {
    setOpen(false)
    setActive(id)
    document.getElementById(id)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="section-menu" ref={wrapRef}>
      <button
        className="menu-btn"
        aria-expanded={open}
        aria-controls="section-menu-panel"
        aria-label={open ? 'Close menu' : 'Open menu'}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <CloseIcon size={22} /> : <MenuIcon size={22} />}
      </button>
      {open ? (
        <nav id="section-menu-panel" className="menu-panel" aria-label="Dashboard sections">
          <ul>
            {sections.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className="menu-item"
                  aria-current={active === s.id ? 'true' : undefined}
                  onClick={(e) => {
                    e.preventDefault()
                    go(s.id)
                  }}
                >
                  {s.label}
                </a>
              </li>
            ))}
            {extra?.map((x) => (
              <li key={x.label}>
                <button
                  className="menu-item"
                  onClick={() => {
                    setOpen(false)
                    x.onSelect()
                  }}
                >
                  {x.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </div>
  )
}
