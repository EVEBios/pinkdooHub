import ReactTestUtil from '@tarojs/test-utils-react'

import Index from '../index'

jest.mock('@/auth', () => ({
  useAuth: () => ({
    status: 'authenticated',
    user: {
      id: 7,
      username: 'alice',
      nickname: 'Alice',
      phone: '13800138000',
      avatar: null,
      role: 'user',
      status: 'normal',
      last_login_at: null,
      created_at: '2026-08-01T08:00:00Z',
      updated_at: '2026-08-20T08:00:00Z'
    },
    logout: jest.fn(),
    retryInitialization: jest.fn()
  })
}))

// Taro 4.2.1 的 @tarojs/router 与 @tarojs/components（Stencil bundle）在 Jest 中
// 经 taro-h5 runtime 形成循环依赖；mount() 不依赖 router，工厂 mock 以打破循环
// （Spike 结论）。
jest.mock('@tarojs/router', () => ({
  history: {},
  getCurrentPages: jest.fn(() => []),
  navigateBack: jest.fn(),
  navigateTo: jest.fn(),
  reLaunch: jest.fn(),
  redirectTo: jest.fn(),
  switchTab: jest.fn(),
  createMpaHistory: jest.fn(),
  prependBasename: jest.fn((url: string) => url),
  setHistory: jest.fn(),
  setHistoryMode: jest.fn(),
  createMultiRouter: jest.fn(),
  createRouter: jest.fn(),
  routesAlias: {},
  createBrowserHistory: jest.fn(),
  createHashHistory: jest.fn(),
  isDingTalk: jest.fn(() => false),
  isWeixin: jest.fn(() => false),
  setMpaTitle: jest.fn(),
  setNavigationBarLoading: jest.fn(),
  setNavigationBarStyle: jest.fn(),
  setTitle: jest.fn(),
  handleAppMount: jest.fn(),
  handleAppMountWithTabbar: jest.fn()
}))

describe('Index', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
  })

  afterEach(() => {
    testUtils.unmout()
  })

  it('渲染首页容器', async () => {
    await testUtils.mount(Index)

    expect(testUtils.queries.querySelector('.index')).not.toBeNull()
    expect(testUtils.queries.querySelector('.index__subtitle')?.textContent)
      .toContain('Alice')
  })
})
