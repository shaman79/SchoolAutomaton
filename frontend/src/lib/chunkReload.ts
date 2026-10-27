/**
 * After a deploy the previous build's hashed chunks are gone. A tab (or the installed PWA) that is
 * still running the old build then fails to lazy-load the next screen, and taps seem to do nothing.
 * Fix: on such a failure, reload the page ONCE — straight to the screen the child was going to — so
 * the new build loads. A timestamp in sessionStorage stops a reload loop if the reload doesn't help.
 */
import type { Router } from 'vue-router'

const RELOAD_KEY = 'sa_chunk_reload_at'
/** No second automatic reload within this window (the first one evidently didn't help). */
export const RELOAD_GUARD_MS = 30_000

const CHUNK_ERROR_PATTERNS = [
  /Failed to fetch dynamically imported module/i, // Chromium
  /error loading dynamically imported module/i, // Firefox
  /Importing a module script failed/i, // Safari
  /Unable to preload CSS/i, // Vite's CSS preload
  /Loading (CSS )?chunk [\w-]+ failed/i,
  /'text\/html' is not a valid JavaScript MIME type/i, // the SPA fallback served instead of a chunk
]

export function isChunkLoadError(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false
  const e = err as { name?: unknown; message?: unknown }
  if (e.name === 'ChunkLoadError') return true
  const msg = typeof e.message === 'string' ? e.message : ''
  return CHUNK_ERROR_PATTERNS.some((re) => re.test(msg))
}

interface ReloadDeps {
  storage?: Pick<Storage, 'getItem' | 'setItem'> | null
  now?: () => number
  navigate?: (url: string) => void
}

function safeSessionStorage(): Pick<Storage, 'getItem' | 'setItem'> | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

/** Reload to `target` unless we already did so within RELOAD_GUARD_MS. Returns whether it reloads.
 *  Without working storage we can't guard against a loop, so we don't reload at all. */
export function reloadOnce(target: string, deps: ReloadDeps = {}): boolean {
  const storage = deps.storage === undefined ? safeSessionStorage() : deps.storage
  const now = (deps.now ?? Date.now)()
  if (!storage) return false
  try {
    const last = Number(storage.getItem(RELOAD_KEY) ?? 0)
    if (last && now - last < RELOAD_GUARD_MS) return false
    storage.setItem(RELOAD_KEY, String(now))
  } catch {
    return false
  }
  ;(deps.navigate ?? navigateFully)(target)
  return true
}

function navigateFully(url: string): void {
  if (url === window.location.href) window.location.reload()
  else window.location.assign(url)
}

/**
 * Wire it up: Vite's `vite:preloadError` (a chunk or its CSS failed to preload) and the router's
 * error hook (the lazy route component itself failed). `onGiveUp` runs when the guard says no — e.g.
 * to tell the learner to reload by hand.
 */
export function installChunkReload(
  router: Router,
  onGiveUp: () => void = () => {},
  deps: ReloadDeps = {},
): void {
  // The screen a navigation is heading to, so a failed lazy load reloads straight into it.
  let pendingTarget: string | null = null
  router.beforeEach((to) => {
    pendingTarget = to.fullPath
  })
  router.afterEach(() => {
    pendingTarget = null
  })

  window.addEventListener('vite:preloadError', (event) => {
    if (reloadOnce(pendingTarget ?? window.location.href, deps)) {
      event.preventDefault() // reloading anyway: don't also throw into the app
      return
    }
    // Not reloading again: during a navigation the error reaches router.onError below (which tells
    // the learner); outside one, tell them here.
    if (!pendingTarget) onGiveUp()
  })

  router.onError((err, to) => {
    if (!isChunkLoadError(err)) return
    if (!reloadOnce(to?.fullPath ?? pendingTarget ?? window.location.href, deps)) onGiveUp()
  })
}
