import ReactTestUtil from '@tarojs/test-utils-react'

import { AuthenticatedRecharge } from '../index'

const mockSubmit = jest.fn()
let mockTopupEnabled = false

jest.mock('@/features/wallet', () => ({
  moneyToCents: (value: string) => Math.round(Number(value) * 100),
  normalizeMoneyDraft: (value: string) => value ? `${value}.00` : undefined,
  useMemberWallet: () => ({
    state: {
      status: 'content',
      member: {
        user: { status: 'normal' },
        wallet: {
          balance: '280.00', balance_limit: '1000.00', status: 'active',
          capabilities: { topup_enabled: mockTopupEnabled },
        },
      },
    },
    retry: jest.fn(),
  }),
  useRecharge: () => ({ state: { status: 'idle' }, submit: mockSubmit }),
}))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('AuthenticatedRecharge', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockTopupEnabled = false
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('Provider 未就绪时展示范围并硬禁用提交，不制造成功', async () => {
    await testUtils.mount(AuthenticatedRecharge)
    const page = requireElement(testUtils, '.recharge-page')
    expect(page.textContent).toContain('微信支付暂未开通')
    expect(page.textContent).toContain('商户号、小程序 AppID 关联、HTTPS 通知')
    expect(requireElement(testUtils, '.recharge-form__input').getAttribute('placeholder')).toBe('1.00–1000.00')
    expect(requireElement(testUtils, '.recharge-form__submit').getAttribute('disabled')).not.toBeNull()
    expect(mockSubmit).not.toHaveBeenCalled()
  })

  it('服务端能力先开放时仍由客户端支付确认门禁保持禁用', async () => {
    mockTopupEnabled = true
    await testUtils.mount(AuthenticatedRecharge)

    expect(requireElement(testUtils, '.recharge-provider').textContent).toContain('客户端支付确认能力')
    expect(requireElement(testUtils, '.recharge-form__submit').getAttribute('disabled')).not.toBeNull()
    expect(mockSubmit).not.toHaveBeenCalled()
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
