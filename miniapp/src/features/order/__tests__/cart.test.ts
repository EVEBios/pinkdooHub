import type { StoragePort } from '@/platform/storage'

import {
  buildOrderItems,
  CART_COLOR_ITEM_LIMIT,
  CART_NON_COLOR_ITEM_LIMIT,
  CartStore,
  type ColorKitCartItem,
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
  kitColorId: null,
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
  kitColorId: null,
  productType: 'kit',
  kitKind: 'fixed',
  productName: '基础拼豆套装',
  configurationLabel: null,
  unitPrice: '599.00',
  imageUrl: '/uploads/products/kit.png',
  quantity: 1,
  ...overrides,
})

const colorItem = (overrides: Partial<ColorKitCartItem> = {}): ColorKitCartItem => ({
  productId: 3,
  experienceOptionId: null,
  kitColorId: 301,
  productType: 'kit',
  kitKind: 'color_selectable',
  productName: '自选拼豆',
  configurationLabel: 'A01 · 樱粉',
  saleUnitGrams: 10,
  swatchHex: '#F4B7C7',
  unitPrice: '3.00',
  imageUrl: null,
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
      { version: 3, items: [] },
      { version: 2, items: [experienceItem(), experienceItem()] },
      { version: 1, items: [{ ...kitItem(), experienceOptionId: 99 }] },
      { version: 2, items: [colorItem({ swatchHex: '#f4b7c7' })] },
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
    expect(storage.value).toEqual({ version: 2, items: [experienceItem()] })
  })

  it('把 v1 Experience 与固定 Kit 购物车迁移为 v2 身份字段', async () => {
    const legacyExperience = { ...experienceItem() } as Record<string, unknown>
    const legacyKit = { ...kitItem() } as Record<string, unknown>
    delete legacyExperience.kitColorId
    delete legacyKit.kitColorId
    delete legacyKit.kitKind
    const storage = new FakeStorage({ version: 1, items: [legacyExperience, legacyKit] })
    const store = new CartStore(storage)

    await store.restore()

    expect(store.getSnapshot().items).toEqual([experienceItem(), kitItem()])
    expect(storage.value).toEqual({ version: 2, items: [experienceItem(), kitItem()] })
  })

  it('恢复旧 v2 颜色项时清空无法区分色样与商品封面的歧义图片', async () => {
    const legacyColor = {
      ...colorItem(),
      imageUrl: '/uploads/products/legacy-cover.webp',
    } as Record<string, unknown>
    delete legacyColor.swatchHex
    const storage = new FakeStorage({ version: 2, items: [legacyColor] })
    const store = new CartStore(storage)

    await store.restore()

    expect(store.getSnapshot().items).toEqual([
      colorItem({ swatchHex: null, imageUrl: null }),
    ])
    expect(storage.value).toEqual({
      version: 2,
      items: [colorItem({ swatchHex: null, imageUrl: null })],
    })
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

    for (let index = 0; index < CART_NON_COLOR_ITEM_LIMIT; index += 1) {
      await store.addItem(experienceItem({
        experienceOptionId: 100 + index,
        configurationLabel: `配置 ${index + 1}`,
      }))
    }

    await expect(store.addItem(kitItem())).rejects.toMatchObject({ code: 'item_limit' })
    await store.updateQuantity(experienceItem({ experienceOptionId: 100 }), 99)
    await expect(store.addItem(experienceItem({
      experienceOptionId: 100,
      configurationLabel: '配置 1',
    }))).rejects.toMatchObject({ code: 'quantity_limit' })
  })

  it('批量加入颜色是原子的，并限制每单最多 20 色', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)
    await store.restore()
    const colors = Array.from({ length: CART_COLOR_ITEM_LIMIT }, (_, index) => colorItem({
      kitColorId: 301 + index,
      configurationLabel: `C${index + 1} · 颜色 ${index + 1}`,
    }))

    await store.addItems(colors)
    await expect(store.addItems([colorItem({
      kitColorId: 999,
      configurationLabel: 'C999 · 额外颜色',
    })])).rejects.toMatchObject({ code: 'item_limit' })

    expect(store.getSnapshot().items).toEqual(colors)
  })

  it('批量中任一颜色超过 990g 时整批拒绝', async () => {
    const storage = new FakeStorage()
    const store = new CartStore(storage)
    await store.restore()

    await expect(store.addItems([
      colorItem(),
      colorItem({ kitColorId: 302, quantity: 100 }),
    ])).rejects.toMatchObject({ code: 'invalid_item' })
    expect(store.getSnapshot().items).toEqual([])
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

    await store.updateQuantity(kitItem(), 3)
    expect(store.getSnapshot().items[1].quantity).toBe(3)
    await store.removeItem(experienceItem())
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

    expect(result).toEqual({ status: 'conflict', preservedItemKeys: ['2:fixed'] })
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
  it('只映射服务端允许字段，并为自选颜色携带商品颜色 ID', () => {
    const items = buildOrderItems([
      experienceItem({ quantity: 2 }),
      kitItem({ quantity: 3 }),
      colorItem({ quantity: 4 }),
    ])

    expect(items).toEqual([
      { product_id: 1, experience_option_id: 11, quantity: 2 },
      { product_id: 2, quantity: 3 },
      { product_id: 3, kit_color_id: 301, quantity: 4 },
    ])
    expect(items[0]).not.toHaveProperty('unitPrice')
    expect(items[1]).not.toHaveProperty('experience_option_id')
  })
})
