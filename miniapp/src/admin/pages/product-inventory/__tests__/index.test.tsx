import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'

import ProductInventoryPage, { AuthenticatedProductInventory } from '../index'

let mockAuth: AuthContextValue
const mockUseAdminProductDetail = jest.fn()
const mockUseInventoryAdjustment = jest.fn()
const mockUseInventoryTransactionList = jest.fn()
const mockApplyFilters = jest.fn()

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { navigateTo: jest.fn(), redirectTo: jest.fn() },
  useRouter: () => ({ params: { id: '7' } }),
}))

jest.mock('@/auth', () => ({
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fproducts%2Findex',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/product', () => ({
  ADMIN_PRODUCT_LIST_PATH: '/admin/pages/products/index',
  buildAdminProductDetailUrl: (id: number) => `/admin/pages/product-detail/index?id=${id}&type=kit`,
  useAdminProductDetail: (...args: unknown[]) => mockUseAdminProductDetail(...args),
}))

jest.mock('@/features/inventory', () => ({
  EMPTY_INVENTORY_INPUT_SNAPSHOT: { sourceId: '', productId: '', createdFrom: '', createdTo: '' },
  EMPTY_INVENTORY_FILTER_DRAFT: {
    transactionType: 'all', sourceType: 'all', sourceId: '', productId: '', createdFrom: '', createdTo: '',
  },
  createInventoryInputSnapshot: (draft: {
    sourceType: string
    sourceId: string
    productId: string
    createdFrom: string
    createdTo: string
  }, options: { allowProductId: boolean }) => ({
    sourceId: draft.sourceType === 'order' ? draft.sourceId.trim() : '',
    productId: options.allowProductId ? draft.productId.trim() : '',
    createdFrom: draft.createdFrom.trim(),
    createdTo: draft.createdTo.trim(),
  }),
  inventoryInputSnapshotsEqual: (left: Record<string, string>, right: Record<string, string>) => (
    left.sourceId === right.sourceId && left.productId === right.productId &&
    left.createdFrom === right.createdFrom && left.createdTo === right.createdTo
  ),
  parseInventoryFilters: () => ({ filters: { transactionType: 'all', sourceType: 'all' } }),
  parseKitInventoryRoute: () => ({ productId: 7 }),
  replaceInventorySourceType: (filters: Record<string, unknown>, sourceType: string) => {
    const next: Record<string, unknown> = { ...filters, sourceType }
    if (sourceType !== 'order') delete next.sourceId
    return next
  },
  useInventoryAdjustment: () => mockUseInventoryAdjustment(),
  useInventoryTransactionList: (...args: unknown[]) => mockUseInventoryTransactionList(...args),
}))

describe('ProductInventoryPage', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = authenticated('admin')
    mockUseAdminProductDetail.mockReturnValue({
      retry: jest.fn(),
      state: { status: 'content', product: kitProduct(false) },
    })
    mockUseInventoryAdjustment.mockReturnValue({
      state: { status: 'idle' }, adjustStock: jest.fn(), retrySameIntent: jest.fn(), reset: jest.fn(),
    })
    mockUseInventoryTransactionList.mockReturnValue({
      filters: { transactionType: 'all', sourceType: 'all' },
      state: { status: 'empty', items: [], total: 0, page: 1, pages: 0, loadingMore: false },
      applyFilters: mockApplyFilters, retry: jest.fn(), loadNextPage: jest.fn(),
    })
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('普通用户不挂载商品或 Inventory Hook', async () => {
    mockAuth = authenticated('user')
    await testUtils.mount(ProductInventoryPage)
    expect(testUtils.queries.querySelector('.inventory-state')?.textContent).toContain('无管理权限')
    expect(mockUseAdminProductDetail).not.toHaveBeenCalled()
    expect(mockUseInventoryAdjustment).not.toHaveBeenCalled()
  })

  it('Guest 返回管理商品固定路径登录，不把动态地址加入 redirect 白名单', async () => {
    mockAuth = { ...authenticated('admin'), status: 'guest', user: undefined }
    await testUtils.mount(ProductInventoryPage)
    testUtils.fireEvent.click(requireElement(testUtils, '.inventory-state__action'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fproducts%2Findex',
    })
    expect(mockUseAdminProductDetail).not.toHaveBeenCalled()
  })

  it('已删除 Kit 在读取详情后阻止挂载 Inventory Hook', async () => {
    mockUseAdminProductDetail.mockReturnValue({
      retry: jest.fn(), state: { status: 'content', product: kitProduct(true) },
    })
    await testUtils.mount(AuthenticatedProductInventory, { props: { productId: 7 } })
    expect(testUtils.queries.querySelector('.inventory-state')?.textContent).toContain('已逻辑删除')
    expect(mockUseInventoryAdjustment).not.toHaveBeenCalled()
    expect(mockUseInventoryTransactionList).not.toHaveBeenCalled()
  })

  it('Online Kit 仍可进入库存调整并挂载指定商品流水', async () => {
    await testUtils.mount(AuthenticatedProductInventory, { props: { productId: 7 } })
    expect(testUtils.queries.querySelector('.product-inventory-page')?.textContent).toContain('已上架')
    expect(testUtils.queries.querySelector('.product-inventory-page__stock-label')?.textContent).toBe('当前权威库存')
    expect(testUtils.queries.querySelector('.product-inventory-page__stock-value')?.textContent).toBe('10')
    expect(mockUseInventoryAdjustment).toHaveBeenCalledTimes(1)
    expect(mockUseInventoryTransactionList).toHaveBeenCalledWith({ kind: 'product', productId: 7 })
    expect(testUtils.queries.querySelectorAll('.masked-date-input')).toHaveLength(2)
  })

  it('指定 Kit 流水按钮切换后立即查询', async () => {
    mockUseInventoryTransactionList.mockReturnValue({
      filters: { transactionType: 'admin_adjustment', sourceType: 'admin' },
      state: { status: 'empty', items: [], total: 0, page: 1, pages: 0, loadingMore: false },
      applyFilters: mockApplyFilters, retry: jest.fn(), loadNextPage: jest.fn(),
    })
    await testUtils.mount(AuthenticatedProductInventory, { props: { productId: 7 } })
    testUtils.fireEvent.click(findButton(testUtils, '取消恢复'))
    expect(mockApplyFilters).toHaveBeenCalledWith({
      transactionType: 'order_cancellation_restore', sourceType: 'admin',
    })
  })
})

function authenticated(role: 'user' | 'admin'): AuthContextValue {
  return {
    status: 'authenticated',
    user: {
      id: 2, username: 'admin', nickname: '管理员', avatar: null, phone: '13800000000',
      role, status: 'normal', last_login_at: null,
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    },
    register: jest.fn(), login: jest.fn(), loginWithWechat: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
  }
}

function kitProduct(isDeleted: boolean) {
  return {
    id: 7,
    name: '在线套装',
    description: null,
    product_type: { value: 'kit' as const, label: '拼豆套装' },
    status: { value: 'online' as const, label: '已上架' },
    images: [],
    price: '99.00',
    stock: 10,
    created_at: '2026-08-25T07:00:00Z',
    updated_at: '2026-08-25T08:00:00Z',
    is_deleted: isDeleted,
  }
}

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

function findButton(testUtils: ReactTestUtil, label: string): Element {
  const button = Array.from(testUtils.queries.querySelectorAll('.inventory-filters__choice'))
    .find((candidate) => candidate.textContent === label)
  if (!button) throw new Error(`button ${label} not found`)
  return button
}
