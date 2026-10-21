/**
 * Keeps taps landing where things are drawn on iPhones and iPads.
 *
 * WebKit bug (bugs.webkit.org 254861 / 297779, worst on iOS 26, in Safari and home-screen installs):
 * once the on-screen keyboard — or a <select> picker — closes, Safari can leave its visual viewport
 * offset from the page. Buttons are then drawn in one place while taps hit-test in another, so
 * learners had to tap well above a button to press it, until they happened to scroll. Any real
 * scroll puts the two back together, so when the keyboard goes away we scroll one pixel and back.
 */

/** Fields that bring up the on-screen keyboard (or the select picker) when focused. */
const KEYBOARD_FIELD =
  'textarea, select, [contenteditable]:not([contenteditable="false"]), input:not(' +
  '[type="checkbox"], [type="radio"], [type="range"], [type="button"], [type="submit"], ' +
  '[type="reset"], [type="color"], [type="file"], [type="image"], [type="hidden"])'

/** The keyboard takes ~250 ms to slide away; re-sync once it has settled. */
const SETTLE_MS = 350
/** A visual-viewport height jump bigger than this is the keyboard (or picker) closing. */
const KEYBOARD_PX = 120

export function isKeyboardField(el: Element | null): boolean {
  return !!el && el.matches(KEYBOARD_FIELD)
}

/** Scroll one pixel and back — a real scroll, which makes WebKit re-sync its viewport. */
export function nudgeScroll(win: Window = window): void {
  const y = win.scrollY
  win.scrollTo({ top: y > 0 ? y - 1 : y + 1, behavior: 'instant' })
  const nudged = win.scrollY
  if (nudged === y) return // nothing to scroll on this page
  win.requestAnimationFrame(() => {
    // Leave it be if something else scrolled meanwhile (e.g. a lesson restoring its reading spot).
    if (Math.abs(win.scrollY - nudged) < 1) win.scrollTo({ top: y, behavior: 'instant' })
  })
}

/** Watch for the keyboard closing and re-sync the viewport each time. Returns an uninstaller. */
export function installViewportResync(win: Window = window): () => void {
  const vv = win.visualViewport
  // Only touch screens get an on-screen keyboard.
  if (!vv || !win.navigator.maxTouchPoints) return () => {}

  let timer: ReturnType<typeof setTimeout> | undefined
  const resyncSoon = (unlessStillTyping: boolean) => {
    clearTimeout(timer)
    timer = setTimeout(() => {
      // Focus moved on to another field: the keyboard is still up.
      if (unlessStillTyping && isKeyboardField(win.document.activeElement)) return
      nudgeScroll(win)
    }, SETTLE_MS)
  }

  const onFocusOut = (e: FocusEvent) => {
    if (e.target instanceof Element && isKeyboardField(e.target)) resyncSoon(true)
  }
  // The keyboard can also be put away while its field keeps focus (iPad "hide keyboard" key).
  let lastHeight = vv.height
  const onResize = () => {
    if (vv.height - lastHeight > KEYBOARD_PX) resyncSoon(false)
    lastHeight = vv.height
  }

  win.document.addEventListener('focusout', onFocusOut)
  vv.addEventListener('resize', onResize)
  return () => {
    clearTimeout(timer)
    win.document.removeEventListener('focusout', onFocusOut)
    vv.removeEventListener('resize', onResize)
  }
}
