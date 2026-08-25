import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { OrderDetail } from '@/api/endpoints/orders'
import type { OrderCancellationState, OrderDetailState } from '@/features/order'

import { AuthenticatedOrderDetail } from '../index'

let mockDetail: OrderDetailState
let mockCancellation: OrderCancellationState
const mockCancel = jest.fn(async () => undefined)
const mockRetry = jest.fn()
const showModalSpy = jest.spyOn(Taro, 'showModal')

jest.mock('@/auth', () => ({
  ORDER_LIST_PATH: '/pages/orders/index',
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fpages%2Forders%2Findex',
  useAuth: jest.fn(),
}))

jest.mock('@/features/order', () => ({
  parseOrderDetailRoute: jest.fn(),
  useOrderDetail: () => ({
    detail: mockDetail,
    cancellation: mockCancellation,
    cancel: mockCancel,
    retry: mockRetry,
  }),
}))

jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

const pendingOrder: OrderDetail = {
  id: 101,
  order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
  total_amount: '298.00',
  status: { value: 'pending', label: '待支付' },
  remark: '服务端备注',
  items: [
    {
      id: 1,
      product_id: 1,
      experience_option_id: 11,
      product_name: '体验快照',
      option_duration_minutes: 60,
      option_participants: 1,
      option_day_type: { value: 'weekday', label: '工作日' },
      product_price: '99.00',
      quantity: 1,
      subtotal: '99.00',
    },
    {
      id: 2,
      product_id: 2,
      experience_option_id: null,
      product_name: '套装快照',
      option_duration_minutes: null,
      option_participants: null,
      option_day_type: null,
      product_price: '199.00',
      quantity: 1,
      subtotal: '199.00',
    },
  ],
  created_at: '2026-08-24T08:00:00Z',
  updated_at: '2026-08-24T08:00:00Z',
}

describe('AuthenticatedOrderDetail', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockDetail = { status: 'content', order: pendingOrder }
    mockCancellation = { status: 'idle' }
    showModalSpy.mockResolvedValue({
      confirm: true,
      cancel: false,
      errMsg: 'showModal:ok',
    })
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('只显示服务端详情快照，Pending 经确认后取消', async () => {
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    const page = requireElement(testUtils, '.order-detail-page')
    expect(page.textContent).toContain('体验快照')
    expect(page.textContent).toContain('60 分钟 · 1 人 · 工作日')
    expect(page.textContent).toContain('套装快照')
    expect(page.textContent).toContain('¥298.00')
    testUtils.fireEvent.click(requireElement(testUtils, '.order-detail-page__cancel'))
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalled()
    expect(mockCancel).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['paid', '已支付'],
    ['cancelled', '已取消'],
    ['completed', '已完成'],
  ] as const)('%s 状态不显示取消入口', async (value, label) => {
    mockDetail = { status: 'content', order: { ...pendingOrder, status: { value, label } } }
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    expect(testUtils.queries.querySelector('.order-detail-page__cancel')).toBeNull()
  })

  it('unknown 不提供重复取消入口，并引导回我的订单核对', async () => {
    mockCancellation = { status: 'unknown', errorMessage: '取消结果可能未知，请从我的订单重新核对' }
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    expect(testUtils.queries.querySelector('.order-cancel-feedback')?.textContent).toContain('结果可能未知')
    expect(testUtils.queries.querySelector('.order-detail-page__cancel')).toBeNull()
    testUtils.fireEvent.click(requireElement(testUtils, '.order-detail-page__back'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/orders/index' })
  })

  it('取消成功和详情刷新失败同时可见', async () => {
    mockDetail = {
      status: 'content',
      order: { ...pendingOrder, status: { value: 'cancelled', label: '已取消' } },
    }
    mockCancellation = {
      status: 'succeeded',
      result: {
        id: 101,
        order_no: pendingOrder.order_no,
        status: { value: 'cancelled', label: '已取消' },
        updated_at: pendingOrder.updated_at,
      },
      refreshErrorMessage: '订单已取消，但详情刷新失败',
    }
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    expect(testUtils.queries.querySelector('.order-cancel-feedback')?.textContent)
      .toContain('订单已取消，但详情刷新失败')
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
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
