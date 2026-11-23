/**
 * What read-aloud says, and in which voice.
 *
 * `speechSegments(el, { lang, foreign })` turns a rendered element into language runs ready for the
 * speech engine:
 *  - visible text only: UI buttons, pictures (incl. inline-SVG labels), KaTeX's visual duplicate and
 *    anything aria-hidden are skipped; a blank (select / input) becomes a pause, never its options;
 *  - headings, paragraphs, list items and answer options end with a pause instead of running on;
 *  - math (KaTeX MathML) and the symbols the app writes (·, :, =, −, 1/2 …) are read as words of the
 *    segment's language ("7 krát 8 se rovná 56"); emoji are dropped;
 *  - with a `foreign` language (a foreign-language lesson or quiz), answer choices, quoted and
 *    emphasised words and clauses that look like that language get its voice, the rest the reading
 *    language's. Without one, only an unmistakable English sentence inside non-English text switches.
 *
 * Language detection is deliberately simple and errs towards the reading language: letters only one
 * of the two languages uses, short function words, and (for English) spelling patterns Czech never
 * has. A clause with no clue takes the language of the clause next to it within the same block.
 */

export interface SpeechSegment {
  text: string
  /** BCP-47 tag (the reading language, e.g. 'cs-CZ') or a bare language ('en') for foreign runs. */
  lang: string
}

export interface SpeechOptions {
  /** BCP-47 tag of the content's reading language, e.g. 'cs-CZ'. */
  lang: string
  /** Bare language practised in this content (from `foreignLanguage`), or null. */
  foreign?: string | null
}

type Hint = 'body' | 'emph' | 'choice'
type Atom =
  | { kind: 'text'; text: string; hint: Hint; group: number }
  | { kind: 'math'; math: Element; hint: Hint; group: number }
  | { kind: 'blank'; hint: Hint; group: number }
  | { kind: 'break' }

// ---------------------------------------------------------------- DOM -> atoms
const SKIP =
  'script, style, svg, img, video, audio, option, annotation, .katex-html, [aria-hidden="true"], .sa-readaloud, ' +
  'input[type="radio"], input[type="checkbox"], input[type="hidden"]'
const BLANK = 'select, input, textarea'
const BLOCK = new Set([
  'P', 'DIV', 'LI', 'UL', 'OL', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LABEL', 'LEGEND', 'FIGCAPTION',
  'FIGURE', 'TR', 'TD', 'TH', 'TABLE', 'BLOCKQUOTE', 'DT', 'DD', 'SECTION', 'FIELDSET', 'PRE', 'BR', 'HR',
])
const EMPH = new Set(['STRONG', 'B', 'EM', 'I', 'Q', 'CODE', 'MARK', 'U'])

function collect(root: Element): Atom[] {
  const out: Atom[] = []
  let groups = 0
  const walk = (node: Node, hint: Hint, group: number) => {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.textContent) out.push({ kind: 'text', text: node.textContent, hint, group })
      return
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return
    const el = node as Element
    if (el.matches(SKIP)) return
    // UI buttons are not content — except answer tokens inside a choices group (match pool).
    if (el.tagName === 'BUTTON' && hint !== 'choice') return
    if (el.matches(BLANK)) {
      out.push({ kind: 'blank', hint, group })
      return
    }
    if (el.classList.contains('katex')) {
      const math = el.querySelector('math')
      if (math) {
        out.push({ kind: 'math', math, hint, group })
        return
      } // no MathML: fall through and read KaTeX's text (its visual copy is skipped above)
    }
    let h = hint
    let g = group
    if (el.hasAttribute('data-speech-choices')) {
      h = 'choice'
      g = ++groups
    } else if (EMPH.has(el.tagName) && h === 'body') {
      h = 'emph'
    }
    const block = BLOCK.has(el.tagName)
    if (block) out.push({ kind: 'break' })
    el.childNodes.forEach((child) => walk(child, h, g))
    if (block) out.push({ kind: 'break' })
  }
  walk(root, 'body', 0)
  return out
}

// ---------------------------------------------------------------- atoms -> clauses
interface Clause {
  parts: Atom[] // text / math / blank atoms
  hint: Hint
  group: number
  block: number // clauses of one block (between breaks) may share a language
  label?: 'N' | 'F' | 'U' | '-' // native, foreign, unknown, no letters
}

const QUOTED = /„[^“”"]*[“”"]|“[^”"]*”|"[^"]*"|‚[^‘’']*[‘’]|«[^»]*»/g

/** Split text at sentence / clause ends, keeping the punctuation with the clause it closes. */
export function splitClauses(text: string): string[] {
  const out: string[] = []
  let start = 0
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    const prev = text[i - 1] ?? ' '
    const next = text[i + 1] ?? ' '
    let cut = -1
    if ('.!?…'.includes(c) && /\s/.test(next)) cut = i + 1
    // A colon or semicolon that ends a clause hugs its word; " : " with spaces is division.
    else if ((c === ':' || c === ';') && /\s/.test(next) && !/\s/.test(prev)) cut = i + 1
    else if ((c === '–' || c === '—') && /\s/.test(prev) && /\s/.test(next)) cut = i
    else if (c === '(') cut = i
    else if (c === ')') cut = i + 1
    if (cut > start) {
      out.push(text.slice(start, cut))
      start = cut
    }
  }
  if (start < text.length) out.push(text.slice(start))
  return out.filter((s) => s.length)
}

function toClauses(atoms: Atom[]): Clause[] {
  const clauses: Clause[] = []
  let block = 0
  let open: Clause | null = null
  const close = () => {
    open = null
  }
  const add = (atom: Atom & { kind: 'text' | 'math' | 'blank' }, hint: Hint) => {
    if (!open || open.hint !== hint || open.group !== atom.group) {
      open = { parts: [], hint, group: atom.group, block }
      clauses.push(open)
    }
    open.parts.push(atom)
  }
  for (const atom of atoms) {
    if (atom.kind === 'break') {
      close()
      block++
      continue
    }
    if (atom.kind !== 'text') {
      add(atom, atom.hint)
      continue
    }
    // Quoted spans are emphasis too ("Jak se řekne „apple“?").
    let last = 0
    const pieces: { text: string; hint: Hint }[] = []
    for (const m of atom.text.matchAll(QUOTED)) {
      if (m.index! > last) pieces.push({ text: atom.text.slice(last, m.index), hint: atom.hint })
      pieces.push({ text: m[0], hint: atom.hint === 'choice' ? 'choice' : 'emph' })
      last = m.index! + m[0].length
    }
    if (last < atom.text.length) pieces.push({ text: atom.text.slice(last), hint: atom.hint })
    for (const piece of pieces) {
      const parts = splitClauses(piece.text)
      parts.forEach((part, i) => {
        add({ kind: 'text', text: part, hint: piece.hint, group: atom.group }, piece.hint)
        // Every clause end closes the clause; the last piece may continue into the next atom.
        if (i < parts.length - 1 || /[.!?…:;)]\s*$/.test(part)) close()
      })
    }
  }
  return clauses
}

// ---------------------------------------------------------------- language clues
// Letters each language uses (lowercase). A clue for language A is a letter A uses and B doesn't.
const LETTERS: Record<string, string> = {
  cs: 'áčďéěíňóřšťúůýž',
  sk: 'áäčďéíĺľňóôŕšťúýž',
  pl: 'ąćęłńóśźż',
  de: 'äöüß',
  fr: 'àâæçéèêëîïôœùûüÿ',
  es: 'áéíñóúü¿¡',
  it: 'àèéìíîòóùú',
  en: '',
}
// Short words that mark the language, minus ones the other common language also writes
// (Czech/English: a, i, to, do, on, no, ten, my, had, her …).
const WORD_LISTS: Record<string, string> = {
  cs: 'je jsou jsem jsi jsme jste se si na ve ze v s z k u o jak co ale nebo jako kde tak jen proto podle mezi od po za ani aby ho tom tento tohle',
  sk: 'je sú som si sme ste sa na vo zo v s z k u o ako čo ale alebo kde tak len preto podľa medzi od po za ani aby',
  en: "the is are am was were be been you he she it we they your his its our their this that these those and or not does did have has can will would should could of in at for with from what where when who why how there here very some any yes an it's i'm don't doesn't isn't aren't can't let's",
  de: 'der die das und ist sind ich du er sie wir ihr nicht ein eine einen mit auf von zu im dem den des auch wie was wo bin bist hat haben kein keine',
  fr: "le la les est et je tu il elle nous vous ils un une des du avec pour pas dans qui que c'est j'ai oui",
  es: 'el los las es yo un una con por para que como muy hola',
  it: 'il lo gli sono un una con per che ciao',
  pl: 'jest są się na nie jak co ale lub gdzie tak tylko',
}
const WORDS: Record<string, Set<string>> = Object.fromEntries(
  Object.entries(WORD_LISTS).map(([lang, list]) => [lang, new Set(list.split(' '))]),
)
// English spellings Czech words never have.
const EN_SPELLING = /th|w|ee|oo|ph|q|ght|tion|ing$|'s$|n't$/
// The words children's vocabulary lessons practise most, so a lone quoted or listed word can be told
// apart: English ones no Czech word is spelled like, and Czech ones written without any diacritic.
const VOCAB: Record<string, Set<string>> = {
  en: new Set(
    `dog dogs cat cats horse cow pig sheep goat chicken duck bird fish mouse rabbit elephant lion tiger
    monkey bear snake frog giraffe zebra wolf fox owl bee butterfly spider turtle dolphin shark whale
    parrot hamster puppy kitten pony red blue green yellow black white brown orange pink purple grey gray
    mum mom dad mother father sister brother grandma grandpa baby family friend boy girl man woman child
    children people head hand hands arm leg legs foot feet eye eyes ear ears nose mouth face hair teeth
    tooth finger knee neck shoulder apple apples banana pear bread milk water juice cheese egg eggs meat
    soup cake chocolate sandwich rice tea coffee breakfast lunch dinner sugar carrot potato tomato school
    book pen pencil desk chair teacher pupil class lesson bag ruler rubber homework house home room kitchen
    bedroom bathroom door window table bed garden bike bicycle train plane ship boat toy ball doll phone
    shirt dress skirt trousers jeans shoes socks hat cap coat jacket sun rain snow wind cloud cloudy sunny
    rainy windy cold hot warm day night morning afternoon evening week month year today tomorrow yesterday
    monday tuesday wednesday thursday friday saturday sunday january february april june july august
    september october november december one two three four five six seven eight nine eleven twelve twenty
    hundred go goes went play plays played run runs eat eats like likes love want see look read write swim
    jump sing dance draw sleep drink live work walk ride fly climb cook help open close sit stand come
    came get got give make made know think say said tell speak listen watch wash brush clean big small
    little good bad happy sad nice new old young tall short long fast slow beautiful funny great best
    favourite favorite hungry thirsty tired angry hello goodbye bye please thank thanks sorry name`.split(/\s+/),
  ),
  cs: new Set(
    `pes psa prase koza ovce slon lev tygr had ryba ryby auto kolo voda vody chleba jablko jablka kniha
    knihy pero okno ruka ruce noha nohy hlava oko ucho nos pusa sestra bratr maminka tatinek teta slovo
    slova tabule lavice barva barvy ahoj doma venku dnes jedna dva sedm osm deset vyber spoj najdi zkus
    pozor`.split(/\s+/),
  ),
}
// "Jak se řekne anglicky „pes“?", "Přelož do angličtiny: „kolo“" — a word quoted after a clause that
// asks for the target language is the native word being translated, not a foreign one.
const INTO_FOREIGN = /(anglick|německ|francouzsk|španělsk|rusk|italsk|polsk)y(?![\p{L}])|do (angličtiny|němčiny|francouzštiny|španělštiny|ruštiny|italštiny|polštiny)/iu

function clueLetters(lang: string, other: string): string {
  const mine = LETTERS[lang] ?? ''
  const theirs = LETTERS[other] ?? ''
  return [...mine].filter((ch) => !theirs.includes(ch)).join('')
}

/** How many of `words` carry a clue for `lang` as opposed to `other`. */
function clues(words: string[], lang: string, other: string): number {
  const letters = clueLetters(lang, other)
  const cyrillic = lang === 'ru' || lang === 'uk'
  let n = 0
  for (const w of words) {
    if (cyrillic ? /[а-яё]/.test(w) : letters && [...w].some((ch) => letters.includes(ch))) n++
    else if (WORDS[lang]?.has(w) || VOCAB[lang]?.has(w)) n++
    else if (lang === 'en' && !/[^a-z']/.test(w) && w !== 'zoo' && EN_SPELLING.test(w)) n++
  }
  return n
}

function words(clause: Clause): string[] {
  return (clauseRaw(clause).toLowerCase().match(/[\p{L}']+/gu) ?? []).map((w) => w.replace(/^'+|'+$/g, ''))
}

function clauseRaw(clause: Clause): string {
  return clause.parts.map((p) => (p.kind === 'text' ? p.text : ' ')).join('')
}

/**
 * Label each clause native (N) or foreign (F); '-' has no letters (numbers, math) and follows its
 * neighbour. Clues decide; without any, an emphasised or quoted word in foreign-language content is
 * foreign, a choice follows the rest of its group, and plain text follows its block's neighbours.
 */
function label(clauses: Clause[], native: string, foreign: string | null, guessed: boolean) {
  for (const c of clauses) {
    const ws = words(c)
    if (!ws.length) c.label = '-'
    else if (!foreign) c.label = 'N'
    else {
      const n = clues(ws, native, foreign)
      const f = clues(ws, foreign, native)
      // No foreign-language context: only a clear sentence in the other language switches.
      if (guessed) c.label = n === 0 && f >= 2 && ws.length >= 3 ? 'F' : 'N'
      else if (n || f) c.label = f > n ? 'F' : 'N'
      else c.label = 'U'
    }
  }
  if (!foreign || guessed) return
  clauses.forEach((c, i) => {
    if (c.label !== 'U' || c.hint !== 'emph') return
    const prev = clauses[i - 1]
    const asked = prev && prev.block === c.block && prev.label === 'N' && INTO_FOREIGN.test(clauseRaw(prev))
    c.label = asked ? 'N' : 'F'
  })
  // Answer choices are in one language: unclear ones follow the clear ones of their group (mostly
  // native -> native); a group with no clear member is foreign (the practised words).
  const groups = new Map<number, Clause[]>()
  for (const c of clauses) if (c.hint === 'choice' && c.label !== '-') groups.set(c.group, [...(groups.get(c.group) ?? []), c])
  for (const members of groups.values()) {
    const n = members.filter((c) => c.label === 'N').length
    const f = members.filter((c) => c.label === 'F').length
    const fill = n > f ? 'N' : 'F'
    for (const c of members) if (c.label === 'U') c.label = fill
  }
  // Unclear plain text joins a foreign neighbour in its block ("She … (play) tennis."), else native.
  for (let i = 0; i < clauses.length; i++) {
    if (clauses[i].label !== 'U') continue
    const block = clauses[i].block
    let j = i
    while (j < clauses.length && clauses[j].block === block && (clauses[j].label === 'U' || clauses[j].label === '-')) j++
    const left = clauses.slice(0, i).reverse().find((c) => c.label === 'N' || c.label === 'F')
    const right = clauses.slice(j).find((c) => c.label === 'N' || c.label === 'F')
    const l = left && left.block === block ? left.label : null
    const r = right && right.block === block ? right.label : null
    const fill = (l === 'F' && r !== 'N') || (r === 'F' && l !== 'N') ? 'F' : 'N'
    for (let k = i; k < j; k++) if (clauses[k].label === 'U') clauses[k].label = fill
    i = j - 1
  }
}

// ---------------------------------------------------------------- words for math and symbols
const MATH_WORDS: Record<string, { over: string; squared: string; cubed: string; power: string; root: string; nthRoot: (n: string) => string }> = {
  cs: { over: 'lomeno', squared: 'na druhou', cubed: 'na třetí', power: 'na', root: 'odmocnina z', nthRoot: (n) => `${n}. odmocnina z` },
  en: { over: 'over', squared: 'squared', cubed: 'cubed', power: 'to the power of', root: 'the square root of', nthRoot: (n) => `the ${n}th root of` },
}

/** KaTeX MathML -> words of `lang` (unknown languages keep the symbols). */
export function mathSpeech(el: Element, lang: string): string {
  const w = MATH_WORDS[lang.split('-')[0]]
  const kids = Array.from(el.children)
  const say = (k: Element | undefined) => (k ? mathSpeech(k, lang).trim() : '')
  switch (el.localName) {
    case 'annotation':
    case 'annotation-xml':
      return ''
    case 'mi':
    case 'mn':
    case 'mtext':
      return el.textContent ?? ''
    case 'mo':
      return ` ${el.textContent ?? ''} `
    case 'mspace':
      return ' '
    case 'mfrac':
      return ` ${say(kids[0])} ${w ? w.over : '/'} ${say(kids[1])} `
    case 'msup': {
      const exp = say(kids[1])
      if (!w) return `${say(kids[0])}^${exp}`
      if (exp === '2') return ` ${say(kids[0])} ${w.squared} `
      if (exp === '3') return ` ${say(kids[0])} ${w.cubed} `
      return ` ${say(kids[0])} ${w.power} ${exp} `
    }
    case 'msqrt':
      return w ? ` ${w.root} ${kids.map((k) => say(k)).join(' ')} ` : ` √${kids.map((k) => say(k)).join(' ')} `
    case 'mroot':
      return w ? ` ${w.nthRoot(say(kids[1]))} ${say(kids[0])} ` : ` √${say(kids[0])} `
    default:
      return kids.map((k) => mathSpeech(k, lang)).join('')
  }
}

const EMOJI = /[\p{Extended_Pictographic}\p{Emoji_Modifier}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{200D}\u{20E3}]/gu

/** Symbols the app writes, as words of `lang`; emoji dropped; blanks become a pause. */
export function speakSymbols(text: string, lang: string): string {
  let t = text.replace(EMOJI, '').replace(/_{1,}/g, ' … ').replace(/\s*[→⇒➜]\s*/g, ', ')
  const base = lang.split('-')[0]
  if (base === 'cs') {
    t = t
      .replace(/\s*[·⋅×∙]\s*/g, ' krát ')
      .replace(/\s*÷\s*/g, ' děleno ')
      .replace(/\s+:\s+/g, ' děleno ')
      .replace(/\s*≠\s*/g, ' se nerovná ')
      .replace(/\s*≤\s*/g, ' je menší nebo rovno ')
      .replace(/\s*≥\s*/g, ' je větší nebo rovno ')
      .replace(/\s*=\s*/g, ' se rovná ')
      .replace(/\s+<\s+/g, ' je menší než ')
      .replace(/\s+>\s+/g, ' je větší než ')
      .replace(/\s*\+\s*/g, ' plus ')
      .replace(/\s*−\s*/g, ' minus ')
      .replace(/(\d)\s+-\s+(\d)/g, '$1 minus $2')
      .replace(/(\d)\s*\/\s*(\d)/g, '$1 lomeno $2')
  } else if (base === 'en') {
    t = t
      .replace(/\s*[·⋅×∙]\s*/g, ' times ')
      .replace(/\s*÷\s*/g, ' divided by ')
      .replace(/\s*≠\s*/g, ' is not equal to ')
      .replace(/\s*≤\s*/g, ' is less than or equal to ')
      .replace(/\s*≥\s*/g, ' is greater than or equal to ')
      .replace(/\s*=\s*/g, ' equals ')
      .replace(/\s+<\s+/g, ' is less than ')
      .replace(/\s+>\s+/g, ' is greater than ')
      .replace(/\s*\+\s*/g, ' plus ')
      .replace(/\s*−\s*/g, ' minus ')
      .replace(/(\d)\s+-\s+(\d)/g, '$1 minus $2')
  }
  return t.replace(/\s+/g, ' ')
}

// ---------------------------------------------------------------- assemble
function clauseText(clause: Clause, lang: string): string {
  return clause.parts
    .map((p) => (p.kind === 'text' ? p.text : p.kind === 'math' ? ` ${mathSpeech(p.math, lang)} ` : ' … '))
    .join('')
}

/** The element's speech, as runs of one language each (the reading language unless detected otherwise). */
export function speechSegments(el: Element, opts: SpeechOptions): SpeechSegment[] {
  const native = opts.lang.split('-')[0].toLowerCase()
  const given = opts.foreign && opts.foreign !== native ? opts.foreign : null
  // Without a foreign-language context, only a clear English sentence in other text switches.
  const foreign = given ?? (native !== 'en' ? 'en' : null)
  const clauses = toClauses(collect(el))
  label(clauses, native, foreign, !given)
  const segments: SpeechSegment[] = []
  let block = -1
  let prevLabel: 'N' | 'F' = 'N'
  for (const c of clauses) {
    const lab: 'N' | 'F' = c.label === 'F' ? 'F' : c.label === '-' ? prevLabel : 'N'
    prevLabel = lab
    const lang = lab === 'F' && foreign ? foreign : opts.lang
    let text = speakSymbols(clauseText(c, lang), lang)
    const last = segments[segments.length - 1]
    // A new block (heading, paragraph, option) pauses: a comma, not a full stop, which Czech voices
    // read after a number as an ordinal ("5." = "pátý").
    if (c.block !== block && last && last.text.trim())
      last.text = last.text.replace(/\s*$/, /[.!?…:;,]\s*$/.test(last.text) ? ' ' : ', ')
    block = c.block
    if (last && last.lang === lang) last.text += text
    else if (text.trim()) {
      if (last && !/\s$/.test(last.text)) text = ' ' + text
      segments.push({ text, lang })
    }
  }
  return segments
    .map((s) => ({ ...s, text: s.text.replace(/\s+/g, ' ').replace(/\s+([,.!?…:;])/g, '$1').replace(/^[,;\s–—-]+|[,;\s–—-]+$/g, '').trim() }))
    .filter((s) => /[\p{L}\p{N}]/u.test(s.text))
}

/** All of the element's speech as one string (tests, debugging). */
export function speakableText(el: Element, lang = 'cs-CZ'): string {
  return speechSegments(el, { lang })
    .map((s) => s.text)
    .join(' ')
}

/** Split text into pieces the engines speak reliably: at most `max` characters, cut at a sentence
 *  end, else a clause end, else a space. (Chrome's online voices stop a single utterance after about
 *  15 seconds, and long utterances fail outright on some Android engines.) */
export function chunkText(text: string, max = 160): string[] {
  const out: string[] = []
  let rest = text.trim()
  while (rest.length > max) {
    const window = rest.slice(0, max + 1)
    let cut = -1
    for (const re of [/[.!?…]["“”»)]?\s/g, /[,;:–—]\s/g, /\s/g]) {
      let m: RegExpExecArray | null
      while ((m = re.exec(window))) cut = m.index + m[0].length
      if (cut > max / 3) break
      cut = -1
    }
    if (cut <= 0) cut = max
    out.push(rest.slice(0, cut).trim())
    rest = rest.slice(cut).trim()
  }
  if (rest) out.push(rest)
  return out.filter((s) => /[\p{L}\p{N}]/u.test(s))
}
