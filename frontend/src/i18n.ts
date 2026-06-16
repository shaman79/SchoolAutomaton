/** UI i18n. Ships en + cs (SPEC §4 #9); generated *content* is multilingual independently. */
import { createI18n } from 'vue-i18n'

import cs from './locales/cs.json'
import en from './locales/en.json'

export const SUPPORTED_LOCALES = ['en', 'cs'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

/**
 * Education-system locales (BCP-47). Distinct from the UI locale: these shape GENERATED content
 * (curriculum framework, spelling, units, grade naming) and the output language, while the UI itself
 * stays in one of SUPPORTED_LOCALES. The selected region's base language drives the UI locale.
 */
export const EDUCATION_LOCALES = ['en-US', 'en-GB', 'cs-CZ'] as const
export type EducationLocale = (typeof EDUCATION_LOCALES)[number]

/** The UI locale (en|cs) implied by an education locale (its base language), defaulting to 'en'. */
export function baseUiLocale(educationLocale: string | null | undefined): Locale {
  const base = (educationLocale || 'en').split('-')[0].toLowerCase()
  return (SUPPORTED_LOCALES as readonly string[]).includes(base) ? (base as Locale) : 'en'
}

/** Best-effort map a browser language tag (navigator.language) to a supported education locale. */
export function educationLocaleFromBrowser(tag: string | null | undefined): EducationLocale {
  const t = (tag || 'en').toLowerCase()
  if (t.startsWith('cs')) return 'cs-CZ'
  if (t === 'en-gb' || t.endsWith('-gb')) return 'en-GB'
  return 'en-US' // default English variant
}

export const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: { en, cs },
})

export function setLocale(locale: string): void {
  const l = (SUPPORTED_LOCALES as readonly string[]).includes(locale) ? locale : 'en'
  i18n.global.locale.value = l as Locale
  document.documentElement.lang = l
}
