class IntersectionObserverMock {
  observe() {}

  unobserve() {}

  disconnect() {}
}

global.IntersectionObserver = IntersectionObserverMock

// Taro H5 的测试运行时不实现微信专有的自定义 TabBar 取值接口。
const taro = require('@tarojs/taro').default
taro.getTabBar = jest.fn()

jest.mock('@tarojs/router', () => ({
  history: {},
  getCurrentPages: jest.fn(() => []),
  navigateBack: jest.fn(),
  navigateTo: jest.fn(),
  reLaunch: jest.fn(),
  redirectTo: jest.fn(),
  switchTab: jest.fn(),
  createMpaHistory: jest.fn(),
  prependBasename: jest.fn((url) => url),
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
  handleAppMountWithTabbar: jest.fn(),
}))
