import ReactTestUtil from '@tarojs/test-utils-react'

import type { ProductListState } from '@/features/product/use_product_list'

import ProductListPage from '../index'

const mockRetry = jest.fn()
const mockLoadNextPage = jest.fn()
const mockSetKeyword = jest.fn()
const mockSetProductType = jest.fn()
let mockProductListState: ProductListState

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
  useAuth: () => ({
    status: 'guest',
    logout: jest.fn(),
  }),
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
})
