import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { ProductListState } from '@/features/product/use_product_list'
import type { AuthContextValue } from '@/auth'

import ProductListPage from '../index'

const mockRetry = jest.fn()
const mockLoadNextPage = jest.fn()
const mockSetKeyword = jest.fn()
const mockSetProductType = jest.fn()
let mockProductListState: ProductListState
let mockAuth: AuthContextValue

jest.mock('@/features/product/use_product_list', () => ({
  useProductList: () => ({
    state: mockProductListState,
    productType: 'all',
    keyword: '',
    setKeyword: mockSetKeyword,
    setProductType: mockSetProductType,
    retry: mockRetry,
    loadNextPage: mockLoadNextPage,
  }),
}))

jest.mock('@/auth', () => ({
  ADMIN_INVENTORY_LIST_PATH: '/admin/pages/inventory-transactions/index',
  ADMIN_ORDER_LIST_PATH: '/admin/pages/orders/index',
  ADMIN_PRODUCT_LIST_PATH: '/admin/pages/products/index',
  ADMIN_USER_LIST_PATH: '/admin/pages/users/index',
  useAuth: () => mockAuth,
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
    mockProductListState = {
      status: 'loading',
      items: [],
      total: 0,
      page: 1,
      pages: 0,
      loadingMore: false,
    }
    mockAuth = {
      status: 'guest',
      register: jest.fn(),
      login: jest.fn(),
      loginWithWechat: jest.fn(),
      logout: jest.fn(),
      retryInitialization: jest.fn(),
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

  it('渲染 Product 内容并只给体验商品添加起价后缀', async () => {
    mockProductListState = {
      status: 'content',
      items: [
        {
          id: 1,
          name: '周末拼豆体验',
          product_type: { value: 'experience', label: '拼豆体验' },
          cover_image: '/uploads/products/experience.webp',
          display_price: '299.00',
        },
        {
          id: 2,
          name: '基础拼豆套装',
          product_type: { value: 'kit', label: '拼豆套装' },
          cover_image: 'https://cdn.example.com/kit.webp',
          display_price: '599.00',
        },
      ],
      total: 2,
      page: 1,
      pages: 1,
      loadingMore: false,
    }
    await testUtils.mount(ProductListPage)

    const cards = testUtils.queries.querySelectorAll('.product-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].textContent).toContain('¥299.00 起')
    expect(cards[1].textContent).toContain('¥599.00')
    expect(cards[1].textContent).not.toContain('¥599.00 起')
    expect(testUtils.queries.querySelector('.product-page__end')?.textContent)
      .toContain('已经到底了')
  })

  it('渲染搜索和类型筛选并传递用户操作', async () => {
    await testUtils.mount(ProductListPage)

    expect(testUtils.queries.querySelector('.product-filters__search')).not.toBeNull()
    const buttons = testUtils.queries.querySelectorAll('.product-filters__type')
    expect(buttons).toHaveLength(3)
    testUtils.fireEvent.click(buttons[2])
    expect(mockSetProductType).toHaveBeenCalledWith('kit')
  })

  it('只为 ADMIN+ 展示三类管理入口', async () => {
    const baseUser = {
      id: 2,
      username: 'dev_admin',
      nickname: '开发管理员',
      avatar: null,
      phone: '13800000000',
      role: 'admin' as const,
      status: 'normal' as const,
      last_login_at: null,
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-01T00:00:00Z',
    }
    mockAuth = { ...mockAuth, status: 'authenticated', user: { ...baseUser, role: 'user' } }
    await testUtils.mount(ProductListPage)
    expect(testUtils.queries.querySelector('.product-page__account')?.textContent).not.toContain('管理订单')
    expect(testUtils.queries.querySelector('.product-page__account')?.textContent).not.toContain('管理用户')
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    mockAuth = { ...mockAuth, user: baseUser }
    await testUtils.mount(ProductListPage)
    const buttons = Array.from(testUtils.queries.querySelectorAll('.product-page__account-action'))
    expect(testUtils.queries.querySelector('.product-page__account-user')?.textContent)
      .toContain('你好，开发管理员')
    expect(testUtils.queries.querySelector('.product-page__account-actions')).not.toBeNull()
    expect(buttons).toHaveLength(6)
    const inventoryButton = buttons.find((button) => button.textContent.includes('库存流水'))
    const adminButton = buttons.find((button) => button.textContent.includes('管理订单'))
    const productButton = buttons.find((button) => button.textContent.includes('管理商品'))
    const userButton = buttons.find((button) => button.textContent.includes('管理用户'))
    expect(adminButton).toBeDefined()
    expect(productButton).toBeDefined()
    expect(userButton).toBeDefined()
    expect(inventoryButton).toBeDefined()
    testUtils.fireEvent.click(inventoryButton!)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/admin/pages/inventory-transactions/index' })
    testUtils.fireEvent.click(productButton!)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/admin/pages/products/index' })
    testUtils.fireEvent.click(adminButton!)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/admin/pages/orders/index' })
    testUtils.fireEvent.click(userButton!)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/admin/pages/users/index' })
  })
})
