import ReactTestUtil from '@tarojs/test-utils-react'

import { BusinessError, NetworkError } from '@/api'
import type { WalletAdjustmentResult } from '@/api/endpoints/wallet'

import {
  type AdminWalletAdjustmentSource,
  useAdminWalletAdjustment,
} from '../use_admin_wallet_adjustment'

const timestamp = '2026-09-05T08:00:00Z'
const result: WalletAdjustmentResult = {
  wallet: {
    wallet_id: 4,
    user_id: 7,
    balance: '280.00',
    balance_limit: '1000.00',
    status: 'active',
    capabilities: {
      topup_enabled: false,
      wallet_payment_enabled: true,
      refund_enabled: true,
    },
    created_at: timestamp,
    updated_at: timestamp,
  },
  transaction: {
    id: 31,
    transaction_type: 'admin_adjustment',
    direction: 'income',
    change_amount: '20.00',
    before_balance: '260.00',
    after_balance: '280.00',
    source_type: 'admin',
    source_id: null,
    source_order_no: null,
    operator_id: 2,
    operator_nickname: '店长',
    reason: '线下差额纠正',
    created_at: timestamp,
  },
}

function Harness({ createKey, source }: {
  readonly source: AdminWalletAdjustmentSource
  readonly createKey: () => string
}) {
  const adjustment = useAdminWalletAdjustment(7, source, createKey)
  return (
    <div>
      <span className='status'>{adjustment.state.status}</span>
      <span className='message'>
        {adjustment.state.status === 'failed' || adjustment.state.status === 'unknown'
          ? adjustment.state.errorMessage
          : ''}
      </span>
      <button
        className='submit-original'
        onClick={() => void adjustment.submit('20.00', '线下差额纠正')}
      >submit original</button>
      <button
        className='submit-edited'
        onClick={() => void adjustment.submit('-30.00', '网络未知后编辑的新原因')}
      >submit edited</button>
      <button
        className='retry'
        onClick={() => void adjustment.retrySameIntent()}
      >retry</button>
    </div>
  )
}

describe('useAdminWalletAdjustment', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('在途时忽略新方向、金额和原因，只发送首次意图', async () => {
    let resolveRequest!: (value: WalletAdjustmentResult) => void
    const source: AdminWalletAdjustmentSource = {
      adjustAdminUserWallet: jest.fn(() => new Promise((resolve) => {
        resolveRequest = resolve
      })),
    }
    const createKey = jest.fn(() => 'in-flight-key')
    await testUtils.mount(Harness, { props: { source, createKey } })

    testUtils.fireEvent.click(requireElement(testUtils, '.submit-original'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('submitting')

    testUtils.fireEvent.click(requireElement(testUtils, '.submit-edited'))
    await flush(testUtils)

    expect(source.adjustAdminUserWallet).toHaveBeenCalledTimes(1)
    expect(source.adjustAdminUserWallet).toHaveBeenCalledWith(
      7,
      { change: '20.00', reason: '线下差额纠正' },
      'in-flight-key',
    )
    expect(createKey).toHaveBeenCalledTimes(1)

    resolveRequest(result)
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('succeeded')
  })

  it.each([
    [
      '网络失败',
      new NetworkError(
        { operation: 'wallet.admin.adjust' },
        new Error('offline'),
      ),
    ],
    [
      'HTTP 500 业务信封',
      new BusinessError(
        { operation: 'wallet.admin.adjust', statusCode: 500 },
        500,
        'Internal server error',
        null,
      ),
    ],
  ])('%s 进入 unknown，编辑后 submit 不生成新 key，显式重试原样复用 request+key', async (_label, cause) => {
    const source: AdminWalletAdjustmentSource = {
      adjustAdminUserWallet: jest.fn()
        .mockRejectedValueOnce(cause)
        .mockResolvedValueOnce(result),
    }
    const keys = ['stable-key', 'must-not-be-used']
    const createKey = jest.fn(() => keys.shift()!)
    await testUtils.mount(Harness, { props: { source, createKey } })

    testUtils.fireEvent.click(requireElement(testUtils, '.submit-original'))
    await flush(testUtils)

    expect(requireElement(testUtils, '.status').textContent).toBe('unknown')
    expect(requireElement(testUtils, '.message').textContent).toContain('原样复用同一方向、金额、原因和操作标识')

    testUtils.fireEvent.click(requireElement(testUtils, '.submit-edited'))
    await flush(testUtils)
    expect(source.adjustAdminUserWallet).toHaveBeenCalledTimes(1)
    expect(createKey).toHaveBeenCalledTimes(1)

    testUtils.fireEvent.click(requireElement(testUtils, '.retry'))
    await flush(testUtils)

    expect(requireElement(testUtils, '.status').textContent).toBe('succeeded')
    expect(source.adjustAdminUserWallet).toHaveBeenCalledTimes(2)
    expect((source.adjustAdminUserWallet as jest.Mock).mock.calls[0])
      .toEqual((source.adjustAdminUserWallet as jest.Mock).mock.calls[1])
    expect(createKey).toHaveBeenCalledTimes(1)
    expect(keys).toEqual(['must-not-be-used'])
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
