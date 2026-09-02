import type { StoragePort } from '@/platform/storage'

import {
  buildOrderItems,
  CART_ITEM_LIMIT,
  CartStore,
  type ExperienceCartItem,
  type KitCartItem,
} from '../cart'

class FakeStorage implements StoragePort {
  value: unknown
  readonly writes: unknown[] = []
  removeCount = 0
  writeError?: Error

  constructor(value?: unknown) {
    this.value = value
  }

  async get(): Promise<unknown> {
    return this.value
  }

  async set(_key: string, value: unknown): Promise<void> {
    if (this.writeError) {
      throw this.writeError
    }
    this.value = value
    this.writes.push(value)
  }

  async remove(): Promise<void> {
    this.value = undefined
    this.removeCount += 1
  }
}

const experienceItem = (overrides: Partial<ExperienceCartItem> = {}): ExperienceCartItem => ({
  productId: 1,
  experienceOptionId: 11,
  productType: 'experience',
  productName: '周末拼豆体验',
  configurationLabel: '1小时 · 2人 · 工作日',
  unitPrice: '299.00',
  imageUrl: '/uploads/products/option.png',
  quantity: 1,
  ...overrides,
})

const kitItem = (overrides: Partial<KitCartItem> = {}): KitCartItem => ({
  productId: 2,
  experienceOptionId: null,
  productType: 'kit',
  productName: '基础拼豆套装',
  configurationLabel: null,
  unitPrice: '599.00',
  imageUrl: '/uploads/products/kit.png',
  quantity: 1,
  ...overrides,
})

describe('CartStore', () => {
  it('从空 Storage 恢复为空购物车', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)

    await store.restore()

    expect(store.getSnapshot()).toMatchObject({ status: 'ready', items: [] })
    expect(storage.removeCount).toBe(0)
  })

  it('清除版本错误、重复组合或字段不完整的坏数据', async () => {
    const invalidValues = [
      { version: 2, items: [] },
      { version: 1, items: [experienceItem(), experienceItem()] },
      { version: 1, items: [{ ...kitItem(), experienceOptionId: 99 }] },
    ]

    for (const value of invalidValues) {
      const storage = new FakeStorage(value)
      const store = new CartStore(storage)
      await store.restore()
      expect(store.getSnapshot()).toMatchObject({ status: 'ready', items: [] })
      expect(storage.removeCount).toBe(1)
    }
  })

  it('恢复时对白名单字段重新投影并写回', async () => {
    const storage = new FakeStorage({
      version: 1,
      items: [{ ...experienceItem(), accessToken: 'must-not-survive' }],
      extra: 'removed',
    })
    const store = new CartStore(storage)

    await store.restore()

    expect(store.getSnapshot().items).toEqual([experienceItem()])
    expect(storage.value).toEqual({ version: 1, items: [experienceItem()] })
  })

  it('并发重复加入同一组合时串行合并数量', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)
    await store.restore()

    await Promise.all([
      store.addItem(experienceItem()),
      store.addItem(experienceItem()),
    ])

    expect(store.getSnapshot().items).toEqual([experienceItem({ quantity: 2 })])
  })

  it('同一 Experience 的不同 Option 保持为不同条目', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)
    await store.restore()

    await store.addItem(experienceItem())
    await store.addItem(experienceItem({
      experienceOptionId: 12,
      configurationLabel: '2小时 · 2人 · 周末',
      unitPrice: '399.00',
    }))

    expect(store.getSnapshot().items).toHaveLength(2)
  })

  it('限制不同组合数量和单组合数量', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)
    await store.restore()

    for (let index = 0; index < CART_ITEM_LIMIT; index += 1) {
      await store.addItem(experienceItem({
        experienceOptionId: 100 + index,
        configurationLabel: `配置 ${index + 1}`,
      }))
    }

    await expect(store.addItem(kitItem())).rejects.toMatchObject({ code: 'item_limit' })
    await store.updateQuantity(1, 100, 99)
    await expect(store.addItem(experienceItem({
      experienceOptionId: 100,
      configurationLabel: '配置 1',
    }))).rejects.toMatchObject({ code: 'quantity_limit' })
  })

  it('持久化失败时不发布伪成功状态', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)
    await store.restore()
    storage.writeError = new Error('disk full')

    await expect(store.addItem(kitItem())).rejects.toThrow('disk full')

    expect(store.getSnapshot().items).toEqual([])
  })

  it('支持修改数量、移除和清空', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)
    await store.restore()
    await store.addItem(experienceItem())
    await store.addItem(kitItem())

    await store.updateQuantity(2, null, 3)
    expect(store.getSnapshot().items[1].quantity).toBe(3)
    await store.removeItem(1, 11)
    expect(store.getSnapshot().items).toEqual([kitItem({ quantity: 3 })])
    await store.clear()
    expect(store.getSnapshot().items).toEqual([])
    expect(storage.value).toBeUndefined()
  })

  it('创建成功后移除已提交数量，并保留未提交或后来增加的数量', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)
    await store.restore()
    await store.addItem(experienceItem())
    await store.addItem(kitItem({ quantity: 4 }))
    await store.addItem(experienceItem({
      experienceOptionId: 12,
      configurationLabel: '2小时 · 2人 · 周末',
    }))

    const result = await store.reconcileSubmittedItems([
      experienceItem(),
      kitItem({ quantity: 2 }),
    ])

    expect(result).toEqual({ status: 'completed', preservedItemKeys: [] })
    expect(store.getSnapshot().items).toEqual([
      kitItem({ quantity: 2 }),
      experienceItem({
        experienceOptionId: 12,
        configurationLabel: '2小时 · 2人 · 周末',
      }),
    ])
  })

  it('当前数量小于提交快照时保守保留并报告对账冲突', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)
    await store.restore()
    await store.addItem(kitItem())

    const result = await store.reconcileSubmittedItems([kitItem({ quantity: 2 })])

    expect(result).toEqual({ status: 'conflict', preservedItemKeys: ['2:kit'] })
    expect(store.getSnapshot().items).toEqual([kitItem()])
  })

  it('对账持久化失败时保留现有购物清单', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)
    await store.restore()
    await store.addItem(kitItem())
    storage.writeError = new Error('disk full')

    await expect(store.reconcileSubmittedItems([kitItem()])).rejects.toThrow('disk full')

    expect(store.getSnapshot().items).toEqual([kitItem()])
  })
})

describe('buildOrderItems', () => {
  it('只映射服务端允许字段，Experience 保留 Option，Kit 省略 Option', () => {
    const items = buildOrderItems([experienceItem({ quantity: 2 }), kitItem({ quantity: 3 })])

    expect(items).toEqual([
      { product_id: 1, experience_option_id: 11, quantity: 2 },
      { product_id: 2, quantity: 3 },
    ])
    expect(items[0]).not.toHaveProperty('unitPrice')
    expect(items[1]).not.toHaveProperty('experience_option_id')
  })
})
