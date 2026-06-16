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
import {
  EDUCATION_LOCALES,
  SUPPORTED_LOCALES,
  educationLocaleFromBrowser,
  i18n,
  setLocale,
} from './i18n'
import router from './router'
import { usePrefsStore } from './stores/prefs'

const pinia = createPinia()
pinia.use(piniaPersist)

const app = createApp(App)
app.use(pinia)
app.use(router)
app.use(i18n)
app.use(MotionPlugin)

// On a FIRST visit (no persisted prefs yet), follow the browser's language; afterwards the
// learner's explicit choice (persisted) always wins.
const hadStoredPrefs = localStorage.getItem('prefs') != null
const prefs = usePrefsStore()
if (!hadStoredPrefs) {
  const browserLang = (navigator.language || 'en').split('-')[0].toLowerCase()
  if ((SUPPORTED_LOCALES as readonly string[]).includes(browserLang)) {
    prefs.locale = browserLang
  }
}
// Ensure a concrete education-system locale (drives generated content). Keep a valid persisted choice;
// otherwise derive one from the browser (a fresh visit) or from the existing UI locale (an upgrade
// from before this setting existed, e.g. cs UI → cs-CZ).
if (!(EDUCATION_LOCALES as readonly string[]).includes(prefs.educationLocale ?? '')) {
  prefs.educationLocale = hadStoredPrefs
    ? educationLocaleFromBrowser(prefs.locale)
    : educationLocaleFromBrowser(navigator.language)
}

// Apply persisted accessibility prefs to <html> before first paint.
prefs.applyToDom()
setLocale(prefs.locale)

app.mount('#app')
