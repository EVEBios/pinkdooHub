import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type { AdminProductListState } from '@/features/product'

import AdminProductsPage, { AuthenticatedAdminProducts } from '../index'

let mockAuth: AuthContextValue
let mockState: AdminProductListState
const mockUseAdminProductList = jest.fn()
const mockApplyFilters = jest.fn()

jest.mock('@/auth', () => ({
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fproducts%2Findex',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/product', () => ({
  ADMIN_PRODUCT_LIST_PATH: '/admin/pages/products/index',
  EMPTY_ADMIN_PRODUCT_FILTERS: { productType: 'all', status: 'all', keyword: '', includeDeleted: false },
  buildAdminProductCreateUrl: (type: string) => `/admin/pages/product-create/index?type=${type}`,
  buildAdminProductDetailUrl: (id: number, type: string) => `/admin/pages/product-detail/index?id=${id}&type=${type}`,
  useAdminProductList: () => mockUseAdminProductList(),
}))

jest.mock('@/utils/asset_url', () => ({ resolveAssetUrl: (url: string) => url }))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('AdminProductsPage', () => {
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
      register: jest.fn(), login: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
    }
    mockState = { status: 'loading', items: [], total: 0, page: 1, pages: 0, loadingMore: false }
    mockUseAdminProductList.mockImplementation(() => ({
      state: mockState,
      filters: { productType: 'all', status: 'all', keyword: '', includeDeleted: false },
      applyFilters: mockApplyFilters,
      retry: jest.fn(),
      loadNextPage: jest.fn(),
    }))
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('普通用户在挂载管理 Hook 前被拒绝', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminProductsPage)
    expect(testUtils.queries.querySelector('.admin-products-state')?.textContent).toContain('无管理权限')
    expect(mockUseAdminProductList).not.toHaveBeenCalled()
  })

  it('Guest 只返回固定管理商品列表', async () => {
    mockAuth = { ...mockAuth, status: 'guest', user: undefined }
    await testUtils.mount(AdminProductsPage)
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-products-state__action'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fproducts%2Findex',
    })
    expect(mockUseAdminProductList).not.toHaveBeenCalled()
  })

  it('展示草稿缺失字段与删除标记，并按类型进入详情', async () => {
    mockState = {
      status: 'content',
      items: [{
        id: 7,
        name: '待配置体验',
        product_type: { value: 'experience', label: '拼豆体验' },
        status: { value: 'draft', label: '草稿' },
        cover_image: null,
        display_price: null,
        updated_at: '2026-08-25T08:00:00Z',
        is_deleted: true,
      }],
      total: 1, page: 1, pages: 1, loadingMore: false,
    }
    await testUtils.mount(AuthenticatedAdminProducts)
    const card = requireElement(testUtils, '.admin-product-card')
    expect(card.textContent).toContain('暂无封面')
    expect(card.textContent).toContain('价格待配置')
    expect(card.textContent).toContain('已删除')
    testUtils.fireEvent.click(card)
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/admin/pages/product-detail/index?id=7&type=experience',
    })
  })

  it('受控筛选只有提交时才应用，并可包含删除记录', async () => {
    await testUtils.mount(AuthenticatedAdminProducts)
    const toggle = requireElement(testUtils, '.admin-product-filters__deleted')
    testUtils.fireEvent.click(toggle)
    expect(mockApplyFilters).not.toHaveBeenCalled()
    const filterCard = requireElement(testUtils, '.admin-product-filters')
    expect(filterCard.firstElementChild).not.toBeNull()
    testUtils.fireEvent.submit(filterCard.firstElementChild!)
    expect(mockApplyFilters).toHaveBeenCalledWith(expect.objectContaining({ includeDeleted: true }))
  })

  it('提供两个类型明确的创建入口', async () => {
    await testUtils.mount(AuthenticatedAdminProducts)
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-products-create__experience'))
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-products-create__kit'))
    expect(Taro.navigateTo).toHaveBeenNthCalledWith(1, {
      url: '/admin/pages/product-create/index?type=experience',
    })
    expect(Taro.navigateTo).toHaveBeenNthCalledWith(2, {
      url: '/admin/pages/product-create/index?type=kit',
    })
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
