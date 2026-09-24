/**
 * School levels as the learner's OWN education system names them.
 *
 * The backend carries an exact `school_year` (0-13, counted from the first year of compulsory
 * primary school: 1 = first grade at age 6-7, 0 = kindergarten/preschool; 13 = a 4th upper-secondary
 * year such as the Czech maturita year) plus the coarse `grade_band`. These are education-system
 * names rather than UI strings ("4. třída", "Grade 4", "Year 5"), so they live here keyed by the
 * education locale instead of in the UI message catalogs.
 */

export const SCHOOL_YEAR_MIN = 0
export const SCHOOL_YEAR_MAX = 13

type LevelSystem = 'cs-CZ' | 'en-GB' | 'en-US'

function systemOf(educationLocale: string | null | undefined): LevelSystem {
  if (educationLocale === 'cs-CZ' || educationLocale === 'en-GB') return educationLocale
  return 'en-US'
}

/** The class choices offered for an education system, youngest first. */
export function schoolYearOptions(educationLocale: string | null | undefined): number[] {
  // Czech upper-secondary school has four years (1.-4. ročník SŠ = 10-13); US/UK stop at 12.
  const max = systemOf(educationLocale) === 'cs-CZ' ? SCHOOL_YEAR_MAX : 12
  return Array.from({ length: max - SCHOOL_YEAR_MIN + 1 }, (_, i) => SCHOOL_YEAR_MIN + i)
}

/** "4. třída" / "2. ročník SŠ" / "Grade 4" / "Year 5" for an exact school year. */
export function schoolYearLabel(
  year: number,
  educationLocale: string | null | undefined,
): string {
  switch (systemOf(educationLocale)) {
    case 'cs-CZ':
      if (year <= 0) return 'Předškolák'
      if (year <= 9) return `${year}. třída`
      return `${year - 9}. ročník SŠ`
    case 'en-GB':
      // UK Year N starts a year before US Grade N, so school year N is Year N+1.
      if (year <= 0) return 'Reception / Year 1'
      return `Year ${Math.min(year + 1, 13)}`
    default:
      if (year <= 0) return 'Kindergarten'
      if (year <= 12) return `Grade ${year}`
      return 'College (year 1)'
  }
}

/** The class choices grouped by school stage, as parents know them ("1. stupeň ZŠ", "Middle school"). */
export function schoolYearGroups(
  educationLocale: string | null | undefined,
): { label: string; years: number[] }[] {
  const range = (from: number, to: number) =>
    Array.from({ length: to - from + 1 }, (_, i) => from + i)
  switch (systemOf(educationLocale)) {
    case 'cs-CZ':
      return [
        { label: 'Mateřská škola', years: [0] },
        { label: '1. stupeň ZŠ', years: range(1, 5) },
        { label: '2. stupeň ZŠ', years: range(6, 9) },
        { label: 'Střední škola', years: range(10, 13) },
      ]
    case 'en-GB':
      return [
        { label: 'Primary school', years: range(0, 5) },
        { label: 'Secondary school', years: range(6, 10) },
        { label: 'Sixth form', years: range(11, 12) },
      ]
    default:
      return [
        { label: 'Elementary school', years: range(0, 5) },
        { label: 'Middle school', years: range(6, 8) },
        { label: 'High school', years: range(9, 12) },
      ]
  }
}

const BAND_LABELS: Record<LevelSystem, Record<string, string>> = {
  'cs-CZ': {
    K: 'Předškoláci',
    'G1-2': '1.–2. třída',
    'G3-5': '3.–5. třída',
    'G6-8': '6.–8. třída',
    'G9-12': '9. třída a SŠ',
    adult: 'Dospělí',
  },
  'en-GB': {
    K: 'Reception',
    'G1-2': 'Years 1–2',
    'G3-5': 'Years 4–6',
    'G6-8': 'Years 7–9',
    'G9-12': 'Years 10–13',
    adult: 'Adults',
  },
  'en-US': {
    K: 'Kindergarten',
    'G1-2': 'Grades 1–2',
    'G3-5': 'Grades 3–5',
    'G6-8': 'Grades 6–8',
    'G9-12': 'Grades 9–12',
    adult: 'Adults',
  },
}

/**
 * The best human label for a piece of content's level: the exact school year when known, else the
 * grade band. Empty for an unknown band (callers then just omit the level).
 */
export function levelLabel(
  level: { grade_band?: string | null; school_year?: number | null },
  educationLocale: string | null | undefined,
): string {
  if (typeof level.school_year === 'number') return schoolYearLabel(level.school_year, educationLocale)
  return BAND_LABELS[systemOf(educationLocale)][level.grade_band ?? ''] ?? ''
}
