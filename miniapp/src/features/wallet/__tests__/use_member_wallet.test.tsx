import ReactTestUtil from '@tarojs/test-utils-react'

import type { MemberWallet } from '@/api/endpoints/wallet'

import { type MemberWalletSource, useMemberWallet } from '../use_member_wallet'

let mockRefreshAfterReturn: (() => void) | undefined

jest.mock('@/platform/use_refresh_after_page_return', () => ({
  useRefreshAfterPageReturn: (refresh: () => void) => { mockRefreshAfterReturn = refresh },
}))

const member: MemberWallet = {
  user: {
    id: 7,
    username: 'member_007',
    nickname: '拼豆会员',
    phone: null,
    avatar: null,
    role: 'user',
    status: 'normal',
    last_login_at: null,
    created_at: '2026-09-01T08:00:00Z',
    updated_at: '2026-09-05T08:00:00Z',
  },
  wallet: {
    wallet_id: 3,
    user_id: 7,
    balance: '280.00',
    balance_limit: '1000.00',
    status: 'active',
    capabilities: {
      topup_enabled: false,
      wallet_payment_enabled: true,
      refund_enabled: true,
    },
    created_at: '2026-09-01T08:00:00Z',
    updated_at: '2026-09-05T08:00:00Z',
  },
}

function Harness({ source }: { readonly source: MemberWalletSource }) {
  const { state } = useMemberWallet(source)
  return (
    <div>
      <span className='status'>{state.status}</span>
      <span className='balance'>{state.status === 'content' ? state.member.wallet.balance : ''}</span>
      <span className='refresh-error'>
        {state.status === 'content' ? state.refreshErrorMessage ?? '' : ''}
      </span>
    </div>
  )
}

describe('useMemberWallet 页面返回刷新', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockRefreshAfterReturn = undefined
  })

  afterEach(() => testUtils.unmout())

  it('首次挂载只请求一次，再次展示时保留余额直到权威响应返回', async () => {
    const refreshed = deferred<MemberWallet>()
    const source: MemberWalletSource = {
      getMemberWallet: jest.fn()
        .mockResolvedValueOnce(member)
        .mockImplementationOnce(() => refreshed.promise),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    expect(source.getMemberWallet).toHaveBeenCalledTimes(1)

    await testUtils.act(async () => { mockRefreshAfterReturn?.() })
    expect(source.getMemberWallet).toHaveBeenCalledTimes(2)
    expect(required(testUtils, '.status').textContent).toBe('content')
    expect(required(testUtils, '.balance').textContent).toBe('280.00')

    refreshed.resolve({
      ...member,
      wallet: { ...member.wallet, balance: '320.00' },
    })
    await flush(testUtils)
    expect(required(testUtils, '.balance').textContent).toBe('320.00')
  })

  it('静默刷新失败时保留已显示的权威快照并暴露刷新错误', async () => {
    const source: MemberWalletSource = {
      getMemberWallet: jest.fn()
        .mockResolvedValueOnce(member)
        .mockRejectedValueOnce(new Error('offline')),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)

    await testUtils.act(async () => { mockRefreshAfterReturn?.() })
    await flush(testUtils)
    expect(required(testUtils, '.status').textContent).toBe('content')
    expect(required(testUtils, '.balance').textContent).toBe('280.00')
    expect(required(testUtils, '.refresh-error').textContent).toBe('offline')
  })
})

function required(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => { resolve = promiseResolve })
  return { promise, resolve }
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}
