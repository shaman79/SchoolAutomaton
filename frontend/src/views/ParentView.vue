<script setup lang="ts">
/**
 * ParentView (/parent, "For parents") — the ONE place for parents, on any device:
 *
 *  - "This device" (when this device has its own learner — most likely the child's): the overview
 *    of its learning, and the parent code that lets a parent follow it from their own phone.
 *  - Each child followed from this phone by their parent code (stores/parent — kept only here, with
 *    the name the parent gives them): their tasks (give one, see where each is) and their overview.
 *  - "+ Add a child": the steps and the code field. A shared link (`/parent?code=…`) adds the child
 *    at once (the code leaves the address bar first); the child's own resume code is recognised and
 *    refused with what to do instead (it would let the parent learn AS the child).
 *
 * Tabs show only when there is more than one of the above. A child's rarer actions (rename, remove
 * from this phone, add another) sit behind the "⋯" by their name. While a task is being prepared its
 * status refreshes every few seconds. Mobile-first, WCAG 2.2 AA, reduced-motion aware.
 */
import { useDocumentVisibility } from '@vueuse/core'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import SaButton from '@/components/common/SaButton.vue'
import SaChip from '@/components/common/SaChip.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import SaMenu, { type MenuItem } from '@/components/common/SaMenu.vue'
import { toast } from '@/components/common/useToasts'
import AssignmentComposer from '@/components/parents/AssignmentComposer.vue'
import AssignmentList from '@/components/parents/AssignmentList.vue'
import ParentCodeCard from '@/components/parents/ParentCodeCard.vue'
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
import { useSessionStore } from '@/stores/session'
import type { Assignment, Mode, ParentChildInfo, ParentSummary, TopicProgress } from '@/types/session'

/** While a task is being prepared, its status is re-read this often, for at most TASK_POLL_FOR_MS. */
const TASK_POLL_MS = 5_000
const TASK_POLL_FOR_MS = 4 * 60_000
/** Tab ids besides the followed children's own ids. */
const DEVICE = 'device'
const ADD = 'add'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const parent = useParentStore()
const session = useSessionStore()
const { reduced } = useReducedMotion()

// ------------------------------------------------------------------ which tab
const hasDevice = computed(() => !!session.resumeCode)

function initialTab(): string {
  if (route.query.code) return ADD
  const sel = parent.selectedId
  if (sel === DEVICE && hasDevice.value) return DEVICE
  if (sel && parent.children.some((c) => c.id === sel)) return sel
  if (hasDevice.value) return DEVICE
  return parent.children[0]?.id ?? ADD
}
const tab = ref<string>(initialTab())
/** Where "Cancel" in the add form goes back to. */
let beforeAdd: string | null = null

const child = computed<FollowedChild | null>(() => parent.children.find((c) => c.id === tab.value) ?? null)
const isDevice = computed(() => tab.value === DEVICE && hasDevice.value)
const isAdd = computed(() => tab.value === ADD || (!child.value && !isDevice.value))
const showTabs = computed(() => (hasDevice.value ? 1 : 0) + parent.children.length >= 2)

function displayName(c: FollowedChild): string {
  const i = parent.children.findIndex((x) => x.id === c.id)
  return c.name || t('parent.child_fallback', { n: i + 1 })
}
function choose(id: string): void {
  if (id === ADD) {
    void openAdd()
    return
  }
  tab.value = id
}
const days = computed<SummaryDays>({
  get: () => parent.period,
  set: (d) => parent.setPeriod(d),
})

// ------------------------------------------------------------------ adding a child
const addCode = ref('')
const addError = ref<string | null>(null)
const addBusy = ref(false)
const addInput = ref<HTMLInputElement | null>(null)

async function openAdd(): Promise<void> {
  if (tab.value !== ADD) beforeAdd = tab.value
  tab.value = ADD
  addError.value = null
  await nextTick()
  addInput.value?.focus()
}
function cancelAdd(): void {
  addError.value = null
  tab.value = beforeAdd ?? initialTab()
}

async function addChild(raw: string = addCode.value): Promise<void> {
  const code = raw.trim()
  if (!code || addBusy.value) return
  addError.value = null
  const kind = codeKind(code)
  // Checked here, without asking the server: the child's own code must never be used to follow.
  if (kind === 'resume') {
    addError.value = t('parent.resume_code_given', { overview: t('parent.title') })
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
    tab.value = added.id
    if (existing) toast.info(t('parent.already'))
    else void startNaming(added.id) // asking for the name is the confirmation
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

// ------------------------------------------------------------------ the selected tab's data
const info = ref<ParentChildInfo | null>(null)
const summary = ref<ParentSummary | null>(null)
const tasks = ref<Assignment[]>([])
const state = ref<'loading' | 'ready' | 'failed'>('loading')
const summaryLoading = ref(false)
const composerOpen = ref(false)
const confirmRemoveChild = ref(false)
// Bumped on every tab switch: answers for a tab no longer on screen are dropped.
let tabSeq = 0
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
/** The overview for the current tab: this device's own (resume code), or a followed child's. */
function fetchSummary(d: number): Promise<ParentSummary> | null {
  if (isDevice.value) return api.getSummary(d)
  if (child.value && !child.value.revoked) return api.parentSummary(child.value.code, d)
  return null
}

async function loadTab(): Promise<void> {
  const mine = ++tabSeq
  stopPoll()
  composerOpen.value = false
  confirmRemoveChild.value = false
  info.value = null
  summary.value = null
  tasks.value = []
  if (isAdd.value) return
  const c = child.value
  if (c?.revoked) return
  state.value = 'loading'
  try {
    if (isDevice.value) {
      const s = await api.getSummary(parent.period)
      if (mine !== tabSeq) return
      summary.value = s
    } else if (c) {
      const [i, s, a] = await Promise.all([
        api.parentChild(c.code),
        api.parentSummary(c.code, parent.period),
        api.parentAssignments(c.code),
      ])
      if (mine !== tabSeq) return
      info.value = i
      summary.value = s
      tasks.value = a
      schedulePoll(true)
    }
    state.value = 'ready'
    // The period was switched while this was loading: show the one now chosen.
    if (summary.value && summary.value.days !== parent.period) void loadSummary()
  } catch (e) {
    if (mine !== tabSeq) return
    if (c && isRevoked(e)) markRevoked()
    else state.value = 'failed'
  }
}

async function loadSummary(): Promise<void> {
  if (state.value !== 'ready') return
  const request = fetchSummary(parent.period)
  if (!request) return
  const mine = ++summarySeq
  const forTab = tabSeq
  summaryLoading.value = true
  try {
    const s = await request
    if (mine === summarySeq && forTab === tabSeq) summary.value = s
  } catch (e) {
    if (forTab !== tabSeq) return
    if (child.value && isRevoked(e)) markRevoked()
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
  const forTab = tabSeq
  if (!c || c.revoked) return
  try {
    const a = await api.parentAssignments(c.code)
    if (forTab !== tabSeq) return
    tasks.value = a
  } catch (e) {
    if (forTab === tabSeq && isRevoked(e)) {
      markRevoked()
      return
    }
  }
  if (forTab === tabSeq) schedulePoll()
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
function onAgain(task: Assignment): void {
  void openComposer({ text: task.title, mode: task.mode })
}
function onUpdated(task: Assignment): void {
  tasks.value = tasks.value.map((a) => (a.id === task.id ? task : a))
  schedulePoll(true)
}
function onRemoved(id: number): void {
  tasks.value = tasks.value.filter((a) => a.id !== id)
}

// ------------------------------------------------------------------ this phone: rename / remove
function removeChild(): void {
  if (child.value) parent.remove(child.value.id)
  confirmRemoveChild.value = false
  tab.value = initialTab()
}
const childMenu = computed<MenuItem[]>(() => {
  const c = child.value
  if (!c) return []
  const items: MenuItem[] = [{ label: t('parent.rename'), action: () => void startNaming(c.id) }]
  if (!showTabs.value) items.push({ label: t('parent.add_another'), action: () => void openAdd() })
  items.push({ label: t('parent.remove_child'), action: () => (confirmRemoveChild.value = true), danger: true })
  return items
})

// Last, once everything they touch exists (the first load runs right away).
watch(tab, (id) => {
  // Switching away ends a rename — but not the name prompt just opened for the child added now.
  if (namingId.value !== id) namingId.value = null
  if (id !== ADD) parent.selectedId = id // remembered for next time (incl. "this device")
})
watch([tab, () => child.value?.revoked], loadTab, { immediate: true })
watch(() => parent.period, loadSummary)
</script>

<template>
  <section class="sa-pview">
    <!-- More than one to choose from: this device, each followed child, add another -->
    <nav v-if="showTabs" class="sa-pview__tabs" :aria-label="t('parent.children_label')">
      <SaChip
        v-if="hasDevice"
        clickable
        :selected="tab === DEVICE"
        :tone="tab === DEVICE ? 'primary' : 'neutral'"
        @click="choose(DEVICE)"
      >
        {{ t('parent.device_tab') }}
      </SaChip>
      <SaChip
        v-for="c in parent.children"
        :key="c.id"
        clickable
        :selected="c.id === tab"
        :tone="c.id === tab ? 'primary' : 'neutral'"
        @click="choose(c.id)"
      >
        {{ displayName(c) }}
      </SaChip>
      <SaChip clickable icon="users" :selected="isAdd" :tone="isAdd ? 'primary' : 'neutral'" @click="choose(ADD)">
        {{ t('parent.add_another') }}
      </SaChip>
    </nav>

    <!-- ============================================================ a followed child -->
    <template v-if="child && !isAdd">
      <header class="sa-pview__head">
        <form v-if="namingId === child.id" class="sa-card sa-pview__form" @submit.prevent="saveName">
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
          <div class="sa-pview__who-text">
            <p class="sa-pview__eyebrow">{{ t('parent.title') }}</p>
            <h1 class="sa-pview__name">{{ displayName(child) }}</h1>
            <p v-if="!child.revoked && state === 'ready'" class="sa-pview__class">
              {{ gradeLabel || t('parent.class_unknown') }}
            </p>
          </div>
          <SaMenu :items="childMenu" :label="t('parent.more_for', { name: displayName(child) })" />
        </div>
        <div v-if="confirmRemoveChild" class="sa-card sa-pview__confirm" role="group" aria-labelledby="sa-pview-rm">
          <p id="sa-pview-rm">{{ t('parent.remove_child_confirm') }}</p>
          <div class="sa-pview__row">
            <SaButton variant="primary" size="sm" @click="removeChild">{{ t('parent.remove_yes') }}</SaButton>
            <SaButton variant="ghost" size="sm" @click="confirmRemoveChild = false">{{ t('parent.keep') }}</SaButton>
          </div>
        </div>
      </header>

      <!-- The code stopped working -->
      <section v-if="child.revoked" class="sa-card sa-pview__revoked" role="alert">
        <h2 class="sa-pview__h2"><SaIcon name="lock" :size="20" /> {{ t('parent.revoked_title') }}</h2>
        <p>{{ t('parent.revoked_body') }}</p>
        <SaButton variant="primary" icon="users" @click="openAdd">{{ t('parent.add_new_code') }}</SaButton>
      </section>

      <template v-else>
        <p v-if="state === 'loading'" class="sa-pview__muted" role="status">{{ t('common.loading') }}</p>

        <div v-else-if="state === 'failed'" class="sa-card sa-pview__note" role="alert">
          <p>{{ t('parent.load_error') }}</p>
          <SaButton variant="ghost" @click="loadTab">{{ t('common.retry') }}</SaButton>
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
              @again="onAgain"
              @revoked="markRevoked"
            />
            <p v-else-if="!composerOpen" class="sa-pview__muted">{{ t('parent.tasks_empty') }}</p>
          </section>

          <!-- The overview, for the period chosen right here -->
          <section class="sa-pview__overview" aria-labelledby="sa-pview-overview">
            <div class="sa-pview__bar">
              <h2 id="sa-pview-overview" class="sa-pview__h2">{{ t('parent.overview') }}</h2>
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
          </section>
        </template>
      </template>
    </template>

    <!-- ============================================================ this device's own learner -->
    <template v-else-if="isDevice">
      <header class="sa-pview__head sa-pview__head--center">
        <h1 class="sa-pview__title">{{ t('parent.title') }}</h1>
        <p class="sa-pview__sub">{{ t('parent.device_sub') }}</p>
      </header>

      <ParentCodeCard />

      <p v-if="state === 'loading'" class="sa-pview__muted" role="status">{{ t('common.loading') }}</p>
      <div v-else-if="state === 'failed'" class="sa-card sa-pview__note" role="alert">
        <p>{{ t('parent.load_error') }}</p>
        <SaButton variant="ghost" @click="loadTab">{{ t('common.retry') }}</SaButton>
      </div>
      <section v-else class="sa-pview__overview" aria-labelledby="sa-pview-overview">
        <div class="sa-pview__bar">
          <h2 id="sa-pview-overview" class="sa-pview__h2">{{ t('parent.overview') }}</h2>
          <PeriodSwitch v-model="days" />
        </div>
        <ParentSummaryPanel
          v-if="summary"
          :summary="summary"
          :class="{ 'sa-pview__stale': summaryLoading }"
          :aria-busy="summaryLoading"
        />
      </section>

      <SaButton v-if="!showTabs" variant="subtle" size="sm" icon="users" class="sa-pview__other" @click="openAdd">
        {{ t('parent.follow_other') }}
      </SaButton>
    </template>

    <!-- ============================================================ add a child -->
    <template v-else>
      <header class="sa-pview__head sa-pview__head--center">
        <h1 class="sa-pview__title">{{ t('parent.title') }}</h1>
        <p class="sa-pview__sub">{{ t('parent.subtitle') }}</p>
      </header>

      <section class="sa-card sa-pview__add" aria-labelledby="sa-pview-add">
        <h2 id="sa-pview-add" class="sa-pview__h2">{{ t('parent.add_title') }}</h2>
        <ol class="sa-pview__steps">
          <li>{{ t('parent.add_step_1', { settings: t('a11y.settings'), overview: t('parent.title') }) }}</li>
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
            <SaButton v-if="parent.children.length || hasDevice" variant="ghost" :disabled="addBusy" @click="cancelAdd">
              {{ t('parent.add_cancel') }}
            </SaButton>
          </div>
        </form>
      </section>
    </template>
  </section>
</template>

<style scoped>
.sa-pview {
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  padding: 1.25rem 0 2rem;
}
.sa-pview__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.sa-pview__head {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.sa-pview__head--center {
  text-align: center;
  padding-top: 0.25rem;
}
.sa-pview__title {
  font-size: 1.5rem;
  font-weight: 800;
}
.sa-pview__sub {
  margin: 0 auto;
  max-width: 32rem;
  color: var(--color-ink-soft);
}
.sa-pview__who {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
}
.sa-pview__who-text {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
.sa-pview__eyebrow {
  margin: 0;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--color-primary);
}
.sa-pview__name {
  margin: 0.1rem 0 0;
  font-size: 1.6rem;
  font-weight: 800;
  line-height: 1.15;
  overflow-wrap: break-word; /* a long name wraps between words, never "Anič|ka" */
}
.sa-pview__class {
  margin: 0.15rem 0 0;
  color: var(--color-ink-soft);
}
.sa-pview__add,
.sa-pview__revoked,
.sa-pview__tasks {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1.1rem;
}
/* The section a "Practise" / "Give again" scrolls to must not hide under the sticky header. */
.sa-pview__tasks {
  scroll-margin-top: calc(var(--sa-header-h, 4rem) + 0.75rem);
}
.sa-pview__overview {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 0.35rem;
}
.sa-pview__h2 {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  font-size: 1.2rem;
  font-weight: 800;
}
/* Heading + its action (or the period switch) on one line when they fit; the control wraps below. */
.sa-pview__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem 1rem;
}
.sa-pview__steps {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin: 0;
  padding-left: 1.4rem;
  line-height: 1.45;
  list-style: decimal; /* the base styles strip list markers; these steps are an order */
}
.sa-pview__steps li::marker {
  font-weight: 800;
  color: var(--color-primary);
}
.sa-pview__form {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.sa-pview__head .sa-pview__form {
  padding: 1rem;
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
.sa-pview__revoked {
  border: 2px solid var(--color-sun);
}
.sa-pview__revoked p {
  margin: 0;
  line-height: 1.45;
}
.sa-pview__revoked > :last-child {
  align-self: flex-start;
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
.sa-pview__confirm {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.9rem;
  border: 1px solid color-mix(in srgb, var(--color-sun) 45%, var(--color-line));
  background: color-mix(in srgb, var(--color-sun) 12%, var(--color-surface));
}
.sa-pview__confirm p {
  margin: 0;
  line-height: 1.45;
}
.sa-pview__other {
  align-self: center;
}
</style>
