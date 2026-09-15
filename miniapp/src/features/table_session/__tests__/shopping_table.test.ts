import { NetworkError } from '@/api'
import type { OrderCreateRequest, OrderDetail } from '@/api/endpoints/orders'
import type { ExperienceCartItem } from '@/features/order/cart'
import { OrderSubmissionStore } from '@/features/order/submission'
import type { StoragePort } from '@/platform/storage'

import { ShoppingTableStore } from '../shopping_table'

function memoryStorage(): StoragePort {
  const values = new Map<string, unknown>()
  return {
    get: jest.fn(async (key) => values.get(key)),
    set: jest.fn(async (key, value) => { values.set(key, JSON.parse(JSON.stringify(value))) }),
    remove: jest.fn(async (key) => { values.delete(key) }),
  }
}
const item: ExperienceCartItem = {
  productId: 1, experienceOptionId: 2, kitColorId: null, productType: 'experience',
  productName: '拼豆体验', configurationLabel: '60 分钟 · 1 人', unitPrice: '59.00', imageUrl: null, quantity: 1,
}
const request = { items: [{ product_id: 1, experience_option_id: 2, quantity: 1 }], table_no: 'T08' }
const order: OrderDetail = {
  id: 10, order_no: `OD${'1'.repeat(26)}`, status: { value: 'pending', label: '待支付' },
  total_amount: '59.00', remark: null, items: [], created_at: '2026-09-14T01:00:00Z', updated_at: '2026-09-14T01:00:00Z',
}

describe('本次购物桌台和结算恢复', () => {
  it('扫码选择可跨实例恢复且账号隔离，重复进入同桌不覆盖选择', async () => {
    const storage = memoryStorage()
    const first = new ShoppingTableStore(storage, () => 1000)
    await first.select(7, 'T08')
    const saved = await first.load(7)
    const second = new ShoppingTableStore(storage, () => 2000)
    expect(await second.load(7)).toEqual(saved)
    expect(await second.load(8)).toEqual({})
    await second.select(7, 'T08')
    expect(await second.load(7)).toEqual(saved)
    await second.select(7, 'T09')
    expect((await second.load(7)).selection?.tableNo).toBe('T09')
    await second.select(7)
    expect(await second.load(7)).toEqual({})
  })
  it('过期选择保留提醒但不能直接提交，重新核对同桌后恢复', async () => {
    let now = 1000
    const store = new ShoppingTableStore(memoryStorage(), () => now)
    await store.select(7, 'T08')
    now += 2 * 60 * 60 * 1000 + 1
    expect(store.expired((await store.load(7)).selection!)).toBe(true)
    await expect(store.prepare(7, request, [item])).rejects.toThrow('选桌已失效')
    await store.select(7, 'T08')
    expect(store.expired((await store.load(7)).selection!)).toBe(false)
  })
  it('提交未知时冻结原请求，不能换桌或清除；旧结果不能清除新请求', async () => {
    const store = new ShoppingTableStore(memoryStorage())
    await store.select(7, 'T08')
    const attempt = await store.prepare(7, request, [item])
    expect(await store.prepare(7, { ...request, remark: '新备注' }, [{ ...item, quantity: 2 }])).toEqual(attempt)
    await expect(store.select(7, 'T09')).rejects.toThrow('先核对')
    await expect(store.select(7)).rejects.toThrow('先核对')
    await store.finish(7, 'another-key', true)
    expect((await store.load(7)).attempt).toEqual(attempt)
    await store.finish(7, attempt.request.table_checkout_key!, false)
    expect((await store.load(7)).selection?.tableNo).toBe('T08')
    const next = await store.prepare(7, request, [item])
    expect(next.request.table_checkout_key).not.toBe(attempt.request.table_checkout_key)
  })
  it('保存失败时不发送下单请求', async () => {
    const storage = memoryStorage()
    const tables = new ShoppingTableStore(storage)
    await tables.select(7, 'T08')
    ;(storage.set as jest.Mock).mockRejectedValueOnce(new Error('存储不可用'))
    const api = { createOrder: jest.fn(async (_request: OrderCreateRequest) => order) }
    const submission = new OrderSubmissionStore(api, undefined, tables)
    await submission.submit([item], '', { userId: 7, tableNo: 'T08' })
    expect(api.createOrder).not.toHaveBeenCalled()
    expect(submission.getState().status).toBe('failed')
  })
  it('首次成功才清理选桌和已提交商品，不受重复点击影响', async () => {
    const tables = new ShoppingTableStore(memoryStorage())
    await tables.select(7, 'T08')
    const api = { createOrder: jest.fn(async (_request: OrderCreateRequest) => order) }
    const cart = { reconcileSubmittedItems: jest.fn(async () => ({ status: 'completed' as const, preservedItemKeys: [] })) }
    const submission = new OrderSubmissionStore(api, cart, tables)
    await Promise.all([submission.submit([item], '', { userId: 7, tableNo: 'T08' }), submission.submit([item], '', { userId: 7, tableNo: 'T08' })])
    expect(api.createOrder).toHaveBeenCalledTimes(1)
    expect(api.createOrder.mock.calls[0][0]).toMatchObject({ table_no: 'T08', table_checkout_key: expect.any(String) })
    expect(cart.reconcileSubmittedItems).toHaveBeenCalledTimes(1)
    expect(await tables.load(7)).toEqual({})
    expect(submission.getState().status).toBe('succeeded')
  })
  it('重启后用原幂等键和原商品恢复，不误删用户后来加入购物车的商品', async () => {
    const storage = memoryStorage()
    const tables = new ShoppingTableStore(storage)
    await tables.select(7, 'T08')
    const api = { createOrder: jest.fn().mockRejectedValueOnce(new NetworkError({ operation: 'orders.create' }, new Error('offline'))).mockResolvedValue(order) }
    const cart = { reconcileSubmittedItems: jest.fn(async () => ({ status: 'completed' as const, preservedItemKeys: [] })) }
    const original = new OrderSubmissionStore(api, cart, tables)
    await original.submit([item], '原备注', { userId: 7, tableNo: 'T08' })
    expect(original.getState().status).toBe('unknown')
    const resumed = new OrderSubmissionStore(api, cart, new ShoppingTableStore(storage))
    await resumed.submit([{ ...item, quantity: 2 }], '新备注', { userId: 7, tableNo: 'T08' })
    expect(api.createOrder.mock.calls[1][0]).toEqual(api.createOrder.mock.calls[0][0])
    expect(cart.reconcileSubmittedItems).not.toHaveBeenCalled()
    expect(resumed.getState()).toMatchObject({ status: 'succeeded', cartReconciliationError: expect.any(Error) })
    expect(await tables.load(7)).toEqual({})
  })
})
