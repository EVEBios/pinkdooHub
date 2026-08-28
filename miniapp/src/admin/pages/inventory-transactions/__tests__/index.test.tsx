import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'

import InventoryTransactionsPage, { AuthenticatedInventoryTransactions } from '../index'

let mockAuth: AuthContextValue
const mockUseInventoryTransactionList = jest.fn()
const mockApplyFilters = jest.fn()

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
  EMPTY_INVENTORY_FILTER_DRAFT: {
    transactionType: 'all', sourceType: 'all', sourceId: '', productId: '', createdFrom: '', createdTo: '',
  },
  parseInventoryFilters: () => ({ filters: { transactionType: 'all', sourceType: 'all' } }),
  useInventoryTransactionList: (...args: unknown[]) => mockUseInventoryTransactionList(...args),
}))

describe('InventoryTransactionsPage', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = authenticated('admin')
    mockUseInventoryTransactionList.mockReturnValue({
      filters: { transactionType: 'all', sourceType: 'all' },
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
    testUtils.fireEvent.click(requireElement(testUtils, '.inventory-filters__reset'))
    expect(mockApplyFilters).toHaveBeenCalledWith({ transactionType: 'all', sourceType: 'all' })
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
    register: jest.fn(), login: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
  }
}

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
