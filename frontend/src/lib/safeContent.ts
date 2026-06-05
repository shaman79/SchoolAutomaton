/**
 * Output-safety seam the CLIENT owns (SPEC §5, security_model OUTPUT SANITIZATION).
 * ALL LLM / Replicate output is untrusted. Nothing in here may ever be bound to v-html
 * before it has passed through DOMPurify.
 *
 *   renderMarkdown(md)  markdown-it {html:false} + KaTeX for $...$ / $$...$$  -> DOMPurify
 *   renderSvg(svg)      DOMPurify SVG profile, FORBID <script>/<foreignObject> + on* attrs
 *
 * Both return a string of sanitized HTML safe to bind via v-html (and only via v-html
 * inside <SafeContent>). KaTeX runs in trust:false / restrictive maxExpand so a malicious
 * \macro cannot blow up or inject. We render math to HTML strings (htmlAndMathml) and let
 * DOMPurify keep KaTeX's span/MathML output.
 */
import DOMPurify, { type Config as DompurifyConfig } from 'dompurify'
import katex from 'katex'
import MarkdownIt from 'markdown-it'

// ---------------------------------------------------------------- markdown engine
// html:false => raw HTML in the markdown source is escaped, not parsed. linkify keeps
// bare URLs clickable; typographer adds nice quotes. Output is DOMPurified afterwards.
const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: false,
})

// ---------------------------------------------------------------- KaTeX
const KATEX_OPTS: katex.KatexOptions = {
  throwOnError: false, // never crash on bad LLM math — render the source in error color
  trust: false, // disallow \href, \url, \includegraphics, etc.
  maxExpand: 1000, // bound macro expansion (DoS guard)
  strict: false,
  output: 'htmlAndMathml',
}

function renderMath(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, { ...KATEX_OPTS, displayMode })
  } catch {
    // Defensive: throwOnError:false already prevents most throws.
    const safe = tex.replace(/[<>&]/g, (c) => (c === '<' ? '&lt;' : c === '>' ? '&gt;' : '&amp;'))
    return `<code class="sa-math-error">${safe}</code>`
  }
}

/**
 * Replace $$...$$ (display) and $...$ (inline) math with rendered KaTeX HTML. We tokenize on
 * math delimiters over the raw string, swap each math span for an alphanumeric sentinel
 * (whitespace-free so markdown-it never trims/splits/escapes it), run markdown on the prose,
 * then splice the rendered math back in. Escaped \$ is treated as a literal dollar sign.
 */
const PH_OPEN = 'xKMATHx'
const PH_CLOSE = 'xENDKMATHx'

function extractMath(src: string): { text: string; math: string[] } {
  const math: string[] = []
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const ch = src[i]
    // escaped dollar -> literal
    if (ch === '\\' && src[i + 1] === '$') {
      out += '$'
      i += 2
      continue
    }
    if (ch === '$') {
      const display = src[i + 1] === '$'
      const delim = display ? '$$' : '$'
      const start = i + delim.length
      // find the matching (unescaped) closing delimiter
      let j = start
      let close = -1
      while (j < n) {
        if (src[j] === '\\') {
          j += 2
          continue
        }
        if (display) {
          if (src[j] === '$' && src[j + 1] === '$') {
            close = j
            break
          }
        } else if (src[j] === '$') {
          close = j
          break
        }
        j += 1
      }
      if (close === -1) {
        // unterminated — emit the delimiter literally and continue
        out += ch
        i += 1
        continue
      }
      const tex = src.slice(start, close)
      const idx = math.push(renderMath(tex, display)) - 1
      out += `${PH_OPEN}${idx}${PH_CLOSE}`
      i = close + delim.length
      continue
    }
    out += ch
    i += 1
  }
  return { text: out, math }
}

function restoreMath(html: string, math: string[]): string {
  if (math.length === 0) return html
  return html.replace(new RegExp(`${PH_OPEN}(\\d+)${PH_CLOSE}`, 'g'), (_m, d: string) => math[Number(d)] ?? '')
}

// ---------------------------------------------------------------- DOMPurify configs
// Markdown output: allow KaTeX (math/semantics/annotation + span+class) plus normal prose.
const MD_PURIFY_CONFIG: DompurifyConfig = {
  USE_PROFILES: { html: true, mathMl: true },
  ADD_TAGS: ['math', 'semantics', 'annotation', 'mrow', 'mi', 'mo', 'mn', 'msup', 'msub'],
  ADD_ATTR: ['aria-hidden', 'role', 'class', 'style', 'aria-label'],
  FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'form', 'input', 'foreignObject'],
  FORBID_ATTR: ['srcset', 'formaction'],
}

const SVG_PURIFY_CONFIG: DompurifyConfig = {
  USE_PROFILES: { svg: true, svgFilters: true },
  // <style> CSS can smuggle external url()/@import; mirror the server lxml sanitizer's FORBIDDEN_TAGS.
  FORBID_TAGS: ['script', 'foreignObject', 'style'],
  // belt-and-braces: explicitly strip common event handlers (the afterSanitize hook also
  // removes ANY on* attribute; DOMPurify already blocks javascript: protocols).
  FORBID_ATTR: ['onload', 'onclick', 'onerror', 'onmouseover', 'onfocus', 'onbegin'],
}

let hooksInstalled = false
function installHooks(): void {
  if (hooksInstalled) return
  hooksInstalled = true
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    // Harden links: external links open safely; never trust LLM-authored hrefs for target.
    if (node.tagName === 'A' && node.hasAttribute('href')) {
      node.setAttribute('target', '_blank')
      node.setAttribute('rel', 'noopener noreferrer nofollow')
    }
    // Strip any lingering on* event handler defensively.
    for (const attr of Array.from(node.attributes)) {
      if (/^on/i.test(attr.name)) node.removeAttribute(attr.name)
    }
    // `style` is kept for KaTeX layout (it uses position:relative/absolute, top/left, height…),
    // but scrub overlay/clickjacking CSS as defense-in-depth. KaTeX never uses fixed/sticky/z-index,
    // so this is safe for math; LLM markdown is html:false so it can't author style anyway.
    if (node.hasAttribute('style')) {
      const cleaned = (node.getAttribute('style') || '')
        .replace(/position\s*:\s*(fixed|sticky)\b[^;]*;?/gi, '')
        .replace(/z-index\s*:[^;]*;?/gi, '')
      node.setAttribute('style', cleaned)
    }
  })
}

// ---------------------------------------------------------------- public API
/** Render untrusted markdown (with $math$) to sanitized HTML safe for v-html. */
export function renderMarkdown(input: string): string {
  if (!input) return ''
  installHooks()
  const { text, math } = extractMath(input)
  const rendered = md.render(text)
  const withMath = restoreMath(rendered, math)
  return DOMPurify.sanitize(withMath, MD_PURIFY_CONFIG)
}

/** Render untrusted SVG markup to sanitized SVG safe for v-html (script/foreignObject/on* stripped). */
export function renderSvg(input: string): string {
  if (!input) return ''
  installHooks()
  return DOMPurify.sanitize(input, SVG_PURIFY_CONFIG)
}

/** Render a single math expression directly (used by <MathBlock>). */
export function renderMathString(tex: string, displayMode = true): string {
  if (!tex) return ''
  installHooks()
  return DOMPurify.sanitize(renderMath(tex, displayMode), MD_PURIFY_CONFIG)
}
