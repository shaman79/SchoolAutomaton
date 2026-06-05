<script setup lang="ts">
/* PLACEHOLDER — F5 agent replaces with the full admin console: dashboard cards, audit log browser
   (decision/safety filters), settings + API-key management (masked), content library. */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '@/lib/api'
import { ADMIN_TOKEN_KEY } from '@/router'

const router = useRouter()
const data = ref<unknown>(null)
const error = ref<string | null>(null)

function token() {
  return localStorage.getItem(ADMIN_TOKEN_KEY) || ''
}
function logout() {
  localStorage.removeItem(ADMIN_TOKEN_KEY)
  router.push({ name: 'admin-login' })
}

onMounted(async () => {
  try {
    data.value = await api.adminDashboard(token())
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load'
  }
})
</script>

<template>
  <section class="py-8 flex flex-col gap-4">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold">Admin</h1>
      <button class="sa-chip" @click="logout">Sign out</button>
    </div>
    <p v-if="error" class="text-[var(--color-coral)]">{{ error }}</p>
    <pre class="sa-card p-4 text-xs overflow-auto">{{ data }}</pre>
  </section>
</template>
