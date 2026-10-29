/**
 * Admin → Settings: the owner sees which AI models / limits are really in effect and where each comes
 * from (app default, the server's .env, changed here, built in), can switch a model (after an inline
 * confirmation) or the daily budget, and undo such a change. API keys only ever read Set / Not set.
 */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { adminConfig: vi.fn(), adminSetConfig: vi.fn(), adminResetConfig: vi.fn() },
  }
})

import SettingsPanel from '@/components/admin/SettingsPanel.vue'
import type { AdminConfigOut, ConfigItem } from '@/components/admin/adminApi'
import { i18n, setLocale } from '@/i18n'
import { ApiError, api } from '@/lib/api'
import { clearToasts, stubDom, toastTexts } from '@/views/__tests__/fixtures'

const mocked = api as unknown as Record<string, Mock>
const TOKEN = 'jwt-token'
const CHANGED_AT = '2026-10-28T09:30:00Z'

function item(fields: Partial<ConfigItem> & Pick<ConfigItem, 'key' | 'group' | 'kind'>): ConfigItem {
  return {
    value: null,
    source: 'default',
    env_name: null,
    editable: false,
    base_value: null,
    base_source: null,
    default_value: null,
    choices: [],
    min: null,
    max: null,
    updated_at: null,
    updated_by: null,
    ...fields,
  }
}

const MAIN = ['claude-opus-5-5', 'claude-opus-4-8']
const SANITIZER = ['claude-haiku-5-5', 'claude-haiku-4-5']

/** Production as the owner described it: the server's .env still pins the older main model. */
function modelItem(fields: Partial<ConfigItem> = {}): ConfigItem {
  return item({
    key: 'model_id',
    group: 'models',
    kind: 'choice',
    value: 'claude-opus-4-8',
    source: 'env',
    env_name: 'SA_MODEL_ID',
    editable: true,
    base_value: 'claude-opus-4-8',
    base_source: 'env',
    default_value: 'claude-opus-5-5',
    choices: MAIN,
    ...fields,
  })
}
function budgetItem(fields: Partial<ConfigItem> = {}): ConfigItem {
  return item({
    key: 'daily_budget_usd',
    group: 'spending',
    kind: 'number',
    value: 50,
    source: 'admin',
    env_name: 'SA_DAILY_BUDGET_USD',
    editable: true,
    base_value: 100,
    base_source: 'default',
    default_value: 100,
    min: 0,
    max: 1000,
    updated_at: CHANGED_AT,
    updated_by: 'owner',
    ...fields,
  })
}

function config(fields: Partial<AdminConfigOut> = {}, items?: ConfigItem[]): AdminConfigOut {
  return {
    can_edit: true,
    items: items ?? [
      modelItem(),
      item({
        key: 'sanitizer_model_id',
        group: 'models',
        kind: 'choice',
        value: 'claude-haiku-5-5',
        env_name: 'SA_SANITIZER_MODEL_ID',
        editable: true,
        base_value: 'claude-haiku-5-5',
        base_source: 'default',
        default_value: 'claude-haiku-5-5',
        choices: SANITIZER,
      }),
      budgetItem(),
      item({ key: 'rate_per_min', group: 'limits', kind: 'integer', value: 20, env_name: 'SA_RATE_PER_MIN', default_value: 20 }),
      item({ key: 'resume_fail_window_s', group: 'limits', kind: 'integer', value: 600, default_value: 600 }),
      item({
        key: 'llm_request_timeout_s',
        group: 'limits',
        kind: 'number',
        value: 90,
        source: 'env',
        env_name: 'SA_LLM_TIMEOUT_S',
        default_value: 120,
      }),
      item({ key: 'future_knob', group: 'limits', kind: 'integer', value: 3 }),
      item({ key: 'anthropic_api_key', group: 'keys', kind: 'status', value: true, source: 'env', env_name: 'ANTHROPIC_API_KEY' }),
      item({ key: 'replicate_api_token', group: 'keys', kind: 'status', value: false, env_name: 'REPLICATE_API_TOKEN' }),
      item({ key: 'env', group: 'about', kind: 'text', value: 'production', source: 'env', env_name: 'SA_ENV', default_value: 'development' }),
      item({ key: 'prompt_version', group: 'about', kind: 'text', value: '2026-10-28.1', source: 'code' }),
    ],
    usage_today: [
      { provider: 'anthropic', model: 'claude-opus-4-8', calls: 12, cost_usd: 1.5, last_call_at: '2026-10-29T08:00:00Z' },
      { provider: 'replicate', model: 'black-forest-labs/flux-schnell', calls: 1, cost_usd: null, last_call_at: null },
    ],
    spent_today_usd: 12.5,
    budget_usd: 50,
    day_started_at: '2026-10-29T00:00:00Z',
    ...fields,
  }
}

async function mountPanel() {
  const w = mount(SettingsPanel, { props: { token: TOKEN }, global: { plugins: [i18n] } })
  await flushPromises()
  return w
}
const row = (w: VueWrapper, key: string) => w.find(`[data-key="${key}"]`)
const tr = (key: string, named: Record<string, unknown> = {}) => i18n.global.t(key, named)
const longDate = (iso: string) => i18n.global.d(new Date(iso), 'long')

beforeEach(() => {
  stubDom()
  vi.clearAllMocks()
  clearToasts()
  mocked.adminConfig.mockResolvedValue(config())
})
afterEach(() => {
  clearToasts()
  setLocale('en')
})

describe('what is in effect', () => {
  it('shows each model in use and where it comes from, in plain words', async () => {
    const w = await mountPanel()
    expect(mocked.adminConfig).toHaveBeenCalledWith(TOKEN)

    const main = row(w, 'model_id')
    expect(main.text()).toContain('Main AI model')
    expect(main.find('[data-test="value"]').text()).toBe('claude-opus-4-8')
    expect(main.find('[data-test="source"]').text()).toBe('Set on the server (SA_MODEL_ID)')

    const check = row(w, 'sanitizer_model_id')
    expect(check.find('[data-test="value"]').text()).toBe('claude-haiku-5-5')
    expect(check.find('[data-test="source"]').text()).toBe('App default')

    const budget = row(w, 'daily_budget_usd')
    expect(budget.find('[data-test="value"]').text()).toBe('$50.00')
    expect(budget.find('[data-test="source"]').text()).toBe(`Changed here by owner, ${longDate(CHANGED_AT)}`)
    expect(longDate(CHANGED_AT)).not.toBe('') // the 'long' date format exists

    expect(row(w, 'prompt_version').text()).toContain('Built into this version')
  })

  it('notes when the server .env pins a model other than the recommended one', async () => {
    const w = await mountPanel()
    const note = row(w, 'model_id').find('[data-test="env-note"]')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('claude-opus-4-8')
    expect(note.text()).toContain('claude-opus-5-5')
    expect(note.text()).toContain('overrides it until you undo it')
    expect(row(w, 'sanitizer_model_id').find('[data-test="env-note"]').exists()).toBe(false)
  })

  it('marks the recommended model and still shows a model that is not on the list', async () => {
    mocked.adminConfig.mockResolvedValue(
      config({}, [modelItem({ value: 'claude-opus-4-1', base_value: 'claude-opus-4-1' })]),
    )
    const w = await mountPanel()
    const options = row(w, 'model_id').findAll('option')
    expect(options.map((o) => o.text())).toEqual([
      'claude-opus-4-1 (in use, not on the list)',
      'claude-opus-5-5 (recommended)',
      'claude-opus-4-8',
    ])
    expect(options[0].attributes('disabled')).toBeDefined()
    expect((row(w, 'model_id').find('select').element as HTMLSelectElement).value).toBe('claude-opus-4-1')
    expect(row(w, 'model_id').find('[data-test="value"]').text()).toBe('claude-opus-4-1')
  })

  it('shows limits with their units, and a setting this build has no label for by its key', async () => {
    const w = await mountPanel()
    expect(row(w, 'rate_per_min').text()).toContain('Requests per learner per minute')
    expect(row(w, 'rate_per_min').find('[data-test="value"]').text()).toBe('20')
    expect(row(w, 'resume_fail_window_s').find('[data-test="value"]').text()).toBe('600 s (10 min)')
    const timeout = row(w, 'llm_request_timeout_s')
    expect(timeout.find('[data-test="value"]').text()).toBe('90 s')
    expect(timeout.find('[data-test="source"]').text()).toBe('Set on the server (SA_LLM_TIMEOUT_S) · app default: 120 s (2 min)')
    expect(row(w, 'future_knob').find('dt').text()).toBe('future_knob')
    expect(row(w, 'env').find('[data-test="value"]').text()).toBe('production')
  })

  it('API keys read Set / Not set in words, never the key', async () => {
    const w = await mountPanel()
    const keys = w.find('[data-test="section-keys"]')
    expect(row(w, 'anthropic_api_key').find('[data-test="value"]').text()).toBe('Set')
    expect(row(w, 'replicate_api_token').find('[data-test="value"]').text()).toBe('Not set')
    expect(row(w, 'replicate_api_token').text()).toContain("Goes in the server's .env as REPLICATE_API_TOKEN")
    expect(keys.findAll('svg').length).toBe(2) // an icon beside each word, not color alone
    expect(keys.findAll('input, select, button').length).toBe(0)
    expect(keys.text()).not.toMatch(/true|false|sk-/)
  })
})

describe('spending today', () => {
  it('shows the spend against the budget and the models that really answered', async () => {
    const w = await mountPanel()
    expect(w.find('[data-test="spent"]').text()).toBe('Spent today: $12.50 of $50.00')
    expect(w.find('[data-test="used"]').text()).toBe('25% of the daily budget used')
    expect(w.find('[data-test="reached"]').exists()).toBe(false)

    const rows = w.findAll('[data-test="usage-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('claude-opus-4-8')
    expect(rows[0].text()).toContain('anthropic')
    expect(rows[0].text()).toContain('12 calls')
    expect(rows[0].text()).toContain('$1.50')
    expect(rows[0].text()).toContain(`last call ${longDate('2026-10-29T08:00:00Z')}`)
    expect(rows[0].text()).toContain('In use: Main AI model')
    expect(rows[1].text()).toContain('black-forest-labs/flux-schnell')
    expect(rows[1].text()).toContain('1 call')
    expect(rows[1].text()).toContain('price unknown')
    expect(rows[1].text()).not.toContain('In use')
  })

  it('says when nothing has called the AI yet today, and when there is no cap', async () => {
    mocked.adminConfig.mockResolvedValue(config({ usage_today: [], spent_today_usd: 0, budget_usd: 0 }))
    const w = await mountPanel()
    expect(w.find('[data-test="usage-empty"]').text()).toBe('No AI calls yet today (since 00:00 UTC).')
    expect(w.find('[data-test="spent"]').text()).toBe('Spent today: $0.00 (no daily cap)')
    expect(w.find('[data-test="used"]').exists()).toBe(false)
  })

  it('says in words when the budget is used up', async () => {
    mocked.adminConfig.mockResolvedValue(config({ spent_today_usd: 51 }))
    const w = await mountPanel()
    expect(w.find('[data-test="reached"]').text()).toContain('Budget reached')
  })
})

describe('changing a model', () => {
  it('asks for confirmation inline, then saves the chosen model and reloads', async () => {
    const w = await mountPanel()
    const main = row(w, 'model_id')
    const save = main.find('[data-test="save"]')
    expect(save.attributes('disabled')).toBeDefined() // nothing changed yet

    await main.find('select').setValue('claude-opus-5-5')
    expect(save.attributes('disabled')).toBeUndefined()
    await save.trigger('click')
    expect(mocked.adminSetConfig).not.toHaveBeenCalled()
    const confirm = main.find('[data-test="confirm"]')
    expect(confirm.text()).toContain('Switch to claude-opus-5-5?')
    expect(confirm.text()).toContain('Every new lesson, quiz and answer check uses this model from now on.')

    const saved = modelItem({
      value: 'claude-opus-5-5',
      source: 'admin',
      updated_by: 'owner',
      updated_at: '2026-10-29T10:00:00Z',
    })
    mocked.adminSetConfig.mockResolvedValue(saved)
    mocked.adminConfig.mockResolvedValue(config({}, [saved]))
    await confirm.find('[data-test="confirm-yes"]').trigger('click')
    await flushPromises()

    expect(mocked.adminSetConfig).toHaveBeenCalledWith(TOKEN, 'model_id', 'claude-opus-5-5')
    expect(mocked.adminConfig).toHaveBeenCalledTimes(2) // reloaded after the save
    expect(row(w, 'model_id').find('[data-test="value"]').text()).toBe('claude-opus-5-5')
    expect(row(w, 'model_id').find('[data-test="source"]').text()).toContain('Changed here by owner')
    expect(row(w, 'model_id').find('[data-test="confirm"]').exists()).toBe(false)
    expect(toastTexts()).toEqual(['Main AI model: now claude-opus-5-5.'])
  })

  it('Cancel closes the confirmation without saving', async () => {
    const w = await mountPanel()
    const main = row(w, 'model_id')
    await main.find('select').setValue('claude-opus-5-5')
    await main.find('[data-test="save"]').trigger('click')
    await main.find('[data-test="confirm-no"]').trigger('click')
    expect(main.find('[data-test="confirm"]').exists()).toBe(false)
    expect(mocked.adminSetConfig).not.toHaveBeenCalled()
    expect((main.find('select').element as HTMLSelectElement).value).toBe('claude-opus-5-5') // choice kept
  })

  it('an expired session while saving reports unauthorized', async () => {
    mocked.adminSetConfig.mockRejectedValue(new ApiError(401, 'Invalid or expired token'))
    const w = await mountPanel()
    const main = row(w, 'model_id')
    await main.find('select').setValue('claude-opus-5-5')
    await main.find('[data-test="save"]').trigger('click')
    await main.find('[data-test="confirm-yes"]').trigger('click')
    await flushPromises()
    expect(w.emitted('unauthorized')).toHaveLength(1)
  })
})

describe('the daily budget', () => {
  it('saves without a confirmation step', async () => {
    const saved = budgetItem({ value: 30 })
    mocked.adminSetConfig.mockResolvedValue(saved)
    const w = await mountPanel()
    const budget = row(w, 'daily_budget_usd')
    const input = budget.find('input')
    expect(input.attributes('step')).toBe('0.01')
    expect(input.attributes('min')).toBe('0')
    expect(input.attributes('max')).toBe('1000')
    expect(w.find(`label[for="${input.attributes('id')}"]`).text()).toBe('Daily AI budget')

    mocked.adminConfig.mockResolvedValue(config({ budget_usd: 30 }, [saved]))
    await input.setValue('30')
    await budget.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(budget.find('[data-test="confirm"]').exists()).toBe(false)
    expect(mocked.adminSetConfig).toHaveBeenCalledWith(TOKEN, 'daily_budget_usd', 30)
    expect(w.find('[data-test="spent"]').text()).toBe('Spent today: $12.50 of $30.00')
  })

  it('checks the range before sending', async () => {
    const w = await mountPanel()
    const budget = row(w, 'daily_budget_usd')
    await budget.find('input').setValue('5000')
    await budget.find('[data-test="save"]').trigger('click')
    expect(mocked.adminSetConfig).not.toHaveBeenCalled()
    const err = budget.find('[data-test="error"]')
    expect(err.attributes('role')).toBe('alert')
    expect(err.text()).toContain('Enter a number from $0.00 to $1,000.00.')
    expect(budget.find('input').attributes('aria-invalid')).toBe('true')
  })

  it("shows the server's 422 explanation on the row and keeps what was typed", async () => {
    const detail = 'daily_budget_usd must be between 0 and 1000'
    mocked.adminSetConfig.mockRejectedValue(new ApiError(422, detail, undefined, detail))
    const w = await mountPanel()
    const budget = row(w, 'daily_budget_usd')
    await budget.find('input').setValue('75')
    await budget.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(mocked.adminSetConfig).toHaveBeenCalledWith(TOKEN, 'daily_budget_usd', 75)
    const err = budget.find('[data-test="error"]')
    expect(err.attributes('role')).toBe('alert')
    expect(err.text()).toContain(detail)
    expect((budget.find('input').element as HTMLInputElement).value).toBe('75')
    expect(mocked.adminConfig).toHaveBeenCalledTimes(1) // nothing reloaded over the input
    expect(toastTexts()).toEqual([])
  })

  it('a failed connection says so on the row', async () => {
    mocked.adminSetConfig.mockRejectedValue(new ApiError(0, 'Network request failed', 'network'))
    const w = await mountPanel()
    const budget = row(w, 'daily_budget_usd')
    await budget.find('input').setValue('75')
    await budget.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(budget.find('[data-test="error"]').text()).toContain(tr('admin.settings.error_save'))
  })
})

describe('undo', () => {
  it('names what it returns to and resets the setting', async () => {
    const w = await mountPanel()
    const undo = row(w, 'daily_budget_usd').find('[data-test="undo"]')
    expect(undo.text()).toBe('Undo — back to $100.00 (app default)')
    expect(row(w, 'model_id').find('[data-test="undo"]').exists()).toBe(false) // not changed here

    const reset = budgetItem({ value: 100, source: 'default', updated_at: null, updated_by: null })
    mocked.adminResetConfig.mockResolvedValue(reset)
    mocked.adminConfig.mockResolvedValue(config({ budget_usd: 100 }, [reset]))
    await undo.trigger('click')
    await flushPromises()

    expect(mocked.adminResetConfig).toHaveBeenCalledWith(TOKEN, 'daily_budget_usd')
    const budget = row(w, 'daily_budget_usd')
    expect(budget.find('[data-test="value"]').text()).toBe('$100.00')
    expect(budget.find('[data-test="source"]').text()).toBe('App default')
    expect(budget.find('[data-test="undo"]').exists()).toBe(false)
    expect(toastTexts()).toEqual(['Daily AI budget: back to $100.00.'])
  })

  it('for a model, names the server setting it goes back to', async () => {
    mocked.adminConfig.mockResolvedValue(
      config({}, [modelItem({ value: 'claude-opus-5-5', source: 'admin', updated_by: 'owner', updated_at: CHANGED_AT })]),
    )
    const w = await mountPanel()
    expect(row(w, 'model_id').find('[data-test="undo"]').text()).toBe(
      'Undo — back to claude-opus-4-8 (server setting)',
    )
  })
})

describe('access', () => {
  it('a read-only account sees the values but no controls', async () => {
    mocked.adminConfig.mockResolvedValue(config({ can_edit: false }))
    const w = await mountPanel()
    expect(w.find('[data-test="read-only-note"]').text()).toContain(
      'This account can view the settings but not change them.',
    )
    expect(w.findAll('select, input')).toHaveLength(0)
    expect(w.find('[data-test="save"]').exists()).toBe(false)
    expect(w.find('[data-test="undo"]').exists()).toBe(false)
    expect(row(w, 'model_id').find('[data-test="value"]').text()).toBe('claude-opus-4-8')
    const note = row(w, 'model_id').find('[data-test="env-note"]').text()
    expect(note).toContain('claude-opus-5-5')
    expect(note).not.toContain('A change here') // they can't make one
    expect(row(w, 'daily_budget_usd').find('[data-test="source"]').text()).toContain('Changed here by owner')
  })

  it('an expired session (401) reports unauthorized', async () => {
    mocked.adminConfig.mockRejectedValue(new ApiError(401, 'Invalid or expired token'))
    const w = await mountPanel()
    expect(w.emitted('unauthorized')).toHaveLength(1)
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  it('other load failures offer a retry', async () => {
    mocked.adminConfig.mockRejectedValueOnce(new ApiError(503, 'Service Unavailable'))
    const w = await mountPanel()
    const alert = w.find('[role="alert"]')
    expect(alert.text()).toContain(tr('admin.load_error'))
    await alert.find('button').trigger('click')
    await flushPromises()
    expect(row(w, 'model_id').exists()).toBe(true)
  })
})

describe('in Czech', () => {
  it('reads naturally', async () => {
    setLocale('cs')
    const w = await mountPanel()
    expect(row(w, 'model_id').text()).toContain('Hlavní AI model')
    expect(row(w, 'model_id').find('[data-test="source"]').text()).toBe('Nastaveno na serveru (SA_MODEL_ID)')
    expect(row(w, 'sanitizer_model_id').find('[data-test="source"]').text()).toBe('Výchozí hodnota aplikace')
    expect(row(w, 'anthropic_api_key').find('[data-test="value"]').text()).toBe('Nastaveno')
    expect(row(w, 'replicate_api_token').find('[data-test="value"]').text()).toBe('Nenastaveno')
    const rows = w.findAll('[data-test="usage-row"]')
    expect(rows[0].text()).toContain('12 volání')
    expect(rows[1].text()).toContain('cena neznámá')
    expect(row(w, 'daily_budget_usd').find('[data-test="undo"]').text()).toMatch(/^Vrátit zpět na 100,00\s?US\$ \(výchozí hodnota\)$/)
  })
})
