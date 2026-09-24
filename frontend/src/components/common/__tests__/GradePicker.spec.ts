import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import GradePicker from '@/components/common/GradePicker.vue'

describe('GradePicker', () => {
  it('lists the Czech classes by school stage and marks the current one', () => {
    const w = mount(GradePicker, { props: { modelValue: 4, educationLocale: 'cs-CZ' } })
    const pills = w.findAll('button')
    expect(pills).toHaveLength(14)
    const current = pills.find((b) => b.attributes('aria-pressed') === 'true')
    expect(current?.text()).toBe('4. třída')
    expect(w.findAll('[role="group"]').map((g) => g.attributes('aria-label'))).toContain('2. stupeň ZŠ')
  })

  it('emits the chosen school year', async () => {
    const w = mount(GradePicker, { props: { modelValue: null, educationLocale: 'cs-CZ' } })
    const ninth = w.findAll('button').find((b) => b.text() === '9. třída')
    await ninth!.trigger('click')
    expect(w.emitted('update:modelValue')).toEqual([[9]])
  })
})
