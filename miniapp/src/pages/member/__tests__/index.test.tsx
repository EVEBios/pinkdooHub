import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import { AuthenticatedMember } from '../index'

const mockRetry = jest.fn()
let mockAvatar: string | null
let mockNickname: string

jest.mock('@/features/wallet', () => ({
  useMemberWallet: () => ({
    state: {
      status: 'content',
      member: {
        user: {
          id: 7,
          username: 'member_007',
          nickname: mockNickname,
          phone: null,
          avatar: mockAvatar,
          role: 'user',
          status: 'normal',
          last_login_at: null,
          created_at: '2026-09-01T08:00:00Z',
          updated_at: '2026-09-05T08:00:00Z',
        },
        wallet: {
          balance: '280.00',
          balance_limit: '1000.00',
          status: 'active',
          capabilities: { topup_enabled: false, wallet_payment_enabled: true, refund_enabled: true },
        },
      },
    },
    retry: mockRetry,
  }),
}))
jest.mock('@/utils/asset_url', () => ({ resolveAssetUrl: (value: string) => `https://api.example.com${value}` }))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('AuthenticatedMember', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAvatar = '/uploads/avatars/member.webp'
    mockNickname = '拼豆会员'
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('首屏展示身份、权威余额、上限与准确的充值状态', async () => {
    await testUtils.mount(AuthenticatedMember)
    const page = requireElement(testUtils, '.member-page')
    expect(page.textContent).toContain('拼豆会员')
    expect(page.textContent).toContain('¥280.00')
    expect(page.textContent).toContain('¥1000.00')
    expect(page.textContent).toContain('pinkdooHub 自有商品与服务')
    expect(page.textContent).toContain('充值暂未开通')
    expect(page.textContent).toContain('个人资料')
    expect(page.textContent).toContain('未绑定手机号')
    expect(page.textContent).toContain('2026-09-01T08:00:00Z')
    expect(requireElement(testUtils, '.member-profile__avatar').getAttribute('src'))
      .toBe('https://api.example.com/uploads/avatars/member.webp')
    testUtils.fireEvent.click(requireElement(testUtils, '.member-actions__primary'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/wallet-transactions/index' })
    testUtils.fireEvent.click(requireElement(testUtils, '.member-actions__secondary'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/wallet-recharge/index' })
  })

  it('无头像时使用带独立居中样式的昵称首字母', async () => {
    mockAvatar = null
    mockNickname = 'peter'
    await testUtils.mount(AuthenticatedMember)

    expect(requireElement(testUtils, '.member-profile__avatar--fallback').textContent).toBe('p')
    expect(requireElement(testUtils, '.member-profile__avatar-initial').textContent).toBe('p')
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
