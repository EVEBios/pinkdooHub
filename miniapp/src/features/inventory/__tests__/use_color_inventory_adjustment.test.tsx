import ReactTestUtil from '@tarojs/test-utils-react'

import { BusinessError, NetworkError } from '@/api'
import type { InventoryColorAdjustmentResult } from '@/api/endpoints/inventory'

import {
  type ColorInventoryAdjustmentSource,
  useColorInventoryAdjustment,
} from '../use_color_inventory_adjustment'

const createdResult: InventoryColorAdjustmentResult = {
  disposition: 'created',
  adjustment: {
    product_id: 7,
    kit_color_id: 701,
    bead_color_id: 21,
    bead_color_slot_no: 21,
    color_code: 'A21',
    color_name: '樱桃红',
    sale_unit_grams: 10,
    stock_units: 5,
    transaction: {
      id: 32,
      product_id: 7,
      kit_color_id: 701,
      bead_color_id: 21,
      bead_color_slot_no: 21,
      color_code: 'A21',
      color_name: '樱桃红',
      sale_unit_grams: 10,
      transaction_type: 'admin_adjustment',
      change_quantity: 3,
      before_quantity: 2,
      after_quantity: 5,
      reason: '颜色补货',
      source_type: 'admin',
      source_id: null,
      source_order_no: null,
      operator_id: 2,
      operator_nickname: '管理员',
      created_at: '2026-09-06T08:00:00Z',
    },
  },
}

function Harness({ createKey, source }: {
  readonly createKey: () => string
  readonly source: ColorInventoryAdjustmentSource
}) {
  const inventory = useColorInventoryAdjustment(source, createKey)
  return (
    <div>
      <span className='status'>{inventory.state.status}</span>
      <span className='message'>
        {inventory.state.status === 'failed' || inventory.state.status === 'unknown'
          ? inventory.state.errorMessage
          : ''}
      </span>
      <button
        className='adjust'
        onClick={() => void inventory.adjustColorStock(
          7,
          701,
          { change: 3, reason: '  颜色补货  ' },
        )}
      >adjust</button>
      <button className='retry' onClick={() => void inventory.retrySameIntent()}>retry</button>
    </div>
  )
}

describe('useColorInventoryAdjustment', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('未知结果不自动重发，显式安全重试复用颜色身份、请求和幂等键', async () => {
    const source: ColorInventoryAdjustmentSource = {
      adjustColorStock: jest.fn()
        .mockRejectedValueOnce(new NetworkError(
          { operation: 'inventory.admin.color.adjust' },
          new Error('offline'),
        ))
        .mockResolvedValueOnce({ ...createdResult, disposition: 'replayed' }),
    }
    await testUtils.mount(Harness, { props: { source, createKey: () => 'stable-color-key' } })
    testUtils.fireEvent.click(requireElement(testUtils, '.adjust'))
    await flush(testUtils)

    expect(requireElement(testUtils, '.status').textContent).toBe('unknown')
    expect(requireElement(testUtils, '.message').textContent).toContain('不会自动重发')
    expect(source.adjustColorStock).toHaveBeenCalledTimes(1)

    testUtils.fireEvent.click(requireElement(testUtils, '.retry'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('replayed')
    expect(source.adjustColorStock).toHaveBeenCalledTimes(2)
    expect((source.adjustColorStock as jest.Mock).mock.calls[0]).toEqual(
      (source.adjustColorStock as jest.Mock).mock.calls[1],
    )
    expect((source.adjustColorStock as jest.Mock).mock.calls[0]).toEqual([
      7,
      701,
      { change: 3, reason: '颜色补货' },
      'stable-color-key',
    ])
  })

  it('明确的商品颜色不存在会清除旧意图，下一次提交生成新 key', async () => {
    const source: ColorInventoryAdjustmentSource = {
      adjustColorStock: jest.fn()
        .mockRejectedValueOnce(new BusinessError(
          { operation: 'inventory.admin.color.adjust', statusCode: 404 },
          40406,
          'Product kit color not found',
          null,
        ))
        .mockResolvedValueOnce(createdResult),
    }
    const keys = ['first-color-key', 'second-color-key']
    await testUtils.mount(Harness, { props: { source, createKey: () => keys.shift()! } })

    testUtils.fireEvent.click(requireElement(testUtils, '.adjust'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('failed')
    expect(requireElement(testUtils, '.message').textContent).toContain('商品颜色')

    testUtils.fireEvent.click(requireElement(testUtils, '.adjust'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('created')
    expect((source.adjustColorStock as jest.Mock).mock.calls.map((call) => call[3]))
      .toEqual(['first-color-key', 'second-color-key'])
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}
