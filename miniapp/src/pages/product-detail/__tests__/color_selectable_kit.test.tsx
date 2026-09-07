import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { KitProductDetail } from '@/api/endpoints/products'
import type { CartContextValue } from '@/features/order'

import { ColorSelectableKitDetail } from '../index'

const mockAddItems = jest.fn()
let mockCart: CartContextValue

jest.mock('@/auth', () => ({
  buildLoginUrl: (path: string) => path,
  useAuth: jest.fn(),
}))

jest.mock('@/features/order', () => {
  const actual = jest.requireActual('@/features/order')
  return { ...actual, useCart: () => mockCart }
})

jest.mock('@/features/reservation', () => ({
  buildReservationCreateUrl: jest.fn(),
}))

describe('自选颜色 Kit 商品详情', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAddItems.mockResolvedValue(undefined)
    mockCart = {
      status: 'ready',
      items: [],
      addItem: jest.fn(),
      addItems: mockAddItems,
      updateQuantity: jest.fn(),
      removeItem: jest.fn(),
      clear: jest.fn(),
      reconcileSubmittedItems: jest.fn(),
      retryInitialization: jest.fn(),
    }
    jest.spyOn(Taro, 'showToast').mockResolvedValue({ errMsg: 'showToast:ok' })
  })

  afterEach(() => {
    testUtils.unmout()
    jest.restoreAllMocks()
    jest.clearAllMocks()
  })

  it('按颜色选择 10g 份数，并一次性原子加入购物车', async () => {
    await testUtils.mount(ColorSelectableKitDetail, { props: { detail: colorKit(2) } })

    testUtils.fireEvent.click(testUtils.queries.querySelectorAll('.color-card')[0])
    await flush(testUtils)
    const firstColorSteps = testUtils.queries.querySelectorAll('.selected-color__step')
    expect(firstColorSteps).toHaveLength(2)
    testUtils.fireEvent.click(firstColorSteps[1])
    testUtils.fireEvent.click(testUtils.queries.querySelectorAll('.color-card')[1])
    await flush(testUtils)
    expect(required(testUtils, '.selected-colors').textContent).toContain('共 30g')

    testUtils.fireEvent.click(required(testUtils, '.product-detail__add-cart'))
    await flush(testUtils)

    expect(mockAddItems).toHaveBeenCalledWith([
      expect.objectContaining({ kitColorId: 101, quantity: 2, saleUnitGrams: 10 }),
      expect.objectContaining({ kitColorId: 102, quantity: 1, saleUnitGrams: 10 }),
    ])
    expect(Taro.showToast).toHaveBeenCalledWith({ title: '已加入 2 种颜色', icon: 'success' })
  })

  it('在第 21 种颜色处阻止继续选择', async () => {
    await testUtils.mount(ColorSelectableKitDetail, { props: { detail: colorKit(21) } })
    for (let index = 0; index < 20; index += 1) {
      testUtils.fireEvent.click(testUtils.queries.querySelectorAll('.color-card')[index])
      await flush(testUtils)
    }
    testUtils.fireEvent.click(testUtils.queries.querySelectorAll('.color-card')[20])
    await flush(testUtils)

    expect(required(testUtils, '.color-picker__count').textContent).toBe('20/20')
    expect(Taro.showToast).toHaveBeenCalledWith({
      title: '每单最多选择 20 种颜色',
      icon: 'none',
    })
  })

  it('色号与名称相同时只展示一个标签', async () => {
    const original = colorKit(1)
    const detail = {
      ...original,
      colors: [{ ...original.colors[0], color_code: 'A1', name: 'A1' }],
    }
    await testUtils.mount(ColorSelectableKitDetail, { props: { detail } })

    expect(required(testUtils, '.color-card__copy').textContent).toBe('A1')
    testUtils.fireEvent.click(required(testUtils, '.color-card'))
    await flush(testUtils)
    expect(required(testUtils, '.selected-color__code').textContent).toBe('A1')
  })

  it('只为已选色块展示醒目标记，并在取消选择后移除', async () => {
    await testUtils.mount(ColorSelectableKitDetail, { props: { detail: colorKit(2) } })

    expect(testUtils.queries.querySelector('.color-card__selected-label')).toBeNull()
    const firstColor = testUtils.queries.querySelectorAll('.color-card')[0]
    testUtils.fireEvent.click(firstColor)
    await flush(testUtils)

    expect(required(testUtils, '.color-card__selected-label').textContent).toBe('已选')
    testUtils.fireEvent.click(testUtils.queries.querySelectorAll('.color-card')[0])
    await flush(testUtils)
    expect(testUtils.queries.querySelector('.color-card__selected-label')).toBeNull()
  })
})

function colorKit(colorCount: number): KitProductDetail {
  return {
    id: 8,
    name: '221 色自选拼豆',
    description: '按 10g 选择颜色',
    product_type: { value: 'kit', label: '拼豆套装' },
    images: [],
    kit_kind: { value: 'color_selectable', label: '自选颜色' },
    sale_unit_grams: 10,
    price: '2.50',
    stock: null,
    available: true,
    colors: Array.from({ length: colorCount }, (_, index) => ({
      id: 101 + index,
      bead_color_id: 201 + index,
      slot_no: index + 1,
      color_code: `C${String(index + 1).padStart(3, '0')}`,
      name: `颜色 ${index + 1}`,
      swatch_image_url: null,
      available: true,
    })),
  }
}

function required(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}
