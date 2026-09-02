import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { CartContextValue } from '@/features/order'

import CartPage from '../index'

const mockRetryInitialization = jest.fn()
const mockUpdateQuantity = jest.fn(async () => undefined)
const mockRemoveItem = jest.fn(async () => undefined)
let mockCart: CartContextValue

jest.mock('@/features/order', () => ({
  cartItemKey: (item: { productId: number; experienceOptionId: number | null }) => (
    `${item.productId}:${item.experienceOptionId ?? 'kit'}`
  ),
  useCart: () => mockCart,
}))

describe('CartPage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockCart = {
      status: 'ready',
      items: [],
      addItem: jest.fn(async () => undefined),
      updateQuantity: mockUpdateQuantity,
      removeItem: mockRemoveItem,
      clear: jest.fn(async () => undefined),
      reconcileSubmittedItems: jest.fn(async () => ({
        status: 'completed' as const,
        preservedItemKeys: [],
      })),
      retryInitialization: mockRetryInitialization,
    }
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it.each([
    ['initializing', '正在恢复购物车…'],
    ['error', '购物车恢复失败'],
    ['ready', '购物车还是空的'],
  ] as const)('渲染 %s 状态', async (status, expectedText) => {
    mockCart = {
      ...mockCart,
      status,
      initializationError: status === 'error' ? new Error('storage unavailable') : undefined,
    }
    await testUtils.mount(CartPage)

    expect(testUtils.queries.querySelector('.cart-page')?.textContent).toContain(expectedText)
  })

  it('展示 Experience/Kit 本地预览，并把数量操作交给 Cart Store', async () => {
    mockCart = {
      ...mockCart,
      items: [
        {
          productId: 1,
          experienceOptionId: 11,
          productType: 'experience',
          productName: '周末拼豆体验',
          configurationLabel: '1小时 · 2人 · 工作日',
          unitPrice: '299.00',
          imageUrl: null,
          quantity: 2,
        },
        {
          productId: 2,
          experienceOptionId: null,
          productType: 'kit',
          productName: '基础拼豆套装',
          configurationLabel: null,
          unitPrice: '599.00',
          imageUrl: null,
          quantity: 1,
        },
      ],
    }
    await testUtils.mount(CartPage)

    const rows = testUtils.queries.querySelectorAll('.cart-item')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('1小时 · 2人 · 工作日')
    expect(rows[1].textContent).not.toContain('1小时')
    expect(testUtils.queries.querySelector('.cart-page__notice')?.textContent).toContain('价格仅供预览')

    const firstRowButtons = rows[0].querySelectorAll('.cart-item__quantity-button')
    testUtils.fireEvent.click(firstRowButtons[1])
    expect(mockUpdateQuantity).toHaveBeenCalledWith(1, 11, 3)

    const checkout = testUtils.queries.querySelector('.cart-page__checkout')
    if (!checkout) {
      throw new Error('没有渲染订单确认入口')
    }
    testUtils.fireEvent.click(checkout)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/order-confirm/index' })
  })

  it('恢复失败时允许重试', async () => {
    mockCart = { ...mockCart, status: 'error', initializationError: new Error('failed') }
    await testUtils.mount(CartPage)

    const retryButton = testUtils.queries.querySelector('.cart-state__action')
    if (!retryButton) {
      throw new Error('没有渲染购物车重试按钮')
    }
    testUtils.fireEvent.click(retryButton)

    expect(mockRetryInitialization).toHaveBeenCalledTimes(1)
  })
})
