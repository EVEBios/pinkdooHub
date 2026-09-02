import ReactTestUtil from '@tarojs/test-utils-react'
import { useState } from 'react'

import { MaskedDateInput, normalizeCompactDateInput } from '../masked_date_input'

describe('MaskedDateInput', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
  })

  afterEach(() => {
    testUtils.unmout()
  })

  it('使用单个数字输入源并始终渲染固定横杠', async () => {
    await testUtils.mount(Harness)
    const field = requireElement(testUtils, '.masked-date-input__field')
    const input = requireElement(testUtils, '.masked-date-input__native')
    expect(field.textContent).toContain('YYYY-MM-DD')
    expect(input.getAttribute('type')).toBe('number')
    expect(input.getAttribute('maxlength')).toBe('8')

    inputValue(testUtils, input, '20260208')
    expect(field.textContent).toContain('2026-02-08')
    expect(input.getAttribute('value')).toBe('20260208')
  })

  it('清除显示值后恢复固定日期占位', async () => {
    await testUtils.mount(Harness)
    inputValue(testUtils, requireElement(testUtils, '.masked-date-input__native'), '20260208')
    testUtils.fireEvent.click(requireElement(testUtils, '.masked-date-input__clear'))
    expect(requireElement(testUtils, '.masked-date-input__field').textContent).toContain('YYYY-MM-DD')
    expect(requireElement(testUtils, '.masked-date-input__native').getAttribute('value')).toBe('')
  })

  it('只保留前 8 位数字作为真实输入值', async () => {
    await testUtils.mount(Harness)
    expect(normalizeCompactDateInput('2026-02-08')).toBe('20260208')
    expect(normalizeCompactDateInput('2026020812')).toBe('20260208')
    expect(normalizeCompactDateInput('date')).toBe('')
  })
})

function Harness() {
  const [value, setValue] = useState('')
  return <MaskedDateInput label='开始日期（UTC）' value={value} onChange={setValue} />
}

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

function inputValue(testUtils: ReactTestUtil, element: Element, value: string): void {
  const fireCustomEvent = testUtils.fireEvent as unknown as (target: Element, event: Event) => void
  fireCustomEvent(element, new CustomEvent('input', { bubbles: true, detail: { value } }))
}
