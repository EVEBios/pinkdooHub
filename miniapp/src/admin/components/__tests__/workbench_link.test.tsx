import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import { ADMIN_WORKBENCH_PATH } from '@/auth'

import { AdminWorkbenchLink } from '../workbench_link'

describe('AdminWorkbenchLink', () => {
  let testUtils: ReactTestUtil

  beforeEach(async () => {
    testUtils = new ReactTestUtil()
    await testUtils.mount(AdminWorkbenchLink)
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('合并重复返回并 reLaunch 到工作台', async () => {
    let resolveNavigation!: () => void
    const navigation = new Promise<void>((resolve) => {
      resolveNavigation = resolve
    }) as unknown as ReturnType<typeof Taro.reLaunch>
    jest.spyOn(Taro, 'reLaunch').mockReturnValue(navigation)

    const link = required(testUtils, '.admin-workbench-link')
    testUtils.fireEvent.click(link)
    testUtils.fireEvent.click(link)

    expect(Taro.reLaunch).toHaveBeenCalledTimes(1)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: ADMIN_WORKBENCH_PATH })
    await testUtils.act(async () => resolveNavigation())
  })

  it('跳转失败时给出反馈并允许再次尝试', async () => {
    jest.spyOn(Taro, 'reLaunch')
      .mockRejectedValueOnce(new Error('busy'))
      .mockResolvedValueOnce(undefined as never)
    const toast = jest.spyOn(Taro, 'showToast').mockResolvedValue(undefined as never)

    await testUtils.act(async () => {
      testUtils.fireEvent.click(required(testUtils, '.admin-workbench-link'))
      await Promise.resolve()
    })
    expect(toast).toHaveBeenCalledWith({ title: '工作台暂时无法打开', icon: 'none' })

    await testUtils.act(async () => {
      testUtils.fireEvent.click(required(testUtils, '.admin-workbench-link'))
      await Promise.resolve()
    })
    expect(Taro.reLaunch).toHaveBeenCalledTimes(2)
  })
})

function required(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
