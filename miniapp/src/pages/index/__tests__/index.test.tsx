import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type { ProductListState } from '@/features/product/use_product_list'

import ProductListPage from '../index'

const mockRetry = jest.fn()
const mockLoadNextPage = jest.fn()
const mockSetKeyword = jest.fn()
const mockSetProductType = jest.fn()
const mockUseRootTabSelection = jest.fn()
const mockUseProductList = jest.fn()
let mockAuth: AuthContextValue
let mockProductListState: ProductListState

jest.mock('@/auth', () => ({
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/product/use_product_list', () => ({
  useProductList: () => mockUseProductList.mockReturnValue({
    state: mockProductListState,
    productType: 'all',
    keyword: '',
    setKeyword: mockSetKeyword,
    setProductType: mockSetProductType,
    retry: mockRetry,
    loadNextPage: mockLoadNextPage,
  })(),
}))

jest.mock('@/navigation/root_tabs', () => ({
  ROOT_TAB_INDEX: { mall: 0, reservations: 1, orders: 2, member: 3 },
  useRootTabSelection: (index: number) => mockUseRootTabSelection(index),
}))

jest.mock('@/utils/asset_url', () => ({
  resolveAssetUrl: (assetUrl: string) => assetUrl.startsWith('/')
    ? `https://api.example.com${assetUrl}`
    : assetUrl,
}))

describe('ProductListPage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = createAuth('user')
    mockProductListState = {
      status: 'loading',
      items: [],
      total: 0,
      page: 1,
      pages: 0,
      loadingMore: false,
    }
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it.each([
    ['loading', '正在加载商品…'],
    ['empty', '暂时没有可浏览的商品'],
    ['error', '商品加载失败'],
  ] as const)('渲染 %s 状态', async (status, expectedText) => {
    mockProductListState = {
      ...mockProductListState,
      status,
      errorMessage: status === 'error' ? '网络请求失败' : undefined,
    }
    await testUtils.mount(ProductListPage)

    expect(testUtils.queries.querySelector('.product-page__state')?.textContent)
      .toContain(expectedText)
  })

  it('按体验、固定套装、自选颜色套装显示准确价格单位', async () => {
    mockProductListState = {
      status: 'content',
      items: [
        {
          id: 1,
          name: '周末拼豆体验',
          product_type: { value: 'experience', label: '拼豆体验' },
          cover_image: '/uploads/products/experience.webp',
          display_price: '299.00',
          kit_kind: null,
          sale_unit_grams: null,
        },
        {
          id: 2,
          name: '基础拼豆套装',
          product_type: { value: 'kit', label: '拼豆套装' },
          cover_image: 'https://cdn.example.com/kit.webp',
          display_price: '599.00',
          kit_kind: { value: 'fixed', label: '固定套装' },
          sale_unit_grams: null,
        },
        {
          id: 3,
          name: '自选颜色拼豆',
          product_type: { value: 'kit', label: '拼豆套装' },
          cover_image: 'https://cdn.example.com/color-kit.webp',
          display_price: '2.50',
          kit_kind: { value: 'color_selectable', label: '自选颜色' },
          sale_unit_grams: 10,
        },
      ],
      total: 3,
      page: 1,
      pages: 1,
      loadingMore: false,
    }
    await testUtils.mount(ProductListPage)

    const cards = testUtils.queries.querySelectorAll('.product-card')
    expect(cards).toHaveLength(3)
    expect(cards[0].textContent).toContain('¥299.00 起')
    expect(cards[1].textContent).toContain('¥599.00')
    expect(cards[1].textContent).not.toContain('¥599.00 起')
    expect(cards[2].textContent).toContain('¥2.50 / 10g')
    expect(testUtils.queries.querySelector('.product-page__end')?.textContent)
      .toContain('已经到底了')
  })

  it('渲染搜索和类型筛选并传递用户操作', async () => {
    await testUtils.mount(ProductListPage)

    const header = testUtils.queries.querySelector('.product-page__header')
    expect(header?.textContent).toContain('pinkdooHub')
    expect(header?.textContent).not.toContain('拼豆店')
    expect(testUtils.queries.querySelector('.product-filters__search')).not.toBeNull()
    const buttons = testUtils.queries.querySelectorAll('.product-filters__type')
    expect(buttons).toHaveLength(3)
    testUtils.fireEvent.click(buttons[2])
    expect(mockSetProductType).toHaveBeenCalledWith('kit')
  })

  it('商城只保留品牌、介绍与商品功能，不再承载账户或管理入口', async () => {
    await testUtils.mount(ProductListPage)

    const page = testUtils.queries.querySelector('.product-page')
    expect(page?.textContent).toContain('发现下一幅拼豆作品')
    expect(testUtils.queries.querySelector('.product-filters')).not.toBeNull()
    expect(testUtils.queries.querySelector('.product-page__account')).toBeNull()
    expect(page?.textContent).not.toContain('登录')
    expect(page?.textContent).not.toContain('退出')
    expect(page?.textContent).not.toContain('会员中心')
    expect(page?.textContent).not.toContain('我的预约')
    expect(page?.textContent).not.toContain('我的订单')
    expect(page?.textContent).not.toContain('店铺管理')
    expect(mockUseRootTabSelection).toHaveBeenCalledWith(0)
  })

  it.each(['admin', 'super_admin'] as const)('%s 不挂载商城请求并自动进入店铺工作台', async (role) => {
    mockAuth = createAuth(role)
    await testUtils.mount(ProductListPage)

    expect(testUtils.queries.querySelector('.admin-workbench-redirect')?.textContent)
      .toContain('正在进入店铺工作台')
    expect(mockUseProductList).not.toHaveBeenCalled()
    expect(mockUseRootTabSelection).not.toHaveBeenCalled()
    await testUtils.act(async () => { await Promise.resolve() })
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
  })

  it('未知运行时角色保持 fail closed 且不挂载商城请求', async () => {
    mockAuth = {
      ...createAuth('user'),
      user: { ...createAuth('user').user!, role: 'staff' as 'user' },
    }
    await testUtils.mount(ProductListPage)

    expect(testUtils.queries.querySelector('.product-page--gate')?.textContent)
      .toContain('账户角色暂不支持')
    expect(mockUseProductList).not.toHaveBeenCalled()
    expect(mockUseRootTabSelection).not.toHaveBeenCalled()
  })

  it('认证初始化失败时不挂载商城请求，并允许重新检查', async () => {
    mockAuth = {
      ...mockAuth,
      status: 'error',
      user: undefined,
      initializationError: new Error('storage unavailable'),
    }
    await testUtils.mount(ProductListPage)

    expect(testUtils.queries.querySelector('.product-page--gate')?.textContent)
      .toContain('storage unavailable')
    expect(mockUseProductList).not.toHaveBeenCalled()
    testUtils.fireEvent.click(requireElement(testUtils, '.product-page__state-action'))
    expect(mockAuth.retryInitialization).toHaveBeenCalledTimes(1)
  })
})

function createAuth(role: 'user' | 'admin' | 'super_admin'): AuthContextValue {
  return {
    status: 'authenticated',
    user: {
      id: 7,
      username: 'member_007',
      nickname: '拼豆伙伴',
      phone: null,
      avatar: null,
      role,
      status: 'normal',
      last_login_at: null,
      created_at: '2026-09-01T08:00:00Z',
      updated_at: '2026-09-05T08:00:00Z',
    },
    register: jest.fn(),
    updateProfile: jest.fn(),
    login: jest.fn(),
    loginWithWechat: jest.fn(),
    logout: jest.fn(),
    retryInitialization: jest.fn(),
  }
}

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
