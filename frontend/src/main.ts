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
import { EDUCATION_LOCALES, educationLocaleFromBrowser, i18n, setLocale } from './i18n'
import router from './router'
import { usePrefsStore } from './stores/prefs'

const pinia = createPinia()
pinia.use(piniaPersist)

const app = createApp(App)
app.use(pinia)
app.use(router)
app.use(i18n)
app.use(MotionPlugin)

// Language: follow the browser until the learner picks a language in Settings; from then on the
// choice wins everywhere. Prefs stored before this rule existed carry no `languageChosen` flag —
// a stored language that differs from the browser's was an explicit pick, so keep honouring it.
const stored = readStoredPrefs()
const prefs = usePrefsStore()
if (
  stored &&
  !('languageChosen' in stored) &&
  (EDUCATION_LOCALES as readonly string[]).includes(String(stored.educationLocale)) &&
  stored.educationLocale !== educationLocaleFromBrowser(navigator.language)
) {
  prefs.languageChosen = true
}
if (!(EDUCATION_LOCALES as readonly string[]).includes(prefs.educationLocale ?? '')) {
  prefs.languageChosen = false // no valid choice to follow
}
prefs.followBrowserLanguage(navigator.language)

function readStoredPrefs(): Record<string, unknown> | null {
  try {
    const raw = localStorage.getItem('prefs')
    return raw ? (JSON.parse(raw) as Record<string, unknown>) : null
  } catch {
    return null
  }
}

// Apply persisted accessibility prefs to <html> before first paint.
prefs.applyToDom()
setLocale(prefs.locale)

app.mount('#app')
