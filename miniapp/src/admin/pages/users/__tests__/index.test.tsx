import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'

import AdminUsersPage, { AuthenticatedAdminUsers } from '../index'

let mockAuth: AuthContextValue
const mockUseAdminUserList = jest.fn()
const mockUseAdminUserDisable = jest.fn()
const mockDisableUser = jest.fn()
const mockRetry = jest.fn()
const mockReset = jest.fn()

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { navigateTo: jest.fn(), showModal: jest.fn() },
}))

jest.mock('@/auth', () => ({
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fusers%2Findex',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/admin_user', () => ({
  ADMIN_USER_LIST_PATH: '/admin/pages/users/index',
  useAdminUserList: () => mockUseAdminUserList(),
  useAdminUserDisable: () => mockUseAdminUserDisable(),
}))

describe('AdminUsersPage', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'authenticated',
      user: {
        id: 2, username: 'admin', nickname: '管理员', avatar: null, phone: '13800000000',
        role: 'admin', status: 'normal', last_login_at: null,
        created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
      },
      register: jest.fn(), login: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
    }
    mockUseAdminUserList.mockReturnValue({
      filters: { status: 'all', role: 'all' },
      state: { status: 'loading', items: [], total: 0, page: 1, pages: 0, loadingMore: false },
      applyFilters: jest.fn(), retry: mockRetry, loadNextPage: jest.fn(),
    })
    mockUseAdminUserDisable.mockReturnValue({
      state: { status: 'idle' }, disableUser: mockDisableUser, reset: mockReset,
    })
    mockDisableUser.mockResolvedValue(true)
    ;(Taro.showModal as jest.Mock).mockResolvedValue({ confirm: true, cancel: false })
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('普通用户不挂载任何管理用户 Hook', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminUsersPage)
    expect(testUtils.queries.querySelector('.admin-users-state')?.textContent).toContain('无管理权限')
    expect(mockUseAdminUserList).not.toHaveBeenCalled()
    expect(mockUseAdminUserDisable).not.toHaveBeenCalled()
  })

  it('Guest 使用固定白名单 redirect 且不挂载 API', async () => {
    mockAuth = { ...mockAuth, status: 'guest', user: undefined }
    await testUtils.mount(AdminUsersPage)
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-users-state__action'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fusers%2Findex',
    })
    expect(mockUseAdminUserList).not.toHaveBeenCalled()
  })

  it('展示安全摘要并确认后禁用普通用户', async () => {
    mockUseAdminUserList.mockReturnValue({
      filters: { status: 'all', role: 'all' },
      state: {
        status: 'content',
        items: [{
          id: 5, username: 'normal_user', nickname: '普通用户', role: 'user', status: 'normal',
          last_login_at: null, created_at: '2026-08-28T08:00:00Z',
        }],
        total: 1, page: 1, pages: 1, loadingMore: false,
      },
      applyFilters: jest.fn(), retry: mockRetry, loadNextPage: jest.fn(),
    })
    await testUtils.mount(AuthenticatedAdminUsers, { props: { currentUserId: 2, currentRole: 'admin' } })
    const card = requireElement(testUtils, '.admin-user-card')
    expect(card.textContent).toContain('@normal_user · ID 5')
    expect(card.textContent).not.toContain('13800000000')
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-user-card__disable'))
    await flush(testUtils)
    expect(mockDisableUser).toHaveBeenCalledWith(5)
    expect(mockRetry).toHaveBeenCalled()
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
    await Promise.resolve()
  })
}
