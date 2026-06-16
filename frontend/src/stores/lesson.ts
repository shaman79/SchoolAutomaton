/**
 * Loads and holds the current lesson for the LessonReader.
 *
 * Progressive generation with PREFETCH: only section 0 is built up front; the rest are generated on
 * demand. To make "Continue" feel instant we pre-generate exactly ONE section ahead of what the
 * learner has revealed — so by the time they advance, the next part is usually already built.
 *
 * `revealedUpTo` is the reveal boundary the learner controls (separate from a section's gen_status):
 * a prefetched-but-not-yet-revealed section is held back until the learner advances, preserving the
 * paced, one-part-at-a-time reading flow.
 *
 * Images never block a part: a section's visuals arrive as `pending` placeholders and we poll the
 * section until each finishes generating, swapping them in incrementally.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '@/lib/api'
import type { Lesson, LessonSection } from '@/types/session'

const POLL_INTERVAL_MS = 2500
const POLL_DEADLINE_MS = 90_000

export const useLessonStore = defineStore('lesson', () => {
  const lesson = ref<Lesson | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  // The highest section ordinal the learner has chosen to reveal (section 0 is shown on load).
  const revealedUpTo = ref(0)
  // The ordinal of a MANUAL reveal currently awaiting generation (drives the visible spinner). null
  // when the next part was already prefetched (so advancing is instant).
  const generatingOrdinal = ref<number | null>(null)
  const failedOrdinal = ref<number | null>(null)

  // Dedupe concurrent fetches of the same section (a silent prefetch vs a manual reveal).
  const inflight = new Map<number, Promise<LessonSection>>()
  // Bumped on every load()/reset(); a slow prefetch from a previous lesson checks this before
  // splicing, so its (stale) result can't land in the newly-loaded lesson (both share the same
  // 12-section skeleton, so an ordinal match would otherwise overwrite the wrong section's content).
  let loadEpoch = 0
  // Active image-poll timers keyed by ordinal, so pending placeholders fill in incrementally.
  const pollTimers = new Map<number, ReturnType<typeof setTimeout>>()
  const pollDeadlines = new Map<number, number>()

  function _sorted(): LessonSection[] {
    return lesson.value ? [...lesson.value.sections].sort((a, b) => a.ordinal - b.ordinal) : []
  }
  function _lastOrdinal(): number {
    const s = _sorted()
    return s.length ? s[s.length - 1].ordinal : 0
  }
  function _byOrdinal(ordinal: number): LessonSection | undefined {
    return lesson.value?.sections.find((s) => s.ordinal === ordinal)
  }
  function _isReady(s: LessonSection | undefined): boolean {
    return !!s && (s.gen_status ?? 'ready') === 'ready'
  }
  function _hasPendingAssets(s: LessonSection | undefined): boolean {
    return !!s && s.assets.some((a) => a.status === 'pending')
  }

  function _spliceSection(section: LessonSection) {
    if (!lesson.value) return
    const sections = lesson.value.sections
    const idx = sections.findIndex((s) => s.ordinal === section.ordinal)
    if (idx >= 0) sections[idx] = section
    else sections.push(section)
  }

  function _stopPoll(ordinal: number) {
    const t = pollTimers.get(ordinal)
    if (t) clearTimeout(t)
    pollTimers.delete(ordinal)
    pollDeadlines.delete(ordinal)
  }

  /** Poll a revealed section while it still has pending image placeholders; swap them in as they
   *  finish. Gives up after a deadline so a stuck/failed image falls back to its alt text. */
  function pollSectionAssets(ordinal: number): void {
    if (!lesson.value) return
    if (!_hasPendingAssets(_byOrdinal(ordinal))) {
      _stopPoll(ordinal)
      return
    }
    if (pollTimers.has(ordinal)) return // already polling
    if (!pollDeadlines.has(ordinal)) pollDeadlines.set(ordinal, Date.now() + POLL_DEADLINE_MS)

    const tick = async () => {
      pollTimers.delete(ordinal)
      const lessonId = lesson.value?.id
      if (lessonId == null) return
      try {
        _spliceSection(await api.getSection(lessonId, ordinal))
      } catch {
        /* transient — retry until the deadline */
      }
      const expired = Date.now() >= (pollDeadlines.get(ordinal) ?? 0)
      if (_hasPendingAssets(_byOrdinal(ordinal)) && !expired) {
        pollTimers.set(ordinal, setTimeout(tick, POLL_INTERVAL_MS))
      } else {
        _stopPoll(ordinal)
      }
    }
    pollTimers.set(ordinal, setTimeout(tick, POLL_INTERVAL_MS))
  }

  function stopPolls(): void {
    pollTimers.forEach((t) => clearTimeout(t))
    pollTimers.clear()
    pollDeadlines.clear()
  }

  /** Refresh a section ONCE right away, then keep polling if images are still pending. Used on reveal
   *  because a prefetched section may carry stale 'pending' placeholders whose images already finished
   *  — this swaps them in immediately instead of after the first poll interval. */
  async function refreshSectionNow(ordinal: number): Promise<void> {
    const lessonId = lesson.value?.id
    if (lessonId == null) return
    try {
      _spliceSection(await api.getSection(lessonId, ordinal))
    } catch {
      /* transient — pollSectionAssets will keep trying */
    }
    pollSectionAssets(ordinal)
  }

  /** Core single-flight fetch shared by the silent prefetch and the manual reveal. The server
   *  endpoint is idempotent + per-lesson locked, so a prefetch and a click for the same ordinal never
   *  double-spend; here we additionally dedupe so they await the SAME request. */
  function fetchSection(ordinal: number): Promise<LessonSection> {
    const existing = inflight.get(ordinal)
    if (existing) return existing
    if (!lesson.value) return Promise.reject(new Error('No lesson loaded'))
    const lessonId = lesson.value.id
    const epoch = loadEpoch
    const p: Promise<LessonSection> = api
      .generateSection(lessonId, ordinal)
      .then((section) => {
        if (epoch === loadEpoch) _spliceSection(section) // ignore a result from a superseded load
        return section
      })
      .finally(() => {
        if (inflight.get(ordinal) === p) inflight.delete(ordinal) // don't clobber a newer entry
      })
    inflight.set(ordinal, p)
    return p
  }

  /** Silently pre-generate ONE section ahead of the reveal boundary, so the next "Continue" is
   *  instant. No-op if there is no next section, it is already ready, or already in flight. */
  function prefetchNext(): void {
    if (!lesson.value) return
    const next = revealedUpTo.value + 1
    if (next > _lastOrdinal()) return
    if (_isReady(_byOrdinal(next)) || inflight.has(next)) return
    // Silent: a manual reveal is what surfaces errors + the spinner.
    void fetchSection(next).catch(() => {})
  }

  async function load(id: number): Promise<void> {
    loading.value = true
    error.value = null
    revealedUpTo.value = 0
    generatingOrdinal.value = null
    failedOrdinal.value = null
    loadEpoch += 1 // supersede any in-flight prefetch from a previously-loaded lesson
    inflight.clear()
    stopPolls()
    try {
      lesson.value = await api.getLesson(id)
      pollSectionAssets(0) // section 0 is revealed immediately; fill its images as they arrive
      prefetchNext() // build section 1 in the background
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Could not load lesson'
      throw e
    } finally {
      loading.value = false
    }
  }

  /** Reveal the next part (the "Continue" action). Instant when it was prefetched; otherwise shows a
   *  spinner while it generates. Afterwards, pre-generate the following part (one ahead). */
  async function revealNext(): Promise<void> {
    if (!lesson.value) return
    const next = revealedUpTo.value + 1
    if (next > _lastOrdinal()) return
    failedOrdinal.value = null

    if (!_isReady(_byOrdinal(next))) {
      generatingOrdinal.value = next
      try {
        await fetchSection(next) // dedupes with any in-flight prefetch
      } catch {
        failedOrdinal.value = next
        generatingOrdinal.value = null
        return
      }
      generatingOrdinal.value = null
    }

    revealedUpTo.value = next
    // If the just-revealed part has image placeholders, refresh once now (a prefetched section may
    // hold stale 'pending' assets whose images already finished), then keep polling for the rest.
    if (_byOrdinal(next)?.assets.some((a) => a.status === 'pending')) {
      void refreshSectionNow(next)
    }
    prefetchNext() // keep one ahead
  }

  /** Wipe lesson state on a learner-identity switch (shared-device privacy). */
  function reset(): void {
    lesson.value = null
    loading.value = false
    error.value = null
    revealedUpTo.value = 0
    generatingOrdinal.value = null
    failedOrdinal.value = null
    loadEpoch += 1
    inflight.clear()
    stopPolls()
  }

  return {
    lesson,
    loading,
    error,
    revealedUpTo,
    generatingOrdinal,
    failedOrdinal,
    load,
    revealNext,
    prefetchNext,
    pollSectionAssets,
    stopPolls,
    reset,
  }
})
