import { describe, expect, it } from 'vitest'

import { renderMarkdown, renderMathString, renderSvg } from '@/lib/safeContent'

describe('renderMarkdown', () => {
  it('renders basic markdown', () => {
    const out = renderMarkdown('**bold** and *italic*')
    expect(out).toContain('<strong>bold</strong>')
    expect(out).toContain('<em>italic</em>')
  })

  it('escapes raw HTML (html:false) so no live tags/handlers reach the DOM', () => {
    const out = renderMarkdown('<script>alert(1)</script> hi <img src=x onerror=alert(1)>')
    // html:false escapes raw HTML to inert text — no live <script> or <img> element exists.
    expect(out).not.toContain('<script')
    expect(out).not.toContain('<img')
    expect(out).toContain('&lt;script&gt;') // proven escaped, not parsed
  })

  it('renders inline KaTeX for $...$', () => {
    const out = renderMarkdown('Energy is $E = mc^2$ today.')
    expect(out).toContain('katex')
    expect(out).not.toContain('$E = mc^2$')
  })

  it('renders display KaTeX for $$...$$', () => {
    const out = renderMarkdown('$$\\frac{a}{b}$$')
    expect(out).toContain('katex')
  })

  it("keeps the small SVG shapes KaTeX draws radicals and stretchy arrows with", () => {
    const out = renderMarkdown('Root $\\sqrt{16}=4$ and $\\overrightarrow{AB}$')
    expect(out.match(/<svg/g)).toHaveLength(2)
    expect(out).toContain('<path d="')
    expect(out).toContain('viewBox="')
  })

  it('still escapes an <svg> written in the markdown text itself', () => {
    const out = renderMarkdown('<svg onload="alert(1)"><path d="M0 0"/></svg>')
    expect(out).not.toContain('<svg')
    expect(out).not.toContain('<path')
    expect(out).toContain('&lt;svg') // inert text, not a live element
  })

  it('wraps tables in their own sideways-scrolling box', () => {
    const out = renderMarkdown('| a | b |\n|---|---|\n| 1 | 2 |')
    expect(out).toMatch(/<div class="sa-table-scroll"><table>[\s\S]*<\/table><\/div>/)
  })

  it('treats escaped \\$ as a literal dollar sign', () => {
    const out = renderMarkdown('It costs \\$5 only.')
    expect(out).toContain('$5')
    expect(out).not.toContain('katex')
  })

  it('forces safe attributes on links', () => {
    const out = renderMarkdown('[x](https://example.com)')
    expect(out).toContain('rel="noopener noreferrer nofollow"')
    expect(out).toContain('target="_blank"')
  })
})

describe('renderSvg', () => {
  it('keeps benign svg shapes and text', () => {
    const out = renderSvg(
      '<svg viewBox="0 0 10 10"><title>diagram</title><rect width="5" height="5"/><text>label</text></svg>',
    )
    expect(out).toContain('<svg')
    expect(out).toContain('<rect')
    expect(out).toContain('label')
  })

  it('strips <script> and on* handlers and foreignObject', () => {
    const out = renderSvg(
      '<svg viewBox="0 0 10 10"><script>alert(1)</script><rect onload="x()" width="5" height="5"/><foreignObject><div>x</div></foreignObject></svg>',
    )
    expect(out).not.toContain('<script')
    expect(out.toLowerCase()).not.toContain('onload')
    expect(out.toLowerCase()).not.toContain('foreignobject')
  })
})

describe('renderMathString', () => {
  it('renders a single expression', () => {
    expect(renderMathString('x^2')).toContain('katex')
  })
  it('does not throw on malformed tex', () => {
    expect(() => renderMathString('\\frac{')).not.toThrow()
  })
})
