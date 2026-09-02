import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'

import ProductAuditPage, { AuthenticatedProductAudit } from '../index'

let mockAuth: AuthContextValue
const mockUseProductAuditList = jest.fn()

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { navigateTo: jest.fn(), redirectTo: jest.fn() },
  useRouter: () => ({ params: { id: '7', type: 'experience' } }),
}))

jest.mock('@/auth', () => ({
  buildLoginUrl: () => '/pages/login/index?redirect=admin-products',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/audit', () => ({
  parseProductAuditRoute: () => ({ productId: 7, productType: 'experience' }),
  useProductAuditList: (...args: unknown[]) => mockUseProductAuditList(...args),
}))

jest.mock('@/features/product', () => ({
  ADMIN_PRODUCT_LIST_PATH: '/admin/pages/products/index',
  buildAdminProductDetailUrl: (id: number, type: string) => `/admin/pages/product-detail/index?id=${id}&type=${type}`,
}))

describe('ProductAuditPage', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'authenticated',
      user: {
        id: 2, username: 'admin', nickname: '管理员', avatar: null, phone: '13800000000',
        role: 'admin', status: 'normal', last_login_at: null,
        created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
      },
      register: jest.fn(), login: jest.fn(), loginWithWechat: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
    }
    mockUseProductAuditList.mockReturnValue({
      state: { status: 'loading' }, retry: jest.fn(), loadNextPage: jest.fn(),
    })
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('普通用户在页面边界被拒绝且不挂载审计 Hook', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(ProductAuditPage)
    expect(testUtils.queries.querySelector('.product-audit-state')?.textContent).toContain('无管理权限')
    expect(mockUseProductAuditList).not.toHaveBeenCalled()
  })

  it('只展示审计白名单并返回原商品详情', async () => {
    mockUseProductAuditList.mockReturnValue({
      state: {
        status: 'content',
        items: [{
          id: 3, operator_id: 2, action: 'UPDATE_PRODUCT', target_type: 'product', target_id: 7,
          description: '更新名称', ip_address: '127.0.0.1', created_at: '2026-08-28T08:00:00Z',
        }],
        total: 1, page: 1, pages: 1, loadingMore: false,
      },
      retry: jest.fn(), loadNextPage: jest.fn(),
    })
    await testUtils.mount(AuthenticatedProductAudit, { props: { productId: 7, productType: 'experience' } })
    const card = requireElement(testUtils, '.product-audit-card')
    expect(card.textContent).toContain('修改基本信息')
    expect(card.textContent).toContain('操作人 ID：2')
    testUtils.fireEvent.click(requireElement(testUtils, '.product-audit-page__back'))
    expect(Taro.redirectTo).toHaveBeenCalledWith({
      url: '/admin/pages/product-detail/index?id=7&type=experience',
    })
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
