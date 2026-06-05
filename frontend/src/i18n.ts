/** UI i18n. Ships en + cs (SPEC §4 #9); generated *content* is multilingual independently. */
import { createI18n } from 'vue-i18n'

import cs from './locales/cs.json'
import en from './locales/en.json'

export const SUPPORTED_LOCALES = ['en', 'cs'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

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
