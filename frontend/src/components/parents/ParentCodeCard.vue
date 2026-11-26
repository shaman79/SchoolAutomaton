<script setup lang="ts">
/**
 * On the learner's own device (Overview for parents): the PARENT CODE that lets a parent follow this
 * overview — and give tasks — from their own phone, without the child's resume code (which would let
 * them learn as the child). Create it, show it again (QR to scan, link to send, code to type), make a
 * new one (the old stops working everywhere) or stop sharing. Both of those ask first, inline.
 *
 * "Create" is offered only once we KNOW there is no code: if loading fails we say so and retry —
 * creating blindly would replace a code a parent already uses.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from '@/components/common/SaButton.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import { toast } from '@/components/common/useToasts'
import { api } from '@/lib/api'
import { dayLabel } from '@/lib/format'
import { qrDataUrl, shareOrCopy, writeClipboard } from '@/lib/share'
import type { ParentCodeInfo } from '@/types/session'

const { t } = useI18n()

const state = ref<'loading' | 'failed' | 'ready'>('loading')
const info = ref<ParentCodeInfo | null>(null)
const open = ref(false)
const busy = ref(false)
const confirming = ref<'new' | 'stop' | null>(null)
const qrSrc = ref('')

const shareUrl = computed(() =>
  info.value ? `${window.location.origin}/parent?code=${encodeURIComponent(info.value.code)}` : '',
)
const lastUsed = computed(() =>
  info.value?.last_used_at
    ? t('parent_code.last_used', { when: dayLabel(info.value.last_used_at) })
    : t('parent_code.never_used'),
)

async function load() {
  state.value = 'loading'
  try {
    info.value = await api.getParentCode()
    state.value = 'ready'
  } catch {
    state.value = 'failed'
  }
}
onMounted(load)

// The QR is the main way across (scan with the parent's phone): drawn as soon as the code is shown,
// and never left showing an old code.
watch([open, shareUrl], async () => {
  qrSrc.value = ''
  if (open.value && shareUrl.value) {
    const url = shareUrl.value
    const src = await qrDataUrl(url)
    if (url === shareUrl.value) qrSrc.value = src
  }
})

async function create() {
  if (busy.value) return
  busy.value = true
  try {
    const replacing = info.value !== null
    info.value = await api.createParentCode()
    open.value = true
    confirming.value = null
    if (replacing) toast.success(t('parent_code.new_done'))
  } catch {
    toast.error(t('parent_code.error'))
  } finally {
    busy.value = false
  }
}

async function stop() {
  if (busy.value) return
  busy.value = true
  try {
    await api.deleteParentCode()
    info.value = null
    open.value = false
    confirming.value = null
    toast.info(t('parent_code.stopped'))
  } catch {
    toast.error(t('parent_code.error'))
  } finally {
    busy.value = false
  }
}

async function copy() {
  if (!info.value) return
  if (await writeClipboard(info.value.code)) toast.success(t('parent_code.copied'))
  else toast.error(t('parent_code.copy_failed'))
}

async function share() {
  if (!shareUrl.value) return
  const how = await shareOrCopy({ title: t('app.name'), text: t('parent_code.share_text'), url: shareUrl.value })
  if (how === 'copied') toast.success(t('parent_code.link_copied'))
  else if (how === 'failed') toast.error(t('parent_code.copy_failed'))
}
</script>

<template>
  <section class="sa-card sa-pcode" aria-labelledby="sa-pcode-title">
    <h2 id="sa-pcode-title" class="sa-pcode__title">
      <SaIcon name="users" :size="22" />
      {{ t('parent_code.title') }}
    </h2>

    <p v-if="state === 'loading'" class="sa-pcode__muted" role="status">{{ t('common.loading') }}</p>

    <div v-else-if="state === 'failed'" class="sa-pcode__stack" role="alert">
      <p class="sa-pcode__muted">{{ t('parent_code.error') }}</p>
      <SaButton variant="ghost" size="sm" @click="load">{{ t('common.retry') }}</SaButton>
    </div>

    <!-- No code yet -->
    <div v-else-if="!info" class="sa-pcode__stack">
      <p class="sa-pcode__text">{{ t('parent_code.intro') }}</p>
      <SaButton variant="primary" block icon="qr" :loading="busy" @click="create">
        {{ t('parent_code.create') }}
      </SaButton>
    </div>

    <!-- A code exists -->
    <div v-else class="sa-pcode__stack">
      <p class="sa-pcode__status">
        <SaIcon name="check" :size="18" />
        <span>{{ t('parent_code.active') }} · {{ lastUsed }}</span>
      </p>

      <SaButton
        variant="ghost"
        size="sm"
        :icon="open ? undefined : 'qr'"
        class="sa-pcode__toggle"
        :aria-expanded="open"
        aria-controls="sa-pcode-body"
        @click="open = !open"
      >
        {{ open ? t('parent_code.hide') : t('parent_code.show') }}
      </SaButton>

      <div v-if="open" id="sa-pcode-body" class="sa-pcode__stack">
        <figure class="sa-pcode__qr">
          <img v-if="qrSrc" :src="qrSrc" :alt="t('parent_code.qr_alt')" width="240" height="240" />
          <figcaption>{{ t('parent_code.how') }}</figcaption>
        </figure>
        <p class="sa-pcode__label">{{ t('parent_code.label') }}</p>
        <code class="sa-pcode__value">{{ info.code }}</code>
        <div class="sa-pcode__actions">
          <SaButton variant="primary" size="sm" icon="share" @click="share">{{ t('parent_code.share') }}</SaButton>
          <SaButton variant="ghost" size="sm" icon="check" @click="copy">{{ t('parent_code.copy') }}</SaButton>
        </div>

        <!-- Replace / stop — each asks first, inline -->
        <div v-if="confirming" class="sa-pcode__confirm" role="alertdialog" aria-labelledby="sa-pcode-confirm">
          <p id="sa-pcode-confirm">
            {{ confirming === 'new' ? t('parent_code.new_confirm') : t('parent_code.stop_confirm') }}
          </p>
          <div class="sa-pcode__actions">
            <SaButton
              variant="primary"
              size="sm"
              :loading="busy"
              @click="confirming === 'new' ? create() : stop()"
            >
              {{ confirming === 'new' ? t('parent_code.new_yes') : t('parent_code.stop_yes') }}
            </SaButton>
            <SaButton variant="ghost" size="sm" :disabled="busy" @click="confirming = null">
              {{ t('parent_code.cancel') }}
            </SaButton>
          </div>
        </div>
        <div v-else class="sa-pcode__manage">
          <SaButton variant="subtle" size="sm" @click="confirming = 'new'">{{ t('parent_code.new_code') }}</SaButton>
          <SaButton variant="subtle" size="sm" @click="confirming = 'stop'">{{ t('parent_code.stop') }}</SaButton>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.sa-pcode {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  padding: 1.1rem;
  border: 2px solid color-mix(in srgb, var(--color-primary) 35%, var(--color-line));
}
.sa-pcode__title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-size: 1.1rem;
  font-weight: 800;
  color: var(--color-ink);
}
.sa-pcode__stack {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}
.sa-pcode__text {
  margin: 0;
  line-height: 1.5;
}
.sa-pcode__muted {
  margin: 0;
  color: var(--color-ink-soft);
}
.sa-pcode__status {
  display: flex;
  align-items: flex-start;
  gap: 0.4rem;
  margin: 0;
  font-weight: 600;
  line-height: 1.4;
}
.sa-pcode__status :deep(svg) {
  margin-top: 0.15rem;
  color: var(--color-primary);
}
.sa-pcode__toggle {
  align-self: flex-start;
}
.sa-pcode__qr {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  text-align: center;
}
/* Always dark-on-white with a quiet zone, whatever the theme — scanners need the contrast. */
.sa-pcode__qr img {
  width: min(240px, 100%);
  height: auto;
  border-radius: 12px;
  background: #ffffff;
  padding: 6px;
  image-rendering: pixelated;
}
.sa-pcode__qr figcaption {
  font-size: 0.85rem;
  line-height: 1.45;
  color: var(--color-ink-soft);
}
.sa-pcode__label {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--color-ink-soft);
}
.sa-pcode__value {
  font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace;
  font-size: clamp(1.2rem, 6vw, 1.55rem);
  font-weight: 800;
  letter-spacing: 0.1em;
  color: var(--color-ink);
  user-select: all;
  overflow-wrap: anywhere;
}
.sa-pcode__actions,
.sa-pcode__manage {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.sa-pcode__actions > * {
  flex: 1 1 max-content;
}
.sa-pcode__confirm {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.85rem;
  border-radius: var(--radius-btn);
  background: color-mix(in srgb, var(--color-sun) 14%, var(--color-surface));
  border: 1px solid color-mix(in srgb, var(--color-sun) 45%, var(--color-line));
}
.sa-pcode__confirm p {
  margin: 0;
  line-height: 1.45;
}
</style>
