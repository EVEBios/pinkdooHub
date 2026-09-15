import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import { AdminWorkbenchRedirect } from '../admin_workbench_redirect'

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { reLaunch: jest.fn(() => Promise.resolve()) },
}))

jest.mock('@/auth', () => ({
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
}))

describe('管理员根页重定向', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('只用 reLaunch 清理顾客页面栈并进入工作台', async () => {
    await testUtils.mount(AdminWorkbenchRedirect)
    await flush(testUtils)

    expect(Taro.reLaunch).toHaveBeenCalledTimes(1)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
  })

  it('导航失败时展示恢复动作', async () => {
    ;(Taro.reLaunch as jest.Mock)
      .mockRejectedValueOnce(new Error('navigation failed'))
      .mockResolvedValueOnce(undefined)
    await testUtils.mount(AdminWorkbenchRedirect)
    await flush(testUtils)

    expect(required(testUtils, '.admin-workbench-redirect__error').textContent)
      .toContain('店铺工作台暂时无法打开')
    expect(required(testUtils, '.admin-workbench-redirect__error').getAttribute('aria-role'))
      .toBe('alert')
    testUtils.fireEvent.click(required(testUtils, '.admin-workbench-redirect__action'))
    await flush(testUtils)
    expect(Taro.reLaunch).toHaveBeenCalledTimes(2)
  })
})

function required(testUtils: ReactTestUtil, selector: string): Element {
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
