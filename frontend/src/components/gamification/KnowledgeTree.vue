<script setup lang="ts">
/**
 * Knowledge map — a friendly "garden" of concept nodes from GET /profiles/me/tree (api.getTree),
 * colored and shaped by node_state. It is self-referential progress (SDT competence/autonomy),
 * never a comparison or a punishment:
 *   locked       → seed (greyed, not yet available)         — "prerequisites first"
 *   available    → sprout (ready to start)
 *   learning     → growing plant
 *   mastered     → bloomed flower (celebratory)
 *   needs_review → "time to water this plant" (gentle care, NOT a red error)
 *
 * Layout: mobile-first responsive flex of node "plots", grouped by subject. Each node is a >=44px
 * tappable button; meaning is carried by an icon glyph + a text state chip, never by color alone.
 * Tapping a node emits `select` and opens an inline detail panel. Pure SVG/flex — no heavy graph lib,
 * so it stays light and crisp on phones. Edges are summarized as "unlocks / leads to" in the detail
 * panel rather than drawn as crossing lines (far more legible on a small screen).
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { KnowledgeTreeData, NodeState, TreeNode } from './types'
import EmptyState from '@/components/common/EmptyState.vue'

const props = withDefaults(
  defineProps<{
    /** Raw payload from api.getTree (typed `unknown` in the frozen client). */
    data: KnowledgeTreeData | null
    loading?: boolean
  }>(),
  { loading: false },
)

const emit = defineEmits<{ select: [node: TreeNode] }>()

const { t } = useI18n()

const nodes = computed<TreeNode[]>(() => props.data?.nodes ?? [])
const hasNodes = computed(() => nodes.value.length > 0)

const byId = computed(() => {
  const m = new Map<number, TreeNode>()
  for (const n of nodes.value) m.set(n.concept_id, n)
  return m
})

/** Group by subject for a tidy garden-bed layout. */
const beds = computed(() => {
  const groups = new Map<string, TreeNode[]>()
  for (const n of nodes.value) {
    const key = n.subject || t('tree.other_subject')
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(n)
  }
  // Within a bed, mastered/learning first feels rewarding; locked sink to the end.
  const rank: Record<NodeState, number> = {
    needs_review: 0,
    learning: 1,
    available: 2,
    mastered: 3,
    locked: 4,
  }
  for (const arr of groups.values()) arr.sort((a, b) => rank[a.state] - rank[b.state])
  return [...groups.entries()].map(([subject, items]) => ({ subject, items }))
})

const counts = computed(() => {
  const c: Record<NodeState, number> = {
    locked: 0,
    available: 0,
    learning: 0,
    mastered: 0,
    needs_review: 0,
  }
  for (const n of nodes.value) c[n.state]++
  return c
})

/** Per-state presentation (glyph + tone + localized label). Glyph is the garden metaphor. */
const STATE_META: Record<NodeState, { glyph: string; tone: string }> = {
  locked: { glyph: '🌱', tone: 'var(--color-ink-soft)' },
  available: { glyph: '🌿', tone: 'var(--color-sky)' },
  learning: { glyph: '🪴', tone: 'var(--color-primary)' },
  mastered: { glyph: '🌸', tone: 'var(--color-mint)' },
  needs_review: { glyph: '💧', tone: 'var(--color-sun)' },
}

function stateLabel(s: NodeState): string {
  return t(`tree.state.${s}`)
}

const selected = ref<TreeNode | null>(null)
function pick(n: TreeNode) {
  selected.value = selected.value?.concept_id === n.concept_id ? null : n
  if (selected.value) emit('select', n)
}

const selectedPrereqs = computed(() =>
  (selected.value?.prereq_ids ?? []).map((id) => byId.value.get(id)).filter((n): n is TreeNode => !!n),
)
const selectedRelated = computed(() =>
  (selected.value?.related_ids ?? []).map((id) => byId.value.get(id)).filter((n): n is TreeNode => !!n),
)

function masteryPct(n: TreeNode) {
  return Math.round((n.mastery ?? 0) * 100)
}
</script>

<template>
  <div class="sa-tree">
    <p v-if="loading" class="py-8 text-center text-[var(--color-ink-soft)]" role="status" aria-live="polite">
      {{ t('common.loading') }}
    </p>

    <EmptyState
      v-else-if="!hasNodes"
      icon="sparkle"
      :title="t('tree.empty_title')"
      :description="t('tree.empty_desc')"
      announce
    />

    <template v-else>
      <!-- Legend (icon + text, never color-only). -->
      <ul class="mb-4 flex flex-wrap gap-2 p-0" :aria-label="t('tree.legend')">
        <li
          v-for="s in (['mastered', 'learning', 'needs_review', 'available', 'locked'] as NodeState[])"
          :key="s"
          class="sa-chip"
          :style="{ color: STATE_META[s].tone }"
        >
          <span aria-hidden="true">{{ STATE_META[s].glyph }}</span>
          <span>{{ stateLabel(s) }}</span>
          <span class="tabular-nums opacity-70">{{ counts[s] }}</span>
        </li>
      </ul>

      <!-- Garden beds grouped by subject. -->
      <div class="flex flex-col gap-5">
        <section v-for="bed in beds" :key="bed.subject" aria-labelledby="">
          <h3 class="mb-2 text-sm font-bold uppercase tracking-wide text-[var(--color-ink-soft)]">
            {{ bed.subject }}
          </h3>
          <ul class="grid list-none grid-cols-2 gap-2.5 p-0 sm:grid-cols-3 lg:grid-cols-4">
            <li v-for="n in bed.items" :key="n.concept_id">
              <button
                type="button"
                class="sa-tree__node sa-card flex w-full flex-col items-center gap-1 p-3 text-center"
                :class="[`sa-tree__node--${n.state}`, { 'sa-tree__node--selected': selected?.concept_id === n.concept_id }]"
                :aria-pressed="selected?.concept_id === n.concept_id"
                :aria-label="`${n.title} — ${stateLabel(n.state)}, ${masteryPct(n)}%`"
                @click="pick(n)"
              >
                <span class="sa-tree__glyph text-2xl leading-none" aria-hidden="true">
                  {{ STATE_META[n.state].glyph }}
                </span>
                <span class="line-clamp-2 text-sm font-semibold leading-tight">{{ n.title }}</span>
                <span
                  class="text-[0.7rem] font-semibold"
                  :style="{ color: STATE_META[n.state].tone }"
                >
                  {{ stateLabel(n.state) }}
                </span>
                <!-- Slim mastery bar (also numeric in aria-label). -->
                <span
                  class="mt-0.5 block h-1 w-full overflow-hidden rounded-[var(--radius-pill)] bg-[var(--color-surface-2)]"
                  aria-hidden="true"
                >
                  <span
                    class="sa-tree__fill block h-full"
                    :style="{ width: masteryPct(n) + '%', background: STATE_META[n.state].tone }"
                  />
                </span>
              </button>
            </li>
          </ul>
        </section>
      </div>

      <!-- Inline detail panel for the tapped node. -->
      <div
        v-if="selected"
        class="sa-card mt-4 p-4"
        role="region"
        :aria-label="t('tree.detail_for', { title: selected.title })"
      >
        <div class="flex items-start gap-3">
          <span class="text-3xl leading-none" aria-hidden="true">
            {{ STATE_META[selected.state].glyph }}
          </span>
          <div class="min-w-0 flex-1">
            <h4 class="text-lg font-bold leading-tight">{{ selected.title }}</h4>
            <p class="text-sm font-semibold" :style="{ color: STATE_META[selected.state].tone }">
              {{ stateLabel(selected.state) }} · {{ masteryPct(selected) }}%
            </p>
            <!-- needs_review framed as gentle care, never punitive. -->
            <p
              v-if="selected.state === 'needs_review'"
              class="mt-1 text-sm text-[var(--color-ink-soft)]"
            >
              {{ t('tree.water_hint') }}
            </p>
            <p
              v-else-if="selected.state === 'locked'"
              class="mt-1 text-sm text-[var(--color-ink-soft)]"
            >
              {{ t('tree.locked_hint') }}
            </p>
          </div>
        </div>

        <div v-if="selectedPrereqs.length" class="mt-3">
          <p class="text-xs font-bold uppercase tracking-wide text-[var(--color-ink-soft)]">
            {{ t('tree.grows_from') }}
          </p>
          <ul class="mt-1 flex flex-wrap gap-1.5 p-0">
            <li v-for="p in selectedPrereqs" :key="p.concept_id" class="sa-chip">
              <span aria-hidden="true">{{ STATE_META[p.state].glyph }}</span>{{ p.title }}
            </li>
          </ul>
        </div>
        <div v-if="selectedRelated.length" class="mt-3">
          <p class="text-xs font-bold uppercase tracking-wide text-[var(--color-ink-soft)]">
            {{ t('tree.grows_into') }}
          </p>
          <ul class="mt-1 flex flex-wrap gap-1.5 p-0">
            <li v-for="r in selectedRelated" :key="r.concept_id" class="sa-chip">
              <span aria-hidden="true">{{ STATE_META[r.state].glyph }}</span>{{ r.title }}
            </li>
          </ul>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sa-tree__node {
  min-height: var(--tap-min);
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease;
  border: 1px solid var(--color-line);
}
.sa-tree__node--locked {
  opacity: 0.7;
}
.sa-tree__node--mastered {
  border-color: color-mix(in srgb, var(--color-mint) 55%, var(--color-line));
}
.sa-tree__node--needs_review {
  border-color: color-mix(in srgb, var(--color-sun) 60%, var(--color-line));
}
.sa-tree__node--selected {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 45%, transparent);
}
@media (hover: hover) {
  .sa-tree__node:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-pop);
  }
}
.sa-tree__fill {
  transition: width 0.6s cubic-bezier(0.22, 1, 0.36, 1);
}
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
:root[data-reduced-motion='true'] .sa-tree__node,
:root[data-reduced-motion='true'] .sa-tree__node:hover {
  transform: none;
  transition: none;
}
:root[data-reduced-motion='true'] .sa-tree__fill {
  transition: none;
}
</style>
