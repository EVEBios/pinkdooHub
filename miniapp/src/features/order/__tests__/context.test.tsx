import { act, useEffect, useState } from 'react'
import { Text } from '@tarojs/components'
import ReactTestUtil from '@tarojs/test-utils-react'
import { CartProvider, useCart } from '../context'
import { CartStore } from '../cart'

describe('购物车启用不重挂载路由子树', () => {
  let util: ReactTestUtil
  beforeEach(() => { util = new ReactTestUtil() })
  afterEach(() => { util.unmout() })

  it('身份恢复及退出保持页面实例，只有顾客上下文订阅和恢复购物车', async () => {
    const storage = { get: jest.fn().mockResolvedValue(undefined), set: jest.fn(), remove: jest.fn() }
    const store = new CartStore(storage)
    const runtime = { store }
    const mounted = jest.fn()
    const disposed = jest.fn()
    let enable!: (value: boolean) => void
    function Page() {
      useEffect(() => { mounted(); return disposed }, [])
      return <Text>页面</Text>
    }
    function Subject() {
      const [enabled, setEnabled] = useState(false)
      enable = setEnabled
      return <CartProvider enabled={enabled} runtime={runtime}><Page /></CartProvider>
    }
    await util.mount(Subject)
    expect(storage.get).not.toHaveBeenCalled()
    await act(async () => { enable(true) })
    expect(storage.get).toHaveBeenCalledTimes(1)
    await act(async () => { enable(false) })
    expect(mounted).toHaveBeenCalledTimes(1)
    expect(disposed).not.toHaveBeenCalled()
    expect(storage.get).toHaveBeenCalledTimes(1)
  })

  it('顾客恢复后可以读取购物车', async () => {
    const storage = { get: jest.fn().mockResolvedValue(undefined), set: jest.fn(), remove: jest.fn() }
    const store = new CartStore(storage)
    let status: string | undefined
    function Page() { status = useCart().status; return <Text>{status}</Text> }
    await util.mount(() => <CartProvider runtime={{ store }}><Page /></CartProvider>)
    await act(async () => { await Promise.resolve() })
    expect(status).toBe('ready')
  })
})
