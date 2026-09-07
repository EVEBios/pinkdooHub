import ReactTestUtil from '@tarojs/test-utils-react'

import { BusinessError, NetworkError } from '@/api'
import type { AssistedWalletOrderResult } from '@/api/endpoints/wallet'

import {
  type AssistedWalletOrderSource,
  useAssistedWalletOrder,
} from '../use_assisted_wallet_order'

const timestamp = '2026-09-05T08:00:00Z'
const result: AssistedWalletOrderResult = {
  order: {
    id: 201,
    order_no: `OD${'D'.repeat(26)}`,
    user_id: 7,
    user_nickname: '拼豆会员',
    total_amount: '50.00',
    status: { value: 'paid', label: '已支付' },
    remark: '门店代客下单',
    items: [{
      id: 301, product_id: 8, experience_option_id: null, product_name: '拼豆材料套装',
      kit_color_id: null, kit_color_slot_no: null, kit_color_code: null, kit_color_name: null,
      sale_unit_grams: null, total_weight_grams: null,
      option_duration_minutes: null, option_participants: null, option_day_type: null,
      product_price: '25.00', quantity: 2, subtotal: '50.00',
    }],
    created_at: timestamp,
    updated_at: timestamp,
  },
  payment: {
    id: 18,
    payment_no: `PY${'C'.repeat(26)}`,
    order_id: 201,
    recharge_order_id: null,
    purpose: 'order',
    method: 'wallet',
    amount: '50.00',
    status: 'succeeded',
    created_at: timestamp,
    updated_at: timestamp,
    succeeded_at: timestamp,
  },
  post_payment_balance: '230.00',
}

function Harness({ createKey, source }: {
  readonly source: AssistedWalletOrderSource
  readonly createKey: () => string
}) {
  const order = useAssistedWalletOrder(7, source, createKey)
  return (
    <div>
      <span className='status'>{order.state.status}</span>
      <span className='message'>
        {order.state.status === 'failed' || order.state.status === 'unknown'
          ? order.state.errorMessage
          : ''}
      </span>
      <button
        className='create'
        onClick={() => void order.createOrder({
          items: [{ product_id: 8, quantity: 2 }],
          remark: '  门店代客下单  ',
        })}
      >create</button>
      <button className='retry' onClick={() => void order.retrySameIntent()}>retry</button>
    </div>
  )
}

describe('useAssistedWalletOrder', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('网络失败不自动重发，显式安全重试复用同一请求和幂等键', async () => {
    const source: AssistedWalletOrderSource = {
      createAssistedWalletOrder: jest.fn()
        .mockRejectedValueOnce(new NetworkError(
          { operation: 'wallet.admin.order.create' },
          new Error('offline'),
        ))
        .mockResolvedValueOnce(result),
    }
    await testUtils.mount(Harness, { props: { source, createKey: () => 'stable-key' } })
    testUtils.fireEvent.click(requireElement(testUtils, '.create'))
    await flush(testUtils)

    expect(requireElement(testUtils, '.status').textContent).toBe('unknown')
    expect(requireElement(testUtils, '.message').textContent).toContain('不会自动重发')
    expect(source.createAssistedWalletOrder).toHaveBeenCalledTimes(1)
    testUtils.fireEvent.click(requireElement(testUtils, '.retry'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('succeeded')
    expect(source.createAssistedWalletOrder).toHaveBeenCalledTimes(2)
    expect((source.createAssistedWalletOrder as jest.Mock).mock.calls[0])
      .toEqual((source.createAssistedWalletOrder as jest.Mock).mock.calls[1])
  })

  it('明确库存失败释放旧意图，下一次提交使用新幂等键', async () => {
    const source: AssistedWalletOrderSource = {
      createAssistedWalletOrder: jest.fn()
        .mockRejectedValueOnce(new BusinessError(
          { operation: 'wallet.admin.order.create', statusCode: 409 },
          40931,
          'stock insufficient',
          null,
        ))
        .mockResolvedValueOnce(result),
    }
    const keys = ['first-key', 'second-key']
    await testUtils.mount(Harness, { props: { source, createKey: () => keys.shift()! } })
    testUtils.fireEvent.click(requireElement(testUtils, '.create'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('failed')
    expect(requireElement(testUtils, '.message').textContent).toContain('库存不足')

    testUtils.fireEvent.click(requireElement(testUtils, '.create'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('succeeded')
    expect((source.createAssistedWalletOrder as jest.Mock).mock.calls.map((call) => call[2]))
      .toEqual(['first-key', 'second-key'])
  })

  it('后端 500 业务信封进入 unknown，显式重试保留原内容与幂等键', async () => {
    const source: AssistedWalletOrderSource = {
      createAssistedWalletOrder: jest.fn()
        .mockRejectedValueOnce(new BusinessError(
          { operation: 'wallet.admin.order.create', statusCode: 500 },
          500,
          'Internal server error',
          null,
        ))
        .mockResolvedValueOnce(result),
    }
    const keys = ['stable-500-key', 'must-not-be-used']
    await testUtils.mount(Harness, { props: { source, createKey: () => keys.shift()! } })
    testUtils.fireEvent.click(requireElement(testUtils, '.create'))
    await flush(testUtils)

    expect(requireElement(testUtils, '.status').textContent).toBe('unknown')
    testUtils.fireEvent.click(requireElement(testUtils, '.retry'))
    await flush(testUtils)

    expect(requireElement(testUtils, '.status').textContent).toBe('succeeded')
    expect((source.createAssistedWalletOrder as jest.Mock).mock.calls[0])
      .toEqual((source.createAssistedWalletOrder as jest.Mock).mock.calls[1])
    expect(keys).toEqual(['must-not-be-used'])
  })

  it('管理资金写开关关闭时展示代客扣款专用 503 文案', async () => {
    const source: AssistedWalletOrderSource = {
      createAssistedWalletOrder: jest.fn(async () => {
        throw new BusinessError(
          { operation: 'wallet.admin.order.create', statusCode: 503 },
          50301,
          'admin wallet write unavailable',
          null,
        )
      }),
    }
    await testUtils.mount(Harness, { props: { source, createKey: () => 'disabled-key' } })
    testUtils.fireEvent.click(requireElement(testUtils, '.create'))
    await flush(testUtils)

    expect(requireElement(testUtils, '.status').textContent).toBe('failed')
    expect(requireElement(testUtils, '.message').textContent).toContain('管理员代客商品扣款能力暂未开放')
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
