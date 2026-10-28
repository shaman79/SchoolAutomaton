/**
 * "Badge unlocked" — one toast however many badges a reply unlocked (a stack of them hid the Next
 * button). A badge is awarded, and so reported, only once: every reply that can carry new badges
 * (quiz and lesson answers, review cards, a finished lesson part) must show them, or the child never
 * hears about it.
 */
import { toast } from '@/components/common/useToasts'
import { i18n } from '@/i18n'

export function announceBadges(badges: ReadonlyArray<{ title: string }> | null | undefined): void {
  const titles = (badges ?? []).map((b) => b.title)
  if (!titles.length) return
  const t = i18n.global.t
  const message =
    titles.length === 1
      ? t('test.badge_unlocked', { title: titles[0] })
      : t('test.badges_unlocked', { titles: titles.join(', ') })
  toast.success(message, { icon: 'trophy', timeout: 6000 })
}
