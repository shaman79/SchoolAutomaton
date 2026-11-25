/** Hand a code or link to another device: clipboard, the phone's share sheet, a QR code. Shared by
 *  the learner's resume-code card and the parent-code card. */
import QRCode from 'qrcode'

/** Copy text; falls back to a hidden textarea where the async clipboard API is missing. */
export async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Fallback for browsers/contexts without the async clipboard API.
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    let ok = false
    try {
      ok = document.execCommand('copy')
    } catch {
      ok = false
    }
    ta.remove()
    return ok
  }
}

/** The native share sheet where there is one (phones — straight to Messages/WhatsApp/email),
 *  otherwise (or when it is dismissed) the link is copied. */
export async function shareOrCopy(data: { title: string; text: string; url: string }): Promise<'shared' | 'copied' | 'failed'> {
  const nav = navigator as Navigator & { share?: (d: ShareData) => Promise<void> }
  if (typeof nav.share === 'function') {
    try {
      await nav.share(data)
      return 'shared'
    } catch {
      /* user dismissed or share unavailable → fall through to clipboard */
    }
  }
  return (await writeClipboard(data.url)) ? 'copied' : 'failed'
}

/** A QR code of `text` as a PNG data URL, rendered locally (the link never leaves the device, and
 *  data: images are allowed by the CSP). Dark on white whatever the theme — scanners need it. */
export async function qrDataUrl(text: string): Promise<string> {
  try {
    return await QRCode.toDataURL(text, {
      errorCorrectionLevel: 'M',
      margin: 2,
      width: 240,
      color: { dark: '#1f2330', light: '#ffffff' },
    })
  } catch {
    return ''
  }
}
