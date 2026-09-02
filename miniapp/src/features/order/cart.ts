import type { components } from '@/api/generated/schema'
import type { StoragePort } from '@/platform/storage'

const CART_STORAGE_KEY = 'pinkdoohub.cart.v1'
const CART_VERSION = 1
export const CART_ITEM_LIMIT = 10
export const CART_QUANTITY_LIMIT = 99

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
  readonly productType: 'experience'
  readonly configurationLabel: string
}

export interface KitCartItem extends CartItemBase {
  readonly experienceOptionId: null
  readonly productType: 'kit'
  readonly configurationLabel: null
}

export type CartItem = ExperienceCartItem | KitCartItem

export type AddCartItemInput = CartItem

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
        // 重写白名单投影，清除 Storage 中可能存在的多余字段。
        await this.storage.set(CART_STORAGE_KEY, parsed)
        this.setState('ready', parsed.items)
      } catch (cause) {
        this.setState('error', this.items, toError(cause, '购物车恢复失败'))
        throw cause
      }
    })
  }

  addItem(input: AddCartItemInput): Promise<void> {
    return this.enqueue(async () => {
      this.assertReady()
      const item = parseCartItem(input)
      if (!item) {
        throw new CartValidationError('invalid_item', '无法加入无效的商品配置')
      }

      const existingIndex = this.items.findIndex((candidate) => cartItemKey(candidate) === cartItemKey(item))
      if (existingIndex >= 0) {
        const quantity = this.items[existingIndex].quantity + item.quantity
        if (quantity > CART_QUANTITY_LIMIT) {
          throw new CartValidationError('quantity_limit', `同一商品配置最多购买 ${CART_QUANTITY_LIMIT} 件`)
        }
        const nextItems = this.items.map((candidate, index) => index === existingIndex
          ? { ...item, quantity }
          : candidate)
        await this.persist(nextItems)
        return
      }

      if (this.items.length >= CART_ITEM_LIMIT) {
        throw new CartValidationError('item_limit', `购物车最多包含 ${CART_ITEM_LIMIT} 种商品配置`)
      }
      await this.persist([...this.items, item])
    })
  }

  updateQuantity(productId: number, experienceOptionId: number | null, quantity: number): Promise<void> {
    return this.enqueue(async () => {
      this.assertReady()
      if (!isPositiveInteger(quantity) || quantity > CART_QUANTITY_LIMIT) {
        throw new CartValidationError('quantity_limit', `数量必须在 1 至 ${CART_QUANTITY_LIMIT} 之间`)
      }
      const key = cartItemKey({ productId, experienceOptionId })
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

  removeItem(productId: number, experienceOptionId: number | null): Promise<void> {
    return this.enqueue(async () => {
      this.assertReady()
      const key = cartItemKey({ productId, experienceOptionId })
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
      const parsedItems = submittedItems.map(parseCartItem)
      if (
        parsedItems.length < 1 ||
        parsedItems.length > CART_ITEM_LIMIT ||
        parsedItems.some((item) => item === undefined)
      ) {
        throw new CartValidationError('invalid_item', '无法对账无效的已提交商品')
      }
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
  return items.map((item) => item.productType === 'experience'
    ? {
        product_id: item.productId,
        experience_option_id: item.experienceOptionId,
        quantity: item.quantity,
      }
    : {
        product_id: item.productId,
        quantity: item.quantity,
      })
}

export function cartItemKey(item: { readonly productId: number; readonly experienceOptionId: number | null }): string {
  return `${item.productId}:${item.experienceOptionId ?? 'kit'}`
}

function parseStoredCart(value: unknown): StoredCart | undefined {
  if (!isRecord(value) || value.version !== CART_VERSION || !Array.isArray(value.items)) {
    return undefined
  }
  if (value.items.length > CART_ITEM_LIMIT) {
    return undefined
  }
  const items: CartItem[] = []
  const keys = new Set<string>()
  for (const candidate of value.items) {
    const item = parseCartItem(candidate)
    if (!item || keys.has(cartItemKey(item))) {
      return undefined
    }
    keys.add(cartItemKey(item))
    items.push(item)
  }
  return { version: CART_VERSION, items }
}

function parseCartItem(value: unknown): CartItem | undefined {
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

  if (value.productType === 'experience') {
    if (!isPositiveInteger(value.experienceOptionId) || !isBoundedText(value.configurationLabel, 200)) {
      return undefined
    }
    return {
      productId: value.productId,
      experienceOptionId: value.experienceOptionId,
      productType: 'experience',
      productName: value.productName,
      configurationLabel: value.configurationLabel,
      unitPrice: value.unitPrice,
      imageUrl: value.imageUrl,
      quantity: value.quantity,
    }
  }
  if (value.experienceOptionId !== null || value.configurationLabel !== null) {
    return undefined
  }
  return {
    productId: value.productId,
    experienceOptionId: null,
    productType: 'kit',
    productName: value.productName,
    configurationLabel: null,
    unitPrice: value.unitPrice,
    imageUrl: value.imageUrl,
    quantity: value.quantity,
  }
}

function copyCartItem(item: CartItem): CartItem {
  return { ...item }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
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
