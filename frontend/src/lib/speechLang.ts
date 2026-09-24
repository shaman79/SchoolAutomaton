/** BCP-47 tag to read content aloud in: the learner's education locale when it is the content's
 *  language (so Czech is read with a Czech voice, English with US/UK as chosen), else the bare language. */
export function speechLang(contentLang: string | null | undefined, educationLocale: string | null | undefined): string {
  const lang = (contentLang || 'en').toLowerCase().split('-')[0]
  if (educationLocale && educationLocale.toLowerCase().startsWith(lang)) return educationLocale
  return lang
}
