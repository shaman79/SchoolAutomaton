/**
 * Admin → Settings: the words and number formats shared by the settings rows — localized labels
 * (falling back to the raw key for a setting this build doesn't know), values with their units,
 * money, dates, and "where this value comes from" in plain words.
 */
import { useI18n } from 'vue-i18n'

import type { ConfigItem, ConfigSource, ConfigValue } from './adminApi'

const P = 'admin.settings'

export function useConfigFormat() {
  const { t, te, d, locale } = useI18n()

  const has = (key: string) => te(key) || te(key, 'en')

  /** Localized label of a setting; the key itself when this build has no label for it. */
  function label(key: string): string {
    const k = `${P}.items.${key}.label`
    return has(k) ? t(k) : key
  }
  function help(key: string): string | null {
    const k = `${P}.items.${key}.help`
    return has(k) ? t(k) : null
  }

  function usd(v: number): string {
    // Sub-cent amounts (a few cheap calls) would all read "$0.00".
    const tiny = v > 0 && v < 0.01
    return new Intl.NumberFormat(locale.value, {
      style: 'currency',
      currency: 'USD',
      ...(tiny ? { maximumFractionDigits: 4 } : {}),
    }).format(v)
  }
  function num(v: number): string {
    return new Intl.NumberFormat(locale.value, { maximumFractionDigits: 2 }).format(v)
  }
  function percent(ratio: number): string {
    const small = ratio > 0 && ratio < 0.01
    return new Intl.NumberFormat(locale.value, {
      style: 'percent',
      maximumFractionDigits: small ? 1 : 0,
    }).format(ratio)
  }
  function dateTime(iso: string | null, format: 'long' | 'time' = 'long'): string {
    if (!iso) return ''
    try {
      return d(new Date(iso), format) || iso
    } catch {
      return iso
    }
  }

  /** A value in words: money, seconds, multipliers, "Set"/"Not set" for API keys. */
  function formatValue(item: Pick<ConfigItem, 'key' | 'kind'>, value: ConfigValue): string {
    if (value === null || value === undefined || value === '') return t(`${P}.empty_value`)
    if (item.kind === 'status') return value ? t(`${P}.status.set`) : t(`${P}.status.not_set`)
    if (typeof value === 'boolean') return value ? t(`${P}.yes`) : t(`${P}.no`)
    if (typeof value === 'number') {
      if (item.key.endsWith('_usd')) return usd(value)
      if (item.key.endsWith('_s')) {
        return value >= 120 && value % 60 === 0
          ? t(`${P}.units.seconds_minutes`, { n: num(value), m: num(value / 60) })
          : t(`${P}.units.seconds`, { n: num(value) })
      }
      if (item.key.endsWith('_multiplier')) return t(`${P}.units.times`, { n: num(value) })
      return num(value)
    }
    return String(value)
  }

  /** Where the value in effect comes from, in plain words. */
  function sourceLine(item: ConfigItem): string {
    switch (item.source) {
      case 'env':
        return item.env_name ? t(`${P}.source.env`, { env: item.env_name }) : t(`${P}.source.env_unnamed`)
      case 'admin': {
        const user = item.updated_by
        const date = dateTime(item.updated_at)
        if (user && date) return t(`${P}.source.admin`, { user, date })
        if (user) return t(`${P}.source.admin_by`, { user })
        if (date) return t(`${P}.source.admin_at`, { date })
        return t(`${P}.source.admin_plain`)
      }
      case 'code':
        return t(`${P}.source.code`)
      default:
        return t(`${P}.source.default`)
    }
  }

  /** The short form used inside "Undo — back to X (…)". */
  function baseSourceWord(source: ConfigSource | null): string {
    return t(`${P}.base_source.${source ?? 'default'}`)
  }

  return { t, label, help, usd, num, percent, dateTime, formatValue, sourceLine, baseSourceWord }
}
