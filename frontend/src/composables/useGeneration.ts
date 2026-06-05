/**
 * Thin, view-facing wrapper around the generation Pinia store (frozen). It owns the SSE lifecycle
 * for the LoadingView: it kicks off generation, exposes friendly reactive progress (a live
 * checklist of plan sections as `section` events arrive, an overall progress %, and a
 * playful status phase), and resolves the destination route once the backend says `ready`.
 *
 * The store is the source of truth; this composable only adds presentation-shaped derivations
 * and the start/stop/retry ergonomics the view needs. All motion is gated elsewhere (the
 * reduced-motion composable / design-system primitives) so this stays logic-only.
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

import { useGenerationStore } from '@/stores/generation'

export interface GenerationChecklistItem {
  ordinal: number
  kind: string
  title?: string
  /** True once the matching `section` SSE event has populated a title (i.e. it has been built). */
  done: boolean
}

export function useGeneration(requestId: string) {
  const gen = useGenerationStore()

  // Track which ordinals have actually been emitted as completed `section` events. The store
  // seeds the list from the `plan` event (titles may be absent); a real `section` event later
  // fills the title — that transition is our "this part is done" signal for the checklist tick.
  const builtOrdinals = ref<Set<number>>(new Set())

  /** Begin generation + SSE. Safe to call once on mount; resets any prior run. */
  async function begin(): Promise<void> {
    builtOrdinals.value = new Set()
    await gen.start(requestId)
  }

  function retry(): Promise<void> {
    return begin()
  }

  function stop(): void {
    gen.stop()
  }

  // The store mutates `sections` in place as `section` events arrive (it merges by ordinal).
  // We treat "has a title" as built; the plan seed usually lacks titles until the section lands.
  const checklist = computed<GenerationChecklistItem[]>(() =>
    [...gen.sections]
      .sort((a, b) => a.ordinal - b.ordinal)
      .map((s) => ({
        ordinal: s.ordinal,
        kind: s.kind,
        title: s.title,
        done: !!s.title || builtOrdinals.value.has(s.ordinal),
      })),
  )

  const totalSections = computed(() => gen.sections.length)
  const builtCount = computed(() => checklist.value.filter((s) => s.done).length)

  /** 0..100. Indeterminate (returns null) until a plan with sections has arrived. */
  const progressPct = computed<number | null>(() => {
    if (gen.status === 'ready') return 100
    if (totalSections.value === 0) return null
    return Math.round((builtCount.value / totalSections.value) * 100)
  })

  /** A coarse phase used to pick encouraging copy + visuals. */
  const phase = computed<'starting' | 'planning' | 'building' | 'ready' | 'error'>(() => {
    if (gen.status === 'error') return 'error'
    if (gen.status === 'ready') return 'ready'
    if (gen.status === 'idle' || gen.status === 'queued') return 'starting'
    return totalSections.value === 0 ? 'planning' : 'building'
  })

  const isError = computed(() => gen.status === 'error')
  const isReady = computed(() => gen.status === 'ready')
  const errorMessage = computed(() => gen.message)

  /** Where to go once ready. `null` until we know (and until a valid id is present). */
  const destination = computed<RouteLocationRaw | null>(() => {
    if (gen.status !== 'ready') return null
    if (gen.resultMode === 'test' && gen.quizId != null) {
      return { name: 'test', params: { sessionId: requestId } }
    }
    if (gen.lessonId != null) {
      return { name: 'lesson', params: { sessionId: requestId } }
    }
    return null
  })

  onBeforeUnmount(stop)

  return {
    // lifecycle
    begin,
    retry,
    stop,
    // raw store status passthrough (typed)
    status: computed(() => gen.status),
    // derived presentation state
    checklist,
    totalSections,
    builtCount,
    progressPct,
    phase,
    isError,
    isReady,
    errorMessage,
    destination,
    resultMode: computed(() => gen.resultMode),
  }
}
