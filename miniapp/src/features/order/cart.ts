import type { components } from '@/api/generated/schema'
import type { StoragePort } from '@/platform/storage'

const CART_STORAGE_KEY = 'pinkdoohub.cart.v1'
const CART_VERSION = 2
const LEGACY_CART_VERSION = 1
export const CART_NON_COLOR_ITEM_LIMIT = 10
export const CART_COLOR_ITEM_LIMIT = 20
export const CART_ITEM_LIMIT = CART_NON_COLOR_ITEM_LIMIT + CART_COLOR_ITEM_LIMIT
export const CART_QUANTITY_LIMIT = 99
export const COLOR_SELECTABLE_SALE_UNIT_GRAMS = 10

export type CartProductType = 'experience' | 'kit'

interface CartItemBase {
  readonly productId: number
  readonly productName: string
  readonly unitPrice: string
  readonly imageUrl: string | null
  readonly quantity: number
}

export interface ExperienceCartItem extends CartItemBase {
  readonly experienceOptionId: number
  readonly kitColorId: null
  readonly productType: 'experience'
  readonly configurationLabel: string
}

export interface KitCartItem extends CartItemBase {
  readonly experienceOptionId: null
  readonly kitColorId: null
  readonly productType: 'kit'
  readonly kitKind: 'fixed'
  readonly configurationLabel: null
}

export interface ColorKitCartItem extends CartItemBase {
  readonly experienceOptionId: null
  readonly kitColorId: number
  readonly productType: 'kit'
  readonly kitKind: 'color_selectable'
  readonly configurationLabel: string
  readonly saleUnitGrams: typeof COLOR_SELECTABLE_SALE_UNIT_GRAMS
}

export type CartItem = ExperienceCartItem | KitCartItem | ColorKitCartItem
export type AddCartItemInput = CartItem
export type CartItemIdentity = Pick<CartItem, 'productId' | 'experienceOptionId' | 'kitColorId'>

export type CartStatus = 'initializing' | 'ready' | 'error'

export interface CartSnapshot {
  readonly status: CartStatus
  readonly items: readonly CartItem[]
  readonly initializationError?: Error
}

export interface CartReconciliationResult {
  readonly status: 'completed' | 'conflict'
  readonly preservedItemKeys: readonly string[]
}

export type CartListener = (snapshot: CartSnapshot) => void
export type OrderItemCreate = components['schemas']['OrderItemCreate']

interface StoredCart {
  readonly version: typeof CART_VERSION
  readonly items: readonly CartItem[]
}

export type CartValidationCode =
  | 'not_ready'
  | 'invalid_item'
  | 'item_limit'
  | 'quantity_limit'

export class CartValidationError extends Error {
  constructor(
    readonly code: CartValidationCode,
    message: string,
  ) {
    super(message)
    this.name = 'CartValidationError'
  }
}

export class CartStore {
  private status: CartStatus = 'initializing'
  private items: readonly CartItem[] = []
  private initializationError?: Error
  private readonly listeners = new Set<CartListener>()
  private operationQueue: Promise<void> = Promise.resolve()

  constructor(private readonly storage: StoragePort) {}

  getSnapshot(): CartSnapshot {
    return {
      status: this.status,
      items: this.items.map(copyCartItem),
      initializationError: this.initializationError,
    }
  }

  subscribe(listener: CartListener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  restore(): Promise<void> {
    return this.enqueue(async () => {
      this.setState('initializing', this.items)
      try {
        const stored = await this.storage.get(CART_STORAGE_KEY)
        const parsed = parseStoredCart(stored)
        if (!parsed) {
          if (stored !== undefined) {
            await this.storage.remove(CART_STORAGE_KEY)
          }
          this.setState('ready', [])
          return
        }
        // 重写 v2 白名单投影；旧购物车会在原 key 上原子升级，用户已有商品不会丢失。
        await this.storage.set(CART_STORAGE_KEY, parsed)
        this.setState('ready', parsed.items)
      } catch (cause) {
        this.setState('error', this.items, toError(cause, '购物车恢复失败'))
        throw cause
      }
    })
  }

  addItem(input: AddCartItemInput): Promise<void> {
    return this.addItems([input])
  }

  addItems(inputs: readonly AddCartItemInput[]): Promise<void> {
    return this.enqueue(async () => {
      this.assertReady()
      if (inputs.length < 1) {
        throw new CartValidationError('invalid_item', '请选择至少一个商品配置')
      }

      const parsedItems = inputs.map((input) => parseCartItem(input, false))
      if (parsedItems.some((item) => item === undefined)) {
        throw new CartValidationError('invalid_item', '无法加入无效的商品配置')
      }
      const batchKeys = new Set((parsedItems as CartItem[]).map(cartItemKey))
      if (batchKeys.size !== parsedItems.length) {
        throw new CartValidationError('invalid_item', '一次加入的商品配置不能重复')
      }

      let nextItems = this.items.map(copyCartItem)
      for (const item of parsedItems as CartItem[]) {
        const existingIndex = nextItems.findIndex(
          (candidate) => cartItemKey(candidate) === cartItemKey(item),
        )
        if (existingIndex >= 0) {
          const quantity = nextItems[existingIndex].quantity + item.quantity
          if (quantity > CART_QUANTITY_LIMIT) {
            throw new CartValidationError(
              'quantity_limit',
              `同一商品配置最多购买 ${CART_QUANTITY_LIMIT} 份`,
            )
          }
          nextItems = nextItems.map((candidate, index) => index === existingIndex
            ? { ...item, quantity }
            : candidate)
        } else {
          nextItems = [...nextItems, item]
        }
      }

      assertCartComposition(nextItems)
      await this.persist(nextItems)
    })
  }

  updateQuantity(identity: CartItemIdentity, quantity: number): Promise<void> {
    return this.enqueue(async () => {
      this.assertReady()
      if (!isPositiveInteger(quantity) || quantity > CART_QUANTITY_LIMIT) {
        throw new CartValidationError(
          'quantity_limit',
          `数量必须在 1 至 ${CART_QUANTITY_LIMIT} 之间`,
        )
      }
      const key = cartItemKey(identity)
      const index = this.items.findIndex((item) => cartItemKey(item) === key)
      if (index < 0) {
        throw new CartValidationError('invalid_item', '购物车中没有这个商品配置')
      }
      const nextItems = this.items.map((item, itemIndex) => itemIndex === index
        ? { ...item, quantity }
        : item)
      await this.persist(nextItems)
    })
  }

  removeItem(identity: CartItemIdentity): Promise<void> {
    return this.enqueue(async () => {
      this.assertReady()
      const key = cartItemKey(identity)
      const nextItems = this.items.filter((item) => cartItemKey(item) !== key)
      if (nextItems.length === this.items.length) {
        return
      }
      await this.persist(nextItems)
    })
  }

  clear(): Promise<void> {
    return this.enqueue(async () => {
      this.assertReady()
      await this.storage.remove(CART_STORAGE_KEY)
      this.setState('ready', [])
    })
  }

  reconcileSubmittedItems(submittedItems: readonly CartItem[]): Promise<CartReconciliationResult> {
    return this.enqueue(async () => {
      this.assertReady()
      const parsedItems = submittedItems.map((item) => parseCartItem(item, false))
      if (parsedItems.length < 1 || parsedItems.some((item) => item === undefined)) {
        throw new CartValidationError('invalid_item', '无法对账无效的已提交商品')
      }
      assertCartComposition(parsedItems as CartItem[])
      const submittedByKey = new Map(
        (parsedItems as CartItem[]).map((item) => [cartItemKey(item), item]),
      )
      if (submittedByKey.size !== parsedItems.length) {
        throw new CartValidationError('invalid_item', '已提交商品包含重复配置')
      }

      const preservedItemKeys: string[] = []
      const nextItems = this.items.flatMap((current) => {
        const key = cartItemKey(current)
        const submitted = submittedByKey.get(key)
        if (!submitted) {
          return [current]
        }
        if (current.quantity < submitted.quantity) {
          // 用户可能在请求期间修改了相同配置；无法证明剩余数量仍属于已提交快照时优先保留。
          preservedItemKeys.push(key)
          return [current]
        }
        if (current.quantity === submitted.quantity) {
          return []
        }
        return [{ ...current, quantity: current.quantity - submitted.quantity }]
      })

      await this.persist(nextItems)
      return {
        status: preservedItemKeys.length === 0 ? 'completed' : 'conflict',
        preservedItemKeys,
      }
    })
  }

  private enqueue<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.operationQueue.then(operation)
    this.operationQueue = result.then(() => undefined).catch(() => undefined)
    return result
  }

  private assertReady(): void {
    if (this.status !== 'ready') {
      throw new CartValidationError('not_ready', '购物车尚未准备好，请稍后重试')
    }
  }

  private async persist(items: readonly CartItem[]): Promise<void> {
    const stored: StoredCart = { version: CART_VERSION, items: items.map(copyCartItem) }
    // 先持久化再发布内存状态，写入失败时 UI 不展示伪成功。
    await this.storage.set(CART_STORAGE_KEY, stored)
    this.setState('ready', stored.items)
  }

  private setState(status: CartStatus, items: readonly CartItem[], initializationError?: Error): void {
    this.status = status
    this.items = items.map(copyCartItem)
    this.initializationError = initializationError
    const snapshot = this.getSnapshot()
    this.listeners.forEach((listener) => listener(snapshot))
  }
}

export function buildOrderItems(items: readonly CartItem[]): readonly OrderItemCreate[] {
  return items.map((item) => {
    if (item.productType === 'experience') {
      return {
        product_id: item.productId,
        experience_option_id: item.experienceOptionId,
        quantity: item.quantity,
      }
    }
    if (item.kitKind === 'color_selectable') {
      return {
        product_id: item.productId,
        kit_color_id: item.kitColorId,
        quantity: item.quantity,
      }
    }
    return { product_id: item.productId, quantity: item.quantity }
  })
}

export function cartItemKey(item: CartItemIdentity): string {
  if (item.experienceOptionId !== null) {
    return `${item.productId}:experience:${item.experienceOptionId}`
  }
  if (item.kitColorId !== null) {
    return `${item.productId}:color:${item.kitColorId}`
  }
  return `${item.productId}:fixed`
}

function assertCartComposition(items: readonly CartItem[]): void {
  const colorCount = items.filter(isColorKitCartItem).length
  const nonColorCount = items.length - colorCount
  if (colorCount > CART_COLOR_ITEM_LIMIT) {
    throw new CartValidationError(
      'item_limit',
      `每单最多选择 ${CART_COLOR_ITEM_LIMIT} 种拼豆颜色`,
    )
  }
  if (nonColorCount > CART_NON_COLOR_ITEM_LIMIT) {
    throw new CartValidationError(
      'item_limit',
      `每单最多包含 ${CART_NON_COLOR_ITEM_LIMIT} 种非自选颜色配置`,
    )
  }
  if (items.length > CART_ITEM_LIMIT) {
    throw new CartValidationError('item_limit', `每单最多包含 ${CART_ITEM_LIMIT} 个商品明细`)
  }
}

function parseStoredCart(value: unknown): StoredCart | undefined {
  if (!isRecord(value) || !Array.isArray(value.items) ||
    (value.version !== CART_VERSION && value.version !== LEGACY_CART_VERSION)) {
    return undefined
  }
  const allowLegacyShape = value.version === LEGACY_CART_VERSION
  const items: CartItem[] = []
  const keys = new Set<string>()
  for (const candidate of value.items) {
    const item = parseCartItem(candidate, allowLegacyShape)
    if (!item || keys.has(cartItemKey(item))) {
      return undefined
    }
    keys.add(cartItemKey(item))
    items.push(item)
  }
  try {
    assertCartComposition(items)
  } catch {
    return undefined
  }
  return { version: CART_VERSION, items }
}

function parseCartItem(value: unknown, allowLegacyShape: boolean): CartItem | undefined {
  if (!isRecord(value) || !(
    isPositiveInteger(value.productId) &&
    (value.productType === 'experience' || value.productType === 'kit') &&
    isBoundedText(value.productName, 100) &&
    isMoneyString(value.unitPrice) &&
    isNullableBoundedText(value.imageUrl, 2_048) &&
    isPositiveInteger(value.quantity) &&
    value.quantity <= CART_QUANTITY_LIMIT
  )) {
    return undefined
  }

  const kitColorId = hasOwn(value, 'kitColorId') ? value.kitColorId : null
  if (value.productType === 'experience') {
    if (!isPositiveInteger(value.experienceOptionId) ||
      !isBoundedText(value.configurationLabel, 200) ||
      kitColorId !== null ||
      (!allowLegacyShape && !hasOwn(value, 'kitColorId'))) {
      return undefined
    }
    return {
      productId: value.productId,
      experienceOptionId: value.experienceOptionId,
      kitColorId: null,
      productType: 'experience',
      productName: value.productName,
      configurationLabel: value.configurationLabel,
      unitPrice: value.unitPrice,
      imageUrl: value.imageUrl,
      quantity: value.quantity,
    }
  }

  if (value.experienceOptionId !== null) {
    return undefined
  }
  const kitKind = hasOwn(value, 'kitKind') ? value.kitKind : 'fixed'
  if (kitKind === 'fixed') {
    if (kitColorId !== null || value.configurationLabel !== null ||
      (!allowLegacyShape && (!hasOwn(value, 'kitColorId') || !hasOwn(value, 'kitKind')))) {
      return undefined
    }
    return {
      productId: value.productId,
      experienceOptionId: null,
      kitColorId: null,
      productType: 'kit',
      kitKind: 'fixed',
      productName: value.productName,
      configurationLabel: null,
      unitPrice: value.unitPrice,
      imageUrl: value.imageUrl,
      quantity: value.quantity,
    }
  }
  if (kitKind !== 'color_selectable' || !isPositiveInteger(kitColorId) ||
    !isBoundedText(value.configurationLabel, 200) ||
    value.saleUnitGrams !== COLOR_SELECTABLE_SALE_UNIT_GRAMS) {
    return undefined
  }
  return {
    productId: value.productId,
    experienceOptionId: null,
    kitColorId,
    productType: 'kit',
    kitKind: 'color_selectable',
    productName: value.productName,
    configurationLabel: value.configurationLabel,
    saleUnitGrams: COLOR_SELECTABLE_SALE_UNIT_GRAMS,
    unitPrice: value.unitPrice,
    imageUrl: value.imageUrl,
    quantity: value.quantity,
  }
}

function isColorKitCartItem(item: CartItem): item is ColorKitCartItem {
  return item.productType === 'kit' && item.kitKind === 'color_selectable'
}

function copyCartItem(item: CartItem): CartItem {
  return { ...item }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

function isBoundedText(value: unknown, maxLength: number): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= maxLength
}

function isNullableBoundedText(value: unknown, maxLength: number): value is string | null {
  return value === null || (typeof value === 'string' && value.length > 0 && value.length <= maxLength)
}

function isMoneyString(value: unknown): value is string {
  return typeof value === 'string' && /^(?:0|[1-9]\d{0,4})\.\d{2}$/.test(value) && value !== '0.00'
}

function toError(cause: unknown, fallbackMessage: string): Error {
  return cause instanceof Error ? cause : new Error(fallbackMessage)
}
