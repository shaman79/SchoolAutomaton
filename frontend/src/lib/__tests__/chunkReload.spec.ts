/**
 * After a deploy, a stale tab's lazy screens fail to load: reload ONCE into the intended screen,
 * never in a loop.
 */
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { RELOAD_GUARD_MS, installChunkReload, isChunkLoadError, reloadOnce } from '@/lib/chunkReload'

function memoryStorage() {
  const m = new Map<string, string>()
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }
}

describe('isChunkLoadError', () => {
  it('recognises the browsers’ missing-chunk errors', () => {
    expect(isChunkLoadError(new TypeError('Failed to fetch dynamically imported module: /assets/LessonView-abc.js'))).toBe(true)
    expect(isChunkLoadError(new TypeError('error loading dynamically imported module'))).toBe(true)
    expect(isChunkLoadError(new TypeError('Importing a module script failed.'))).toBe(true)
    expect(isChunkLoadError(new Error('Unable to preload CSS for /assets/x.css'))).toBe(true)
  })

  it('ignores ordinary errors', () => {
    expect(isChunkLoadError(new Error('Navigation cancelled'))).toBe(false)
    expect(isChunkLoadError(null)).toBe(false)
    expect(isChunkLoadError('Failed to fetch dynamically imported module')).toBe(false)
  })
})

describe('reloadOnce', () => {
  it('reloads to the intended screen the first time', () => {
    const navigate = vi.fn()
    expect(reloadOnce('/lesson/abc', { storage: memoryStorage(), now: () => 1_000_000, navigate })).toBe(true)
    expect(navigate).toHaveBeenCalledWith('/lesson/abc')
  })

  it('does not reload again within the guard window (no loop)', () => {
    const storage = memoryStorage()
    const navigate = vi.fn()
    let now = 1_000_000
    reloadOnce('/lesson/abc', { storage, now: () => now, navigate })
    now += RELOAD_GUARD_MS - 1
    expect(reloadOnce('/lesson/abc', { storage, now: () => now, navigate })).toBe(false)
    expect(navigate).toHaveBeenCalledTimes(1)
  })

  it('may reload again once the window has passed (a later deploy)', () => {
    const storage = memoryStorage()
    const navigate = vi.fn()
    let now = 1_000_000
    reloadOnce('/a', { storage, now: () => now, navigate })
    now += RELOAD_GUARD_MS + 1
    expect(reloadOnce('/b', { storage, now: () => now, navigate })).toBe(true)
    expect(navigate).toHaveBeenLastCalledWith('/b')
  })

  it('a lazy screen whose chunk is gone reloads into that screen; a second failure tells the child', async () => {
    const missing = () => Promise.reject(new TypeError('Failed to fetch dynamically imported module: /assets/LessonView-old.js'))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/lesson/:id', component: missing },
      ],
    })
    const navigate = vi.fn()
    const gaveUp = vi.fn()
    const storage = memoryStorage()
    installChunkReload(router, gaveUp, { storage, now: () => 5_000_000, navigate })
    await router.push('/')

    await router.push('/lesson/abc').catch(() => {})
    expect(navigate).toHaveBeenCalledWith('/lesson/abc')
    expect(gaveUp).not.toHaveBeenCalled()

    await router.push('/lesson/abc').catch(() => {}) // the reload didn't help: no loop
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(gaveUp).toHaveBeenCalledTimes(1)
  })

  it('never reloads without storage to guard with', () => {
    const navigate = vi.fn()
    expect(reloadOnce('/a', { storage: null, navigate })).toBe(false)
    expect(navigate).not.toHaveBeenCalled()
  })
})
