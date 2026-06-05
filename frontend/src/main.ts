import { MotionPlugin } from '@vueuse/motion'
import { createPinia } from 'pinia'
import piniaPersist from 'pinia-plugin-persistedstate'
import { createApp } from 'vue'

import '@fontsource/lexend/400.css'
import '@fontsource/lexend/500.css'
import '@fontsource/lexend/700.css'
import '@fontsource/atkinson-hyperlegible/400.css'
import '@fontsource/atkinson-hyperlegible/700.css'
import '@fontsource/opendyslexic/400.css'
import '@fontsource/opendyslexic/700.css'
import './style/main.css'

import App from './App.vue'
import { i18n, setLocale } from './i18n'
import router from './router'
import { usePrefsStore } from './stores/prefs'

const pinia = createPinia()
pinia.use(piniaPersist)

const app = createApp(App)
app.use(pinia)
app.use(router)
app.use(i18n)
app.use(MotionPlugin)

// Apply persisted accessibility prefs to <html> before first paint.
const prefs = usePrefsStore()
prefs.applyToDom()
setLocale(prefs.locale)

app.mount('#app')
