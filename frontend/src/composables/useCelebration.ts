/**
 * Centralizes celebratory feedback (XP pops, level-ups, badge unlocks, streaks).
 * It is the SINGLE place that decides whether to animate — every celebratory
 * sequence (GSAP confetti, Lottie reward, sound) MUST go through here so it
 * uniformly honors the reduced-motion preference and the per-profile `sound`
 * toggle (SPEC: one reduced-motion composable gates ALL motion).
 *
 * GSAP is imported lazily so it stays out of the initial bundle and only loads
 * on the first real celebration (typically the Results route).
 */
import { useReducedMotion } from '@/composables/useReducedMotion'
import { usePrefsStore } from '@/stores/prefs'

export interface ConfettiOptions {
  /** Source element to burst from; defaults to viewport center. */
  origin?: HTMLElement | null
  /** Particle count (scaled down automatically on small/low-power screens). */
  count?: number
  /** Brand-ish palette; falls back to design tokens. */
  colors?: string[]
}

const DEFAULT_COLORS = ['#6c4cff', '#ff7ac6', '#18c29c', '#ffb020', '#38b6ff']

/** Best-effort sound cue. No-op if sound is disabled or audio is unavailable. */
function playCue(name: 'correct' | 'levelup' | 'badge' | 'streak', enabled: boolean): void {
  if (!enabled || typeof window === 'undefined') return
  // Sound asset wiring is owned by the audio layer; we only honor the toggle and
  // expose the hook. Swallow everything — audio must never break the UI.
  try {
    const w = window as unknown as { __saPlayCue?: (n: string) => void }
    w.__saPlayCue?.(name)
  } catch {
    /* ignore */
  }
}

export function useCelebration() {
  const { reduced } = useReducedMotion()
  const prefs = usePrefsStore()

  const canAnimate = () => !reduced.value
  const canSound = () => prefs.sound

  /**
   * Fire a confetti burst. Resolves when finished (immediately under reduced
   * motion). Never throws — celebration failures must be invisible.
   */
  async function confetti(opts: ConfettiOptions = {}): Promise<void> {
    if (!canAnimate() || typeof document === 'undefined') return
    try {
      const { gsap } = await import('gsap')
      const colors = opts.colors ?? DEFAULT_COLORS
      const count = Math.min(opts.count ?? 80, window.innerWidth < 480 ? 50 : 120)

      const rect = opts.origin?.getBoundingClientRect()
      const ox = rect ? rect.left + rect.width / 2 : window.innerWidth / 2
      const oy = rect ? rect.top + rect.height / 2 : window.innerHeight / 3

      const layer = document.createElement('div')
      layer.setAttribute('aria-hidden', 'true')
      layer.style.cssText =
        'position:fixed;inset:0;pointer-events:none;z-index:80;overflow:hidden;'
      document.body.appendChild(layer)

      const pieces: HTMLElement[] = []
      for (let i = 0; i < count; i++) {
        const p = document.createElement('span')
        const size = 6 + Math.random() * 8
        p.style.cssText = `position:absolute;left:${ox}px;top:${oy}px;width:${size}px;height:${size * 0.5}px;background:${colors[i % colors.length]};border-radius:2px;will-change:transform,opacity;`
        layer.appendChild(p)
        pieces.push(p)
      }

      await new Promise<void>((resolve) => {
        gsap.to(pieces, {
          duration: () => 0.9 + Math.random() * 0.7,
          x: () => (Math.random() - 0.5) * window.innerWidth,
          y: () => window.innerHeight * (0.5 + Math.random() * 0.5),
          rotation: () => Math.random() * 540,
          opacity: 0,
          ease: 'power2.out',
          stagger: 0.004,
          onComplete: resolve,
        })
      })
      layer.remove()
    } catch {
      /* gsap missing or DOM unavailable — silently skip */
    }
  }

  /** Convenience wrappers used by the gamification UI (F4) and Results view (F3). */
  async function celebrateCorrect(origin?: HTMLElement | null) {
    playCue('correct', canSound())
    if (canAnimate()) await confetti({ origin, count: 36 })
  }
  async function celebrateLevelUp(origin?: HTMLElement | null) {
    playCue('levelup', canSound())
    await confetti({ origin, count: 110 })
  }
  async function celebrateBadge(origin?: HTMLElement | null) {
    playCue('badge', canSound())
    await confetti({ origin, count: 80, colors: ['#ffb020', '#ff7ac6', '#6c4cff'] })
  }
  function celebrateStreak() {
    playCue('streak', canSound())
  }

  return {
    reduced,
    canAnimate,
    canSound,
    confetti,
    celebrateCorrect,
    celebrateLevelUp,
    celebrateBadge,
    celebrateStreak,
  }
}
