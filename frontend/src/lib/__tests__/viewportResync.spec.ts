import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { installViewportResync, isKeyboardField, nudgeScroll } from '@/lib/viewportResync'

/** A window with a visual viewport, a scrollable page and manually-run animation frames. */
function fakeWindow({ touch = true, y = 300, maxY = 2000 } = {}) {
  const vv = Object.assign(new EventTarget(), { height: 800 })
  const scrolls: number[] = []
  const frames: FrameRequestCallback[] = []
  const win = {
    document,
    navigator: { maxTouchPoints: touch ? 5 : 0 },
    visualViewport: vv,
    get scrollY() {
      return y
    },
    scrollTo({ top = 0 }: ScrollToOptions) {
      y = Math.min(Math.max(top, 0), maxY)
      scrolls.push(y)
    },
    requestAnimationFrame(cb: FrameRequestCallback) {
      frames.push(cb)
      return frames.length
    },
  } as unknown as Window
  const runFrames = () => frames.splice(0).forEach((cb) => cb(0))
  const resize = (height: number) => {
    vv.height = height
    vv.dispatchEvent(new Event('resize'))
  }
  return { win, scrolls, runFrames, resize }
}

function field(html: string): HTMLElement {
  const wrap = document.createElement('div')
  wrap.innerHTML = html
  const el = wrap.firstElementChild as HTMLElement
  document.body.appendChild(el)
  return el
}

describe('viewport re-sync after the on-screen keyboard closes', () => {
  let uninstall = () => {}
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    uninstall()
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('treats only keyboard-raising fields as such', () => {
    for (const html of ['<textarea></textarea>', '<input>', '<input type="text">', '<input inputmode="numeric">', '<select></select>', '<div contenteditable="true"></div>']) {
      expect(isKeyboardField(field(html))).toBe(true)
    }
    for (const html of ['<input type="radio">', '<input type="checkbox">', '<input type="range">', '<button></button>', '<div contenteditable="false"></div>']) {
      expect(isKeyboardField(field(html))).toBe(false)
    }
  })

  it('scrolls one pixel and back, as a real scroll', () => {
    const { win, scrolls, runFrames } = fakeWindow({ y: 300 })
    nudgeScroll(win)
    runFrames()
    expect(scrolls).toEqual([299, 300])
  })

  it('nudges downwards at the top of the page, and not at all on a page that cannot scroll', () => {
    const top = fakeWindow({ y: 0 })
    nudgeScroll(top.win)
    top.runFrames()
    expect(top.scrolls).toEqual([1, 0])

    const short = fakeWindow({ y: 0, maxY: 0 })
    nudgeScroll(short.win)
    short.runFrames()
    expect(short.scrolls).toEqual([0])
  })

  it('does not undo a scroll something else made in the meantime', () => {
    const { win, scrolls, runFrames } = fakeWindow({ y: 300 })
    nudgeScroll(win)
    win.scrollTo({ top: 1200 }) // e.g. a lesson restoring the reading spot
    runFrames()
    expect(scrolls).toEqual([299, 1200])
  })

  it('re-syncs once the keyboard is gone after a field loses focus', () => {
    const { win, scrolls, runFrames } = fakeWindow()
    uninstall = installViewportResync(win)
    const prompt = field('<textarea></textarea>')
    prompt.focus()
    prompt.blur()
    expect(scrolls).toEqual([]) // waits for the keyboard to slide away
    vi.advanceTimersByTime(400)
    runFrames()
    expect(scrolls).toEqual([299, 300])
  })

  it('waits while focus moves on to another field (the keyboard stays up)', () => {
    const { win, scrolls } = fakeWindow()
    uninstall = installViewportResync(win)
    const first = field('<input>')
    const second = field('<input>')
    first.focus()
    second.focus()
    vi.advanceTimersByTime(400)
    expect(scrolls).toEqual([])
  })

  it('ignores focus leaving buttons and answer options', () => {
    const { win, scrolls } = fakeWindow()
    uninstall = installViewportResync(win)
    const option = field('<input type="radio">')
    option.focus()
    option.blur()
    vi.advanceTimersByTime(400)
    expect(scrolls).toEqual([])
  })

  it('re-syncs when the keyboard is put away while its field keeps focus', () => {
    const { win, scrolls, runFrames, resize } = fakeWindow()
    uninstall = installViewportResync(win)
    field('<input>').focus()
    resize(450) // keyboard up
    vi.advanceTimersByTime(400)
    expect(scrolls).toEqual([])
    resize(800) // keyboard down
    vi.advanceTimersByTime(400)
    runFrames()
    expect(scrolls).toEqual([299, 300])
  })

  it('does nothing without a touch screen', () => {
    const { win, scrolls, resize } = fakeWindow({ touch: false })
    uninstall = installViewportResync(win)
    const prompt = field('<textarea></textarea>')
    prompt.focus()
    prompt.blur()
    resize(450)
    resize(800)
    vi.advanceTimersByTime(400)
    expect(scrolls).toEqual([])
  })
})
