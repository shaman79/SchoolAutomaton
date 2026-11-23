/** BCP-47 tag to read content aloud in: the learner's education locale when it is the content's
 *  language (so Czech is read with a Czech voice, English with US/UK as chosen), else the bare language. */
export function speechLang(contentLang: string | null | undefined, educationLocale: string | null | undefined): string {
  const lang = (contentLang || 'en').toLowerCase().split('-')[0]
  if (educationLocale && educationLocale.toLowerCase().startsWith(lang)) return educationLocale
  return lang
}

// Language named in a lesson topic / quiz title, in Czech or English ("anglická slovíčka",
// "němčina – členy", "Spanish verbs").
const NAMED: [RegExp, string][] = [
  [/angli|english/i, 'en'],
  [/němč|němec|německ|german|deutsch/i, 'de'],
  [/francouz|french|fran[cç]ais/i, 'fr'],
  [/španěl|spanish|españ/i, 'es'],
  [/\bital|italšt|italian/i, 'it'],
  [/rušt|ruský|ruská|ruské|russian/i, 'ru'],
  [/polšt|polský|polská|polish/i, 'pl'],
  [/slovenšt|slovensk|slovak/i, 'sk'],
  [/češt|český|česká|české|czech/i, 'cs'],
]

/** The language a foreign-language lesson or quiz practises (bare code), or null for any other
 *  subject. Named in the topic / title when possible; otherwise English, the language almost every
 *  learner of a non-English school system practises — but never the reading language itself. */
export function foreignLanguage(
  subject: string | null | undefined,
  hints: (string | null | undefined)[],
  readLang: string,
): string | null {
  if (subject !== 'foreign_language') return null
  const base = readLang.toLowerCase().split('-')[0]
  const text = hints.filter(Boolean).join(' ')
  for (const [re, lang] of NAMED) if (lang !== base && re.test(text)) return lang
  return base !== 'en' ? 'en' : null
}
