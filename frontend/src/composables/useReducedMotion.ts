/**
 * Single source of truth for "should we animate?" — OR of the OS preference and the per-profile
 * toggle (usePrefs writes `data-reduced-motion` on <html>). All motion (vueuse/motion, GSAP, Lottie)
 * must gate on this (SPEC frontend: one reduced-motion composable).
 */
import { onMounted, onUnmounted, ref } from 'vue'

export function useReducedMotion() {
  const reduced = ref(false)

  const compute = () => {
    const os =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const pref = document.documentElement.dataset.reducedMotion === 'true'
    reduced.value = os || pref
  }

  let mql: MediaQueryList | null = null
  let observer: MutationObserver | null = null

  onMounted(() => {
    compute()
    mql = window.matchMedia('(prefers-reduced-motion: reduce)')
    mql.addEventListener('change', compute)
    observer = new MutationObserver(compute)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-reduced-motion'],
    })
  })
  onUnmounted(() => {
    mql?.removeEventListener('change', compute)
    observer?.disconnect()
  })

  return { reduced }
}
