import ReactTestUtil from '@tarojs/test-utils-react'

import { useRefreshAfterPageReturn } from '../use_refresh_after_page_return'

let mockDidHide: (() => void) | undefined
let mockDidShow: (() => void) | undefined

jest.mock('@tarojs/taro', () => ({
  useDidHide: (callback: () => void) => { mockDidHide = callback },
  useDidShow: (callback: () => void) => { mockDidShow = callback },
}))

function Harness({ refresh }: { readonly refresh: () => void }) {
  useRefreshAfterPageReturn(refresh)
  return <div />
}

describe('useRefreshAfterPageReturn', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockDidHide = undefined
    mockDidShow = undefined
  })

  afterEach(() => testUtils.unmout())

  it('首次展示不重复刷新，只有 hide 后再次 show 才刷新一次', async () => {
    const refresh = jest.fn()
    await testUtils.mount(Harness, { props: { refresh } })

    await testUtils.act(async () => { mockDidShow?.() })
    expect(refresh).not.toHaveBeenCalled()

    await testUtils.act(async () => {
      mockDidHide?.()
      mockDidShow?.()
      mockDidShow?.()
    })
    expect(refresh).toHaveBeenCalledTimes(1)
  })
})
