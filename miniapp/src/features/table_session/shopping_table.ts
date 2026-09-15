import type { OrderCreateRequest } from '@/api/endpoints/orders'
import type { CartItem } from '@/features/order/cart'
import { TaroStorageAdapter, type StoragePort } from '@/platform/storage'

import { createTableIntentKey } from './idempotency'

const MAX_AGE_MS = 2 * 60 * 60 * 1000
export interface ShoppingTable {
  readonly tableNo: string
  readonly selectionId: string
  readonly savedAt: number
}
export interface CheckoutAttempt {
  readonly request: OrderCreateRequest
  readonly items: readonly CartItem[]
  readonly selectionId: string
}
export interface ShoppingTableState {
  readonly selection?: ShoppingTable
  readonly attempt?: CheckoutAttempt
}

/** 本次选桌与未知提交按账号持久化；未知提交必须先恢复，不能换一笔继续扣库存。 */
export class ShoppingTableStore {
  private queue: Promise<unknown> = Promise.resolve()
  private listeners = new Set<() => void>()
  constructor(private readonly storage: StoragePort, private readonly now = Date.now) {}
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private key(userId: number): string {
    if (!Number.isSafeInteger(userId) || userId <= 0) throw new Error('请先登录再选择桌台')
    return `pinkdoohub.shopping-table.v1.${userId}`
  }
  private run<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.queue.then(operation)
    this.queue = result.catch(() => undefined)
    return result
  }
  private async read(userId: number): Promise<ShoppingTableState> {
    const value = await this.storage.get(this.key(userId))
    if (value === undefined) return {}
    if (!value || typeof value !== 'object') throw new Error('桌台记录读取失败，请重试')
    const state = value as ShoppingTableState
    if (state.selection && (!/^T(?:0[1-9]|[12]\d|30)$/.test(state.selection.tableNo) ||
      !Number.isFinite(state.selection.savedAt) || typeof state.selection.selectionId !== 'string')) {
      throw new Error('桌台记录无效，请重新选择')
    }
    if (state.attempt && (!state.attempt.request?.table_checkout_key || !state.attempt.request.table_no ||
      !Array.isArray(state.attempt.request.items) || !Array.isArray(state.attempt.items))) {
      throw new Error('上次订单记录无法读取，请先到我的订单核对')
    }
    return state
  }
  private async write(userId: number, state: ShoppingTableState): Promise<void> {
    await this.storage.set(this.key(userId), state)
    this.listeners.forEach((listener) => listener())
  }
  load(userId: number): Promise<ShoppingTableState> { return this.run(() => this.read(userId)) }
  expired(selection: ShoppingTable): boolean {
    return this.now() < selection.savedAt || this.now() - selection.savedAt > MAX_AGE_MS
  }
  select(userId: number, tableNo?: string): Promise<void> {
    return this.run(async () => {
      const state = await this.read(userId)
      if (state.attempt) throw new Error('请先核对上次开台订单的提交结果')
      if (tableNo !== undefined && !/^T(?:0[1-9]|[12]\d|30)$/.test(tableNo)) throw new Error('请输入 1–30 号桌')
      if (tableNo && state.selection?.tableNo === tableNo && !this.expired(state.selection)) return
      await this.write(userId, tableNo ? { selection: {
        tableNo, selectionId: createTableIntentKey('checkout'), savedAt: this.now(),
      } } : {})
    })
  }
  consumeSelection(userId: number, selectionId: string): Promise<void> {
    return this.run(async () => {
      const state = await this.read(userId)
      if (!state.attempt && state.selection?.selectionId === selectionId) await this.write(userId, {})
    })
  }
  prepare(userId: number, request: OrderCreateRequest, items: readonly CartItem[]): Promise<CheckoutAttempt> {
    return this.run(async () => {
      const state = await this.read(userId)
      if (state.attempt) return state.attempt
      if (!state.selection || this.expired(state.selection)) throw new Error('本次选桌已失效，请重新确认桌台')
      if (request.table_no !== state.selection.tableNo) throw new Error('本次桌台已变更，请重新核对订单')
      const attempt: CheckoutAttempt = {
        request: { ...request, table_checkout_key: createTableIntentKey('checkout') },
        items: items.map((item) => ({ ...item })), selectionId: state.selection.selectionId,
      }
      await this.write(userId, { ...state, attempt })
      return attempt
    })
  }
  finish(userId: number, key: string, succeeded: boolean): Promise<void> {
    return this.run(async () => {
      const state = await this.read(userId)
      if (state.attempt?.request.table_checkout_key !== key) return
      await this.write(userId, succeeded ? {} : { selection: state.selection })
    })
  }
}
export const shoppingTableStore = new ShoppingTableStore(new TaroStorageAdapter())
