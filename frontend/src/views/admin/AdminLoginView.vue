<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '@/lib/api'
import { ADMIN_TOKEN_KEY } from '@/router'

const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref<string | null>(null)
const busy = ref(false)

async function login() {
  if (busy.value) return
  busy.value = true
  error.value = null
  try {
    const res = await api.adminLogin(username.value, password.value)
    localStorage.setItem(ADMIN_TOKEN_KEY, res.access_token)
    router.push((route.query.redirect as string) || { name: 'admin' })
  } catch {
    error.value = 'Invalid credentials'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="py-16 flex flex-col gap-4 max-w-sm mx-auto">
    <h1 class="text-2xl font-bold text-center">Admin sign in</h1>
    <div class="sa-card p-4 flex flex-col gap-3">
      <input v-model="username" placeholder="Username" class="rounded-[var(--radius-btn)] border border-[var(--color-line)] bg-[var(--color-surface-2)] p-3" />
      <input v-model="password" type="password" placeholder="Password" class="rounded-[var(--radius-btn)] border border-[var(--color-line)] bg-[var(--color-surface-2)] p-3" @keydown.enter="login" />
      <button class="sa-btn sa-btn-primary" :disabled="busy" @click="login">Sign in</button>
      <p v-if="error" class="text-sm text-[var(--color-coral)]" role="alert">{{ error }}</p>
    </div>
  </section>
</template>
