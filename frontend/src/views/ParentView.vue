<script setup lang="ts">
/**
 * ParentView (/parent) — a parent's OWN phone: follow one or more children by their parent codes
 * (stores/parent — kept only on this device, with the names the parent gives them), see each child's
 * overview for the last 7 or 30 days, and give them lessons/quizzes to do (tasks).
 *
 * Adding a child: open the link shared from the child's device (`/parent?code=…` — the code is taken
 * out of the address bar at once), scan its QR code, or type the code. The child's own resume code
 * is recognised and refused with what to do instead (it would let the parent learn AS the child).
 * A code that stops working (a new one was made, or sharing was stopped) says so and offers to add
 * the new one. While a task is being prepared its status is refreshed every few seconds.
 * Mobile-first, WCAG 2.2 AA, reduced-motion aware.
 */
import { useDocumentVisibility } from '@vueuse/core'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import SaButton from '@/components/common/SaButton.vue'
import SaChip from '@/components/common/SaChip.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import { toast } from '@/components/common/useToasts'
import AssignmentComposer from '@/components/parents/AssignmentComposer.vue'
import AssignmentList from '@/components/parents/AssignmentList.vue'
import ParentSummaryPanel from '@/components/parents/ParentSummaryPanel.vue'
import PeriodSwitch from '@/components/parents/PeriodSwitch.vue'
import { useReducedMotion } from '@/composables/useReducedMotion'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/apiError'
import { codeKind, formatParentCode } from '@/lib/codes'
import { parentErrorKey } from '@/lib/errors'
import { schoolYearLabel } from '@/lib/grades'
import { MAX_OPEN_TASKS } from '@/lib/limits'
import { MAX_CHILD_NAME, useParentStore, type FollowedChild, type SummaryDays } from '@/stores/parent'
import type { Assignment, Mode, ParentChildInfo, ParentSummary, TopicProgress } from '@/types/session'

/** While a task is being prepared, its status is re-read this often, for at most TASK_POLL_FOR_MS. */
const TASK_POLL_MS = 5_000
const TASK_POLL_FOR_MS = 4 * 60_000

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const parent = useParentStore()
const { reduced } = useReducedMotion()

const child = computed<FollowedChild | null>(() => parent.selected)
function displayName(c: FollowedChild): string {
  const i = parent.children.findIndex((x) => x.id === c.id)
  return c.name || t('parent.child_fallback', { n: i + 1 })
}
const days = computed<SummaryDays>({
  get: () => parent.period,
  set: (d) => parent.setPeriod(d),
})

// ------------------------------------------------------------------ adding a child
const adding = ref(false)
const addCode = ref('')
const addError = ref<string | null>(null)
const addBusy = ref(false)
const addInput = ref<HTMLInputElement | null>(null)
const showAdd = computed(() => adding.value || parent.children.length === 0)

async function openAdd(): Promise<void> {
  adding.value = true
  addError.value = null
  await nextTick()
  addInput.value?.focus()
}

async function addChild(raw: string = addCode.value): Promise<void> {
  const code = raw.trim()
  if (!code || addBusy.value) return
  addError.value = null
  const kind = codeKind(code)
  // Checked here, without asking the server: the child's own code must never be used to follow.
  if (kind === 'resume') {
    addError.value = t('parent.resume_code_given', { overview: t('parents.link') })
    return
  }
  if (kind !== 'parent') {
    addError.value = t('parent.not_found')
    return
  }
  addBusy.value = true
  try {
    const { child: added, existing } = await parent.add(code)
    addCode.value = ''
    adding.value = false
    toast.success(t(existing ? 'parent.already' : 'parent.added'))
    if (!existing) void startNaming(added.id)
  } catch (e) {
    addError.value =
      e instanceof ApiError && e.status === 401 ? t('parent.not_found') : t(parentErrorKey(e))
  } finally {
    addBusy.value = false
  }
}

// A shared link carries the code in `?code=`: out of the address bar first, then add it.
onMounted(() => {
  const q = route.query.code
  const incoming = (Array.isArray(q) ? q[0] : q)?.trim()
  if (!incoming) return
  void router.replace({ query: {} })
  addCode.value = formatParentCode(incoming)
  adding.value = true
  void addChild(incoming)
})

// ------------------------------------------------------------------ naming (this device only)
const namingId = ref<string | null>(null)
const nameDraft = ref('')
const nameInput = ref<HTMLInputElement | null>(null)

async function startNaming(id: string): Promise<void> {
  namingId.value = id
  nameDraft.value = parent.children.find((c) => c.id === id)?.name ?? ''
  await nextTick()
  nameInput.value?.focus()
}
function saveName(): void {
  if (namingId.value) parent.rename(namingId.value, nameDraft.value)
  namingId.value = null
}

// ------------------------------------------------------------------ the selected child
const info = ref<ParentChildInfo | null>(null)
const summary = ref<ParentSummary | null>(null)
const tasks = ref<Assignment[]>([])
const state = ref<'loading' | 'ready' | 'failed'>('loading')
const summaryLoading = ref(false)
// Bumped on every child switch: answers for a child no longer on screen are dropped.
let childSeq = 0
let summarySeq = 0

const gradeLabel = computed(() =>
  info.value?.school_year != null ? schoolYearLabel(info.value.school_year, info.value.education_locale) : '',
)

function isRevoked(e: unknown): boolean {
  return e instanceof ApiError && e.status === 401
}
function markRevoked(): void {
  if (child.value) parent.setRevoked(child.value.id, true)
  composerOpen.value = false
  stopPoll()
}

async function loadChild(): Promise<void> {
  const c = child.value
  const mine = ++childSeq
  stopPoll()
  composerOpen.value = false
  info.value = null
  summary.value = null
  tasks.value = []
  if (!c || c.revoked) return
  state.value = 'loading'
  try {
    const [i, s, a] = await Promise.all([
      api.parentChild(c.code),
      api.parentSummary(c.code, parent.period),
      api.parentAssignments(c.code),
    ])
    if (mine !== childSeq) return
    info.value = i
    summary.value = s
    tasks.value = a
    state.value = 'ready'
    schedulePoll(true)
    // The period was switched while this was loading: show the one now chosen.
    if (s.days !== parent.period) void loadSummary()
  } catch (e) {
    if (mine !== childSeq) return
    if (isRevoked(e)) markRevoked()
    else state.value = 'failed'
  }
}

async function loadSummary(): Promise<void> {
  const c = child.value
  if (!c || c.revoked || state.value !== 'ready') return
  const mine = ++summarySeq
  const forChild = childSeq
  summaryLoading.value = true
  try {
    const s = await api.parentSummary(c.code, parent.period)
    if (mine === summarySeq && forChild === childSeq) summary.value = s
  } catch (e) {
    if (forChild !== childSeq) return
    if (isRevoked(e)) markRevoked()
    else toast.error(t(parentErrorKey(e)))
  } finally {
    if (mine === summarySeq) summaryLoading.value = false
  }
}


// ------------------------------------------------------------------ tasks being prepared
let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollUntil = 0

function stopPoll(): void {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}
function schedulePoll(fresh = false): void {
  if (fresh) pollUntil = Date.now() + TASK_POLL_FOR_MS
  stopPoll()
  if (!tasks.value.some((a) => a.status === 'preparing') || Date.now() > pollUntil) return
  pollTimer = setTimeout(() => void refreshTasks(), TASK_POLL_MS)
}
async function refreshTasks(): Promise<void> {
  const c = child.value
  const forChild = childSeq
  if (!c || c.revoked) return
  try {
    const a = await api.parentAssignments(c.code)
    if (forChild !== childSeq) return
    tasks.value = a
  } catch (e) {
    if (forChild === childSeq && isRevoked(e)) {
      markRevoked()
      return
    }
  }
  if (forChild === childSeq) schedulePoll()
}
onBeforeUnmount(stopPoll)

// Back on this tab after a while: the child may have done something meanwhile.
const visibility = useDocumentVisibility()
watch(visibility, (v) => {
  if (v !== 'visible' || state.value !== 'ready') return
  void refreshTasks()
  void loadSummary()
})

// ------------------------------------------------------------------ giving a task
const composerOpen = ref(false)
const composer = ref<InstanceType<typeof AssignmentComposer> | null>(null)
const tasksSection = ref<HTMLElement | null>(null)

async function openComposer(prefill?: { text: string; mode: Mode }): Promise<void> {
  composerOpen.value = true
  await nextTick()
  tasksSection.value?.scrollIntoView({ behavior: reduced.value ? 'auto' : 'smooth', block: 'start' })
  if (prefill) composer.value?.prefill(prefill.text, prefill.mode)
  else void composer.value?.focus()
}
function onGiven(task: Assignment): void {
  tasks.value = [task, ...tasks.value.filter((a) => a.id !== task.id)]
  composerOpen.value = false
  toast.success(t('parent.given'))
  schedulePoll(true)
}
function onAssignTopic(topic: TopicProgress): void {
  void openComposer({ text: topic.title, mode: 'test' })
}
function onUpdated(task: Assignment): void {
  tasks.value = tasks.value.map((a) => (a.id === task.id ? task : a))
  schedulePoll(true)
}
function onRemoved(id: number): void {
  tasks.value = tasks.value.filter((a) => a.id !== id)
}

// ------------------------------------------------------------------ this phone
const confirmRemoveChild = ref(false)
function removeChild(): void {
  if (child.value) parent.remove(child.value.id)
  confirmRemoveChild.value = false
}

// Last, once everything they touch exists (the first load runs right away).
watch(() => child.value?.id, () => {
  confirmRemoveChild.value = false
  namingId.value = null
})
watch(() => child.value?.id, loadChild, { immediate: true })
watch(() => child.value?.revoked, (now, before) => {
  if (before && !now) void loadChild() // the code works again (re-added) → load it
})
watch(() => parent.period, loadSummary)
</script>

<template>
  <section class="sa-pview">
    <header class="sa-pview__head">
      <h1 class="sa-pview__title">{{ t('parent.title') }}</h1>
      <p class="sa-pview__sub">{{ t('parent.subtitle') }}</p>
    </header>

    <!-- More than one child: pick whose overview to see -->
    <nav v-if="parent.children.length > 1" class="sa-pview__kids" :aria-label="t('parent.children_label')">
      <SaChip
        v-for="c in parent.children"
        :key="c.id"
        clickable
        :selected="c.id === child?.id"
        :tone="c.id === child?.id ? 'primary' : 'neutral'"
        @click="parent.select(c.id)"
      >
        {{ displayName(c) }}
      </SaChip>
    </nav>

    <!-- Add a child (always shown while there is none) -->
    <section v-if="showAdd" class="sa-card sa-pview__add" aria-labelledby="sa-pview-add">
      <h2 id="sa-pview-add" class="sa-pview__h2">{{ t('parent.add_title') }}</h2>
      <ol class="sa-pview__steps">
        <li>{{ t('parent.add_step_1', { progress: t('stats.title'), overview: t('parents.link') }) }}</li>
        <li>{{ t('parent.add_step_2', { create: t('parent_code.create') }) }}</li>
        <li>{{ t('parent.add_step_3') }}</li>
      </ol>
      <form class="sa-pview__form" @submit.prevent="addChild()">
        <label for="sa-parent-code" class="sa-pview__label">{{ t('parent.code_label') }}</label>
        <input
          id="sa-parent-code"
          ref="addInput"
          v-model="addCode"
          class="sa-pview__input sa-pview__input--code"
          autocomplete="off"
          autocapitalize="characters"
          spellcheck="false"
          inputmode="text"
          placeholder="ABCDE-FGHJK"
          :aria-invalid="addError ? 'true' : undefined"
          :aria-describedby="addError ? 'sa-parent-code-err' : undefined"
        />
        <p v-if="addError" id="sa-parent-code-err" class="sa-pview__error" role="alert">{{ addError }}</p>
        <div class="sa-pview__row">
          <SaButton type="submit" variant="primary" icon="users" :loading="addBusy" :disabled="!addCode.trim()">
            {{ t('parent.add_submit') }}
          </SaButton>
          <SaButton v-if="parent.children.length" variant="ghost" :disabled="addBusy" @click="adding = false">
            {{ t('parent.add_cancel') }}
          </SaButton>
        </div>
      </form>
    </section>

    <template v-if="child">
      <!-- Whose overview this is (the name lives only on this phone) -->
      <section class="sa-card sa-pview__child">
        <form v-if="namingId === child.id" class="sa-pview__form" @submit.prevent="saveName">
          <label for="sa-child-name" class="sa-pview__label">{{ t('parent.name_prompt') }}</label>
          <input
            id="sa-child-name"
            ref="nameInput"
            v-model="nameDraft"
            class="sa-pview__input"
            :maxlength="MAX_CHILD_NAME"
            autocomplete="off"
            :placeholder="t('parent.name_label')"
          />
          <div class="sa-pview__row">
            <SaButton type="submit" variant="primary" size="sm">{{ t('parent.name_save') }}</SaButton>
            <SaButton variant="ghost" size="sm" @click="namingId = null">{{ t('parent.name_skip') }}</SaButton>
          </div>
        </form>
        <div v-else class="sa-pview__who">
          <span class="sa-pview__avatar" aria-hidden="true"><SaIcon name="users" :size="22" /></span>
          <span class="sa-pview__who-text">
            <h2 class="sa-pview__name">{{ displayName(child) }}</h2>
            <span v-if="!child.revoked && state === 'ready'" class="sa-pview__class">
              {{ gradeLabel || t('parent.class_unknown') }}
            </span>
          </span>
          <SaButton variant="subtle" size="sm" @click="startNaming(child.id)">{{ t('parent.rename') }}</SaButton>
        </div>
      </section>

      <!-- The code stopped working -->
      <section v-if="child.revoked" class="sa-card sa-pview__revoked" role="alert">
        <h2 class="sa-pview__h2"><SaIcon name="lock" :size="20" /> {{ t('parent.revoked_title') }}</h2>
        <p>{{ t('parent.revoked_body') }}</p>
        <SaButton v-if="!showAdd" variant="primary" icon="users" @click="openAdd">{{ t('parent.add_another') }}</SaButton>
      </section>

      <template v-else>
        <p v-if="state === 'loading'" class="sa-pview__muted" role="status">{{ t('common.loading') }}</p>

        <div v-else-if="state === 'failed'" class="sa-card sa-pview__note" role="alert">
          <p>{{ t('parent.load_error') }}</p>
          <SaButton variant="ghost" @click="loadChild">{{ t('common.retry') }}</SaButton>
        </div>

        <template v-else>
          <!-- Tasks: give one, see where each is -->
          <section ref="tasksSection" class="sa-card sa-pview__tasks" aria-labelledby="sa-pview-tasks">
            <div class="sa-pview__bar">
              <h2 id="sa-pview-tasks" class="sa-pview__h2">{{ t('parent.tasks_title') }}</h2>
              <SaButton v-if="!composerOpen" variant="primary" size="sm" icon="sparkle" @click="openComposer()">
                {{ t('parent.give') }}
              </SaButton>
            </div>
            <AssignmentComposer
              v-if="composerOpen"
              ref="composer"
              :code="child.code"
              :grade-label="gradeLabel"
              :max-open="MAX_OPEN_TASKS"
              @given="onGiven"
              @cancel="composerOpen = false"
              @revoked="markRevoked"
            />
            <AssignmentList
              v-if="tasks.length"
              :code="child.code"
              :tasks="tasks"
              @removed="onRemoved"
              @updated="onUpdated"
              @revoked="markRevoked"
            />
            <p v-else-if="!composerOpen" class="sa-pview__muted">{{ t('parent.tasks_empty') }}</p>
          </section>

          <!-- The overview, for the period chosen right here -->
          <div class="sa-pview__bar sa-pview__bar--overview">
            <h2 class="sa-pview__h2">{{ t('parents.subtitle', { n: days }) }}</h2>
            <PeriodSwitch v-model="days" />
          </div>
          <ParentSummaryPanel
            v-if="summary"
            :summary="summary"
            remote
            can-assign
            :class="{ 'sa-pview__stale': summaryLoading }"
            :aria-busy="summaryLoading"
            @assign="onAssignTopic"
          />
        </template>
      </template>

      <!-- This phone: another child, or stop following this one -->
      <section class="sa-pview__manage">
        <div v-if="confirmRemoveChild" class="sa-card sa-pview__confirm" role="alertdialog" aria-labelledby="sa-pview-rm">
          <p id="sa-pview-rm">{{ t('parent.remove_child_confirm') }}</p>
          <div class="sa-pview__row">
            <SaButton variant="primary" size="sm" @click="removeChild">{{ t('parent.remove_yes') }}</SaButton>
            <SaButton variant="ghost" size="sm" @click="confirmRemoveChild = false">{{ t('parent.keep') }}</SaButton>
          </div>
        </div>
        <template v-else>
          <SaButton v-if="!showAdd" variant="ghost" block icon="users" @click="openAdd">
            {{ t('parent.add_another') }}
          </SaButton>
          <SaButton variant="subtle" size="sm" @click="confirmRemoveChild = true">
            {{ t('parent.remove_child') }}
          </SaButton>
        </template>
      </section>
    </template>
  </section>
</template>

<style scoped>
.sa-pview {
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  padding: 1.5rem 0 2rem;
}
.sa-pview__head {
  text-align: center;
}
.sa-pview__title {
  font-size: 1.5rem;
  font-weight: 800;
}
.sa-pview__sub {
  margin: 0.25rem auto 0;
  max-width: 32rem;
  color: var(--color-ink-soft);
}
.sa-pview__kids {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.5rem;
}
.sa-pview__add,
.sa-pview__child,
.sa-pview__revoked,
.sa-pview__tasks {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1.1rem;
}
/* The section a "Give as a task" scrolls to must not hide under the sticky header. */
.sa-pview__tasks {
  scroll-margin-top: calc(var(--sa-header-h, 4rem) + 0.75rem);
}
.sa-pview__h2 {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  font-size: 1.15rem;
  font-weight: 800;
}
.sa-pview__steps {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin: 0;
  padding-left: 1.3rem;
  line-height: 1.45;
}
.sa-pview__form {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.sa-pview__label {
  font-weight: 700;
}
.sa-pview__input {
  width: 100%;
  min-height: var(--tap-min);
  border-radius: var(--radius-btn);
  border: 2px solid var(--color-line);
  background: var(--color-surface-2);
  padding: 0.6rem 0.8rem;
  font: inherit;
  font-size: 1.05rem;
  color: var(--color-ink);
}
.sa-pview__input--code {
  font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.sa-pview__input:focus {
  outline: none;
  border-color: var(--color-primary);
  background: var(--color-surface);
}
.sa-pview__error {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  line-height: 1.45;
  color: var(--color-coral);
}
.sa-pview__row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
/* Avatar + name, and "Rename" beside them — or below, on a narrow phone (never squeezing the name). */
.sa-pview__who {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
}
.sa-pview__avatar {
  display: grid;
  place-items: center;
  flex: none;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: var(--radius-pill);
  background: var(--color-surface-2);
  color: var(--color-primary);
}
.sa-pview__who-text {
  display: flex;
  flex-direction: column;
  flex: 1 1 9rem;
  min-width: 0;
}
.sa-pview__name {
  margin: 0;
  font-size: 1.3rem;
  font-weight: 800;
  line-height: 1.2;
  overflow-wrap: break-word; /* a long name wraps between words, never "Anič|ka" */
}
.sa-pview__class {
  font-size: 0.9rem;
  color: var(--color-ink-soft);
}
.sa-pview__revoked {
  border: 2px solid var(--color-sun);
}
.sa-pview__revoked p {
  margin: 0;
  line-height: 1.45;
}
/* Heading + action (or period switch) on one line when they fit; the control wraps below. */
.sa-pview__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem 1rem;
}
.sa-pview__bar--overview {
  margin-top: 0.4rem;
}
.sa-pview__muted {
  margin: 0;
  color: var(--color-ink-soft);
  line-height: 1.45;
}
.sa-pview__note {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 1.5rem 1.1rem;
  text-align: center;
  color: var(--color-ink-soft);
}
.sa-pview__note p {
  margin: 0;
}
.sa-pview__stale {
  opacity: 0.6;
  transition: opacity 0.15s;
}
.sa-pview__manage {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.5rem;
}
.sa-pview__confirm {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  width: 100%;
  padding: 0.9rem;
  border: 1px solid color-mix(in srgb, var(--color-sun) 45%, var(--color-line));
  background: color-mix(in srgb, var(--color-sun) 12%, var(--color-surface));
}
.sa-pview__confirm p {
  margin: 0;
  line-height: 1.45;
}
</style>
