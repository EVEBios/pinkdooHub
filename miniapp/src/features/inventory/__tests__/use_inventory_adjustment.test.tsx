import ReactTestUtil from '@tarojs/test-utils-react'

import { BusinessError, NetworkError } from '@/api'
import type { InventoryAdjustmentResult } from '@/api/endpoints/inventory'

import {
  type InventoryAdjustmentSource,
  useInventoryAdjustment,
} from '../use_inventory_adjustment'

const createdResult: InventoryAdjustmentResult = {
  disposition: 'created',
  adjustment: {
    product_id: 7,
    stock: 15,
    transaction: {
      id: 31,
      product_id: 7,
      transaction_type: 'admin_adjustment',
      change_quantity: 5,
      before_quantity: 10,
      after_quantity: 15,
      reason: '盘点补录',
      source_type: 'admin',
      source_id: null,
      source_order_no: null,
      operator_id: 2,
      operator_nickname: '管理员',
      created_at: '2026-08-28T08:00:00Z',
    },
  },
}

function Harness({
  source,
  createKey,
}: {
  readonly source: InventoryAdjustmentSource
  readonly createKey: () => string
}) {
  const inventory = useInventoryAdjustment(source, createKey)
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
        onClick={() => void inventory.adjustStock(7, { change: 5, reason: '  盘点补录  ' })}
      >adjust</button>
      <button className='retry' onClick={() => void inventory.retrySameIntent()}>retry</button>
    </div>
  )
}

describe('useInventoryAdjustment', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('网络失败不自动重发，安全重试复用完全相同的请求和幂等键', async () => {
    const source: InventoryAdjustmentSource = {
      adjustStock: jest.fn()
        .mockRejectedValueOnce(new NetworkError(
          { operation: 'inventory.admin.adjust' }, new Error('offline'),
        ))
        .mockResolvedValueOnce({ ...createdResult, disposition: 'replayed' }),
    }
    await testUtils.mount(Harness, { props: { source, createKey: () => 'stable-key' } })
    testUtils.fireEvent.click(requireElement(testUtils, '.adjust'))
    await flush(testUtils)

    expect(requireElement(testUtils, '.status').textContent).toBe('unknown')
    expect(requireElement(testUtils, '.message').textContent).toContain('不会自动重发')
    expect(source.adjustStock).toHaveBeenCalledTimes(1)
    testUtils.fireEvent.click(requireElement(testUtils, '.retry'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('replayed')
    expect(source.adjustStock).toHaveBeenCalledTimes(2)
    expect((source.adjustStock as jest.Mock).mock.calls[0]).toEqual(
      (source.adjustStock as jest.Mock).mock.calls[1],
    )
  })

  it('一次意图的重复点击合并为同一个 Promise 和一次写请求', async () => {
    let resolveRequest!: (value: InventoryAdjustmentResult) => void
    const source: InventoryAdjustmentSource = {
      adjustStock: jest.fn(() => new Promise((resolve) => { resolveRequest = resolve })),
    }
    await testUtils.mount(Harness, { props: { source, createKey: () => 'single-key' } })
    const button = requireElement(testUtils, '.adjust')
    testUtils.fireEvent.click(button)
    testUtils.fireEvent.click(button)
    expect(source.adjustStock).toHaveBeenCalledTimes(1)
    await testUtils.act(async () => { resolveRequest(createdResult); await Promise.resolve() })
    expect(requireElement(testUtils, '.status').textContent).toBe('created')
  })

  it('明确业务失败清除旧意图，下一次提交生成新幂等键', async () => {
    const source: InventoryAdjustmentSource = {
      adjustStock: jest.fn()
        .mockRejectedValueOnce(new BusinessError(
          { operation: 'inventory.admin.adjust', statusCode: 409 },
          40932,
          'inventory balance out of range',
          null,
        ))
        .mockResolvedValueOnce(createdResult),
    }
    const keys = ['first-key', 'second-key']
    await testUtils.mount(Harness, { props: { source, createKey: () => keys.shift()! } })
    testUtils.fireEvent.click(requireElement(testUtils, '.adjust'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('failed')
    expect(requireElement(testUtils, '.message').textContent).toContain('0 至 999999')

    testUtils.fireEvent.click(requireElement(testUtils, '.adjust'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('created')
    expect((source.adjustStock as jest.Mock).mock.calls.map((call) => call[2]))
      .toEqual(['first-key', 'second-key'])
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
