import ReactTestUtil from '@tarojs/test-utils-react'
import { useState } from 'react'

import type {
  WalletTransaction,
  WalletTransactionPage,
} from '@/api/endpoints/wallet'

import {
  type WalletTransactionSource,
  useAdminWalletTransactions,
} from '../use_wallet_transactions'

const timestamp = '2026-09-05T08:00:00Z'

function transaction(id: number, reason: string): WalletTransaction {
  return {
    id,
    transaction_type: 'admin_adjustment',
    direction: 'income',
    change_amount: '10.00',
    before_balance: '0.00',
    after_balance: '10.00',
    source_type: 'admin',
    source_id: null,
    source_order_no: null,
    operator_id: 2,
    operator_nickname: '店长',
    reason,
    created_at: timestamp,
  }
}

function page(item: WalletTransaction): WalletTransactionPage {
  return {
    items: [item],
    total: 1,
    page: 1,
    page_size: 20,
    pages: 1,
  }
}

interface Deferred<T> {
  readonly promise: Promise<T>
  resolve(value: T): void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((complete) => { resolve = complete })
  return { promise, resolve }
}

function AdminLedgerHarness({ source }: { readonly source: WalletTransactionSource }) {
  const [userId, setUserId] = useState(7)
  const { state } = useAdminWalletTransactions(userId, source)
  return (
    <div>
      <span className='scope'>{userId}</span>
      <span className='status'>{state.status}</span>
      <span className='items'>{state.items.map((item) => `${item.id}:${item.reason}`).join(',')}</span>
      <button className='switch' onClick={() => setUserId(8)}>switch</button>
    </div>
  )
}

describe('useAdminWalletTransactions', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('目标 userId 变化的首帧即隐藏上一客户流水并重新加载新 scope', async () => {
    const secondPage = deferred<WalletTransactionPage>()
    const source: WalletTransactionSource = {
      listWalletTransactions: jest.fn(async () => page(transaction(1, '本人流水'))),
      listAdminUserWalletTransactions: jest.fn((userId: number) => userId === 7
        ? Promise.resolve(page(transaction(71, '客户七流水')))
        : secondPage.promise),
    }
    await testUtils.mount(AdminLedgerHarness, { props: { source } })
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('content')
    expect(requireElement(testUtils, '.items').textContent).toContain('71:客户七流水')

    testUtils.fireEvent.click(requireElement(testUtils, '.switch'))
    await flush(testUtils)

    expect(requireElement(testUtils, '.scope').textContent).toBe('8')
    expect(requireElement(testUtils, '.status').textContent).toBe('loading')
    expect(requireElement(testUtils, '.items').textContent).toBe('')
    expect(source.listAdminUserWalletTransactions).toHaveBeenNthCalledWith(
      2,
      8,
      { page: 1, page_size: 20 },
    )

    secondPage.resolve(page(transaction(81, '客户八流水')))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('content')
    expect(requireElement(testUtils, '.items').textContent).toBe('81:客户八流水')
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
