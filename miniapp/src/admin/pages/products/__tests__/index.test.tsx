import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type { AdminProductListState } from '@/features/product'

import AdminProductsPage, { AuthenticatedAdminProducts } from '../index'

let mockAuth: AuthContextValue
let mockState: AdminProductListState
let mockFilters: {
  productType: 'all' | 'experience' | 'kit'
  status: 'all' | 'draft' | 'online' | 'offline'
  keyword: string
  includeDeleted: boolean
}
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
    mockFilters = { productType: 'all', status: 'all', keyword: '', includeDeleted: false }
    mockUseAdminProductList.mockImplementation(() => ({
      state: mockState,
      filters: mockFilters,
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

  it('按钮立即组合已提交文字筛选，输入文字仍等待查询提交', async () => {
    mockFilters = { productType: 'experience', status: 'draft', keyword: '已提交名称', includeDeleted: false }
    await testUtils.mount(AuthenticatedAdminProducts)

    input(testUtils, requireElement(testUtils, '.admin-product-filters__input'), '新输入名称')
    expect(mockApplyFilters).not.toHaveBeenCalled()
    expect(requireElement(testUtils, '.admin-product-filters__pending').textContent).toContain('尚未应用')

    testUtils.fireEvent.click(findButton(testUtils, '材料套装'))
    expect(mockApplyFilters).toHaveBeenLastCalledWith({
      productType: 'kit', status: 'draft', keyword: '已提交名称', includeDeleted: false,
    })

    const filterCard = requireElement(testUtils, '.admin-product-filters')
    expect(filterCard.firstElementChild).not.toBeNull()
    testUtils.fireEvent.submit(filterCard.firstElementChild!)
    expect(mockApplyFilters).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: '新输入名称' }))
    expect(testUtils.queries.querySelector('.admin-product-filters__pending')).toBeNull()
  })

  it('删除记录使用两个按钮并立即查询', async () => {
    await testUtils.mount(AuthenticatedAdminProducts)
    const buttons = Array.from(testUtils.queries.querySelectorAll('.admin-product-filters__deleted'))
    expect(buttons.map((button) => button.textContent)).toEqual(['不含删除记录', '包含删除记录'])
    testUtils.fireEvent.click(findButton(testUtils, '包含删除记录'))
    expect(mockApplyFilters).toHaveBeenCalledWith({
      productType: 'all', status: 'all', keyword: '', includeDeleted: true,
    })
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

function findButton(testUtils: ReactTestUtil, label: string): Element {
  const button = Array.from(testUtils.queries.querySelectorAll(
    '.admin-product-filters__button, .admin-product-filters__deleted',
  ))
    .find((candidate) => candidate.textContent === label)
  if (!button) throw new Error(`button ${label} not found`)
  return button
}

function input(testUtils: ReactTestUtil, element: Element, value: string): void {
  const fireCustomEvent = testUtils.fireEvent as unknown as (target: Element, event: Event) => void
  fireCustomEvent(element, new CustomEvent('input', { bubbles: true, detail: { value } }))
}
