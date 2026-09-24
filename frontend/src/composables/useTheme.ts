/**
 * Thin reactive facade over usePrefsStore for theme/font/scale. The store already
 * owns persistence + applying to <html data-theme/data-font ...>; this composable
 * just exposes typed option lists and ergonomic setters for the AccessibilityPanel
 * and anywhere else that needs to read/switch the look. (Optional per F1 brief.)
 */
import { storeToRefs } from 'pinia'

import { usePrefsStore, type FontName, type ThemeName } from '@/stores/prefs'

export interface ThemeOption {
  value: ThemeName
  /** i18n key for the localized label. */
  labelKey: string
}
export interface FontOption {
  value: FontName
  labelKey: string
}

export const THEME_OPTIONS: ThemeOption[] = [
  { value: 'default', labelKey: 'a11y.theme_default' },
  { value: 'highcontrast', labelKey: 'a11y.theme_highcontrast' },
  { value: 'dyslexia', labelKey: 'a11y.theme_dyslexia' },
]

export const FONT_OPTIONS: FontOption[] = [
  { value: 'lexend', labelKey: 'a11y.font_lexend' },
  { value: 'atkinson', labelKey: 'a11y.font_atkinson' },
  { value: 'opendyslexic', labelKey: 'a11y.font_opendyslexic' },
]

/**
 * Fonts that render the UI language correctly. The bundled OpenDyslexic draws lowercase "š" with the
 * capital "Š" glyph (same height as "Š" in the font file) — a letter confusion, exactly what a
 * dyslexic reader must not get — so it isn't offered for Czech (and CSS falls back to Lexend there).
 */
export function fontOptionsFor(uiLocale: string): FontOption[] {
  return uiLocale === 'cs' ? FONT_OPTIONS.filter((f) => f.value !== 'opendyslexic') : FONT_OPTIONS
}

/** Discrete, accessible text-size steps (maps to --font-scale). */
export const FONT_SCALE_STEPS = [0.9, 1, 1.15, 1.3, 1.5] as const

export function useTheme() {
  const prefs = usePrefsStore()
  const { theme, font, fontScale } = storeToRefs(prefs)

  const setTheme = (t: ThemeName) => {
    prefs.theme = t
  }
  const setFont = (f: FontName) => {
    prefs.font = f
  }
  const setFontScale = (s: number) => {
    prefs.fontScale = s
  }

  return {
    theme,
    font,
    fontScale,
    setTheme,
    setFont,
    setFontScale,
    THEME_OPTIONS,
    FONT_OPTIONS,
    FONT_SCALE_STEPS,
  }
}
