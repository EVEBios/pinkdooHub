import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'

import InventoryTransactionsPage, { AuthenticatedInventoryTransactions } from '../index'

let mockAuth: AuthContextValue
const mockUseInventoryTransactionList = jest.fn()
const mockApplyFilters = jest.fn()
let mockFilters: {
  transactionType: string
  sourceType: string
  productId?: number
  sourceId?: number
}

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { navigateTo: jest.fn() },
}))

jest.mock('@/auth', () => ({
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fadmin%2Fpages%2Finventory-transactions%2Findex',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/inventory', () => ({
  ADMIN_INVENTORY_LIST_PATH: '/admin/pages/inventory-transactions/index',
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
  replaceInventorySourceType: (filters: Record<string, unknown>, sourceType: string) => {
    const next: Record<string, unknown> = { ...filters, sourceType }
    if (sourceType !== 'order') delete next.sourceId
    return next
  },
  useInventoryTransactionList: (...args: unknown[]) => mockUseInventoryTransactionList(...args),
}))

describe('InventoryTransactionsPage', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = authenticated('admin')
    mockFilters = { transactionType: 'all', sourceType: 'all' }
    mockUseInventoryTransactionList.mockReturnValue({
      filters: mockFilters,
      state: { status: 'empty', items: [], total: 0, page: 1, pages: 0, loadingMore: false },
      applyFilters: mockApplyFilters,
      retry: jest.fn(),
      loadNextPage: jest.fn(),
    })
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('普通用户不挂载 Inventory Hook', async () => {
    mockAuth = authenticated('user')
    await testUtils.mount(InventoryTransactionsPage)
    expect(testUtils.queries.querySelector('.inventory-state')?.textContent).toContain('无管理权限')
    expect(mockUseInventoryTransactionList).not.toHaveBeenCalled()
  })

  it('Guest 通过固定白名单路径进入登录且不挂载 API', async () => {
    mockAuth = { ...authenticated('admin'), status: 'guest', user: undefined }
    await testUtils.mount(InventoryTransactionsPage)
    testUtils.fireEvent.click(requireElement(testUtils, '.inventory-state__action'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fadmin%2Fpages%2Finventory-transactions%2Findex',
    })
    expect(mockUseInventoryTransactionList).not.toHaveBeenCalled()
  })

  it('ADMIN 使用全局作用域并可清空筛选', async () => {
    await testUtils.mount(AuthenticatedInventoryTransactions)
    expect(mockUseInventoryTransactionList).toHaveBeenCalledWith({ kind: 'global' })
    expect(testUtils.queries.querySelectorAll('.masked-date-input')).toHaveLength(2)
    testUtils.fireEvent.click(requireElement(testUtils, '.inventory-filters__reset'))
    expect(mockApplyFilters).toHaveBeenCalledWith({ transactionType: 'all', sourceType: 'all' })
  })

  it('按钮立即使用已提交文字筛选，不使用尚未查询的输入值', async () => {
    mockFilters = {
      transactionType: 'all', sourceType: 'order', productId: 12, sourceId: 7,
    }
    mockUseInventoryTransactionList.mockReturnValue({
      filters: mockFilters,
      state: { status: 'empty', items: [], total: 0, page: 1, pages: 0, loadingMore: false },
      applyFilters: mockApplyFilters,
      retry: jest.fn(),
      loadNextPage: jest.fn(),
    })
    await testUtils.mount(AuthenticatedInventoryTransactions)
    input(testUtils, findInput(testUtils, 'Product ID（可选）'), '99')
    expect(mockApplyFilters).not.toHaveBeenCalled()

    testUtils.fireEvent.click(findButton(testUtils, '订单扣减'))
    expect(requireElement(testUtils, '.inventory-filters__pending').textContent).toContain('尚未应用')
    expect(mockApplyFilters).toHaveBeenLastCalledWith({
      transactionType: 'order_deduction', sourceType: 'order', productId: 12, sourceId: 7,
    })

    testUtils.fireEvent.click(findButton(testUtils, '管理员'))
    expect(mockApplyFilters).toHaveBeenLastCalledWith({
      transactionType: 'all', sourceType: 'admin', productId: 12,
    })
  })

  it('来源切离订单时同步清除已应用的 source ID，不留下未应用提示', async () => {
    await testUtils.mount(AuthenticatedInventoryTransactions)
    testUtils.fireEvent.click(findButton(testUtils, '订单'))
    input(testUtils, findInput(testUtils, 'Order source ID（可选）'), '7')
    const filterCard = requireElement(testUtils, '.inventory-filters')
    testUtils.fireEvent.submit(filterCard.firstElementChild!)
    expect(testUtils.queries.querySelector('.inventory-filters__pending')).toBeNull()

    testUtils.fireEvent.click(findButton(testUtils, '管理员'))
    expect(testUtils.queries.querySelector('.inventory-filters__pending')).toBeNull()
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

function findInput(testUtils: ReactTestUtil, placeholder: string): Element {
  const element = Array.from(testUtils.queries.querySelectorAll('.inventory-filters__input'))
    .find((candidate) => candidate.getAttribute('placeholder') === placeholder)
  if (!element) throw new Error(`input ${placeholder} not found`)
  return element
}

function input(testUtils: ReactTestUtil, element: Element, value: string): void {
  const fireCustomEvent = testUtils.fireEvent as unknown as (target: Element, event: Event) => void
  fireCustomEvent(element, new CustomEvent('input', { bubbles: true, detail: { value } }))
}
