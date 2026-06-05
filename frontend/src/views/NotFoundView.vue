<script setup lang="ts">
import { useRouter } from 'vue-router'
const router = useRouter()
</script>

<template>
  <section class="py-20 flex flex-col items-center gap-4 text-center">
    <p class="text-6xl">🧭</p>
    <h1 class="text-2xl font-bold">This page wandered off.</h1>
    <button class="sa-btn sa-btn-primary" @click="router.push('/')">Back to learning</button>
  </section>
</template>
