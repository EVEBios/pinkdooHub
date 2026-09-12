import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type { CartContextValue } from '@/features/order'

import CartPage from '../index'

const mockRetryInitialization = jest.fn()
const mockUpdateQuantity = jest.fn(async () => undefined)
const mockRemoveItem = jest.fn(async () => undefined)
let mockCart: CartContextValue
let mockAuth: AuthContextValue
const mockUseCart = jest.fn()

jest.mock('@/auth', () => ({
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/order', () => ({
  cartItemKey: (item: { productId: number; experienceOptionId: number | null; kitColorId: number | null }) => (
    `${item.productId}:${item.experienceOptionId ?? item.kitColorId ?? 'fixed'}`
  ),
  useCart: () => {
    mockUseCart()
    return mockCart
  },
}))

jest.mock('@/utils/asset_url', () => ({
  resolveAssetUrl: (assetUrl: string) => `https://api.example.com${assetUrl}`,
}))

describe('CartPage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = authenticatedUser()
    mockCart = {
      status: 'ready',
      items: [],
      addItem: jest.fn(async () => undefined),
      addItems: jest.fn(async () => undefined),
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

  it.each(['admin', 'super_admin'] as const)('%s 深链不挂载购物车，并自动进入工作台', async (role) => {
    mockAuth = {
      ...mockAuth,
      user: { ...mockAuth.user!, role },
    }
    await testUtils.mount(CartPage)

    expect(requireElement(testUtils, '.admin-workbench-redirect').textContent).toContain('正在进入店铺工作台')
    expect(mockUseCart).not.toHaveBeenCalled()
    await flush(testUtils)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
  })

  it('未知角色保持 fail closed，不挂载购物车', async () => {
    mockAuth = {
      ...mockAuth,
      user: { ...mockAuth.user!, role: 'operator' as never },
    }
    await testUtils.mount(CartPage)

    expect(requireElement(testUtils, '.cart-state__title').textContent).toContain('账户角色暂不支持')
    expect(mockUseCart).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
  })

  it('空购物车返回商城时切换到根 Tab', async () => {
    await testUtils.mount(CartPage)

    testUtils.fireEvent.click(requireElement(testUtils, '.cart-state__action'))
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/index/index' })
    expect(Taro.navigateTo).not.toHaveBeenCalledWith({ url: '/pages/index/index' })
  })

  it('展示 Experience/Kit 本地预览，并把数量操作交给 Cart Store', async () => {
    mockCart = {
      ...mockCart,
      items: [
        {
          productId: 1,
          experienceOptionId: 11,
          kitColorId: null,
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
          kitColorId: null,
          productType: 'kit',
          kitKind: 'fixed',
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
    expect(mockUpdateQuantity).toHaveBeenCalledWith(mockCart.items[0], 3)

    const checkout = testUtils.queries.querySelector('.cart-page__checkout')
    if (!checkout) {
      throw new Error('没有渲染订单确认入口')
    }
    testUtils.fireEvent.click(checkout)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/order-confirm/index' })
  })

  it('把同一自选商品合成一个区块，优先直绘 HEX 并保留图片回退', async () => {
    const firstColor = {
      productId: 3,
      experienceOptionId: null,
      kitColorId: 31,
      productType: 'kit' as const,
      kitKind: 'color_selectable' as const,
      productName: '221自选颜色',
      configurationLabel: 'A1',
      saleUnitGrams: 10 as const,
      swatchHex: '#E60012',
      unitPrice: '3.00',
      imageUrl: '/uploads/bead-colors/a1.png',
      quantity: 2,
    }
    const secondColor = {
      ...firstColor,
      kitColorId: 32,
      configurationLabel: 'A2',
      swatchHex: null,
      imageUrl: '/uploads/bead-colors/a2.png',
      quantity: 1,
    }
    mockCart = { ...mockCart, items: [firstColor, secondColor] }
    await testUtils.mount(CartPage)

    expect(testUtils.queries.querySelectorAll('.cart-item')).toHaveLength(1)
    const group = testUtils.queries.querySelector('.cart-color-group')
    expect(group?.textContent).toContain('221自选颜色')
    expect(group?.textContent).toContain('2 种颜色 · 共 30g')
    expect(group?.textContent.match(/预览单价/g)).toHaveLength(1)

    const colorRows = testUtils.queries.querySelectorAll('.cart-color-row')
    expect(colorRows).toHaveLength(2)
    expect(colorRows[0].textContent).toContain('A1')
    expect(colorRows[0].textContent).toContain('20g')
    expect((colorRows[0].querySelector('.bead-color-swatch--hex') as HTMLElement).style.backgroundColor)
      .toBe('rgb(230, 0, 18)')
    expect(colorRows[0].querySelector('.bead-color-swatch--image')).toBeNull()
    expect(colorRows[1].querySelector('.bead-color-swatch--image')?.getAttribute('src'))
      .toBe('https://api.example.com/uploads/bead-colors/a2.png')

    const secondColorSteps = colorRows[1].querySelectorAll('.cart-color-row__step')
    testUtils.fireEvent.click(secondColorSteps[1])
    expect(mockUpdateQuantity).toHaveBeenCalledWith(secondColor, 2)
  })

  it('允许从合并区块中单独移除一种颜色', async () => {
    const color = {
      productId: 3,
      experienceOptionId: null,
      kitColorId: 31,
      productType: 'kit' as const,
      kitKind: 'color_selectable' as const,
      productName: '221自选颜色',
      configurationLabel: 'A1',
      saleUnitGrams: 10 as const,
      swatchHex: null,
      unitPrice: '3.00',
      imageUrl: null,
      quantity: 1,
    }
    mockCart = { ...mockCart, items: [color] }
    await testUtils.mount(CartPage)

    const remove = testUtils.queries.querySelector('.cart-color-row__remove')
    if (!remove) {
      throw new Error('没有渲染单色移除按钮')
    }
    testUtils.fireEvent.click(remove)

    expect(mockRemoveItem).toHaveBeenCalledWith(color)
  })

  it('不同自选商品仍各自占一个区块', async () => {
    const baseColor = {
      productId: 3,
      experienceOptionId: null,
      kitColorId: 31,
      productType: 'kit' as const,
      kitKind: 'color_selectable' as const,
      productName: '第一套自选颜色',
      configurationLabel: 'A1',
      saleUnitGrams: 10 as const,
      swatchHex: null,
      unitPrice: '3.00',
      imageUrl: null,
      quantity: 1,
    }
    mockCart = {
      ...mockCart,
      items: [baseColor, {
        ...baseColor,
        productId: 4,
        kitColorId: 41,
        productName: '第二套自选颜色',
      }],
    }
    await testUtils.mount(CartPage)

    expect(testUtils.queries.querySelectorAll('.cart-color-group')).toHaveLength(2)
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

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

function authenticatedUser(): AuthContextValue {
  return {
    status: 'authenticated',
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
    register: jest.fn(),
    updateProfile: jest.fn(),
    login: jest.fn(),
    loginWithWechat: jest.fn(),
    logout: jest.fn(),
    retryInitialization: jest.fn(),
  }
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}
