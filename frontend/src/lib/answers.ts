/** Human-readable answers (the learner's or the correct one), shared by review and instant feedback. */
import { i18n } from '@/i18n'
import { formatNumber } from '@/lib/format'
import type { ItemPublic } from '@/types/question'

/** Render a per-type submitted/correct value as readable text by mapping option ids → their labels. */
export function formatAnswer(item: ItemPublic, value: unknown): string {
  const t = i18n.global.t
  const locale = i18n.global.locale
  if (value == null || value === '' || (Array.isArray(value) && value.length === 0)) {
    return t('review.not_answered')
  }
  const p = item.payload
  switch (p.kind) {
    case 'mcq': {
      const ids = Array.isArray(value) ? value : [value]
      return ids.map((id) => p.options.find((o) => o.id === id)?.text ?? String(id)).join(', ')
    }
    case 'true_false':
      return value ? t('q.tf.true') : t('q.tf.false')
    case 'cloze': {
      const map = (value ?? {}) as Record<string, string>
      const filled = p.blanks.map((b) => map[b.id]).filter((v) => v != null && v !== '')
      return filled.length ? filled.join(', ') : t('review.not_answered')
    }
    case 'short_answer':
      return String(value)
    case 'numeric':
      return `${typeof value === 'number' ? formatNumber(value, locale.value) : String(value)}${p.unit ? ` ${p.unit}` : ''}`
    case 'match': {
      const pairs = (value as { left_id: string; right_id: string }[]) ?? []
      const left = (id: string) => p.left.find((s) => s.id === id)?.text ?? id
      const right = (id: string) => p.right.find((s) => s.id === id)?.text ?? id
      return pairs.map((pr) => `${left(pr.left_id)} → ${right(pr.right_id)}`).join('; ')
    }
    case 'order': {
      const ids = (value as string[]) ?? []
      return ids.map((id) => p.tokens.find((tk) => tk.id === id)?.text ?? id).join(' → ')
    }
    case 'hotspot': {
      const ids = Array.isArray(value) ? value : [value]
      return ids
        .map((id) => p.regions.find((r) => r.id === id)?.label ?? String(id))
        .join(', ')
    }
    default:
      return typeof value === 'string' ? value : JSON.stringify(value)
  }
}
