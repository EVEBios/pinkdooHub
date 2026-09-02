import { useCallback, useEffect, useRef, useState } from 'react'

import { BusinessError, SessionExpiredError } from '@/api'
import type { AdminOrderDetail, OrderStatusResult } from '@/api/endpoints/orders'

import { getDefaultOrderApi } from './runtime'
import { isOrderCommandUnknownError } from './submission'

export type AdminOrderDetailState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | { readonly status: 'content'; readonly order: AdminOrderDetail }

export type AdminOrderTransitionAction = 'mark_paid' | 'complete'

export type AdminOrderTransitionState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly action: AdminOrderTransitionAction }
  | { readonly status: 'failed'; readonly action: AdminOrderTransitionAction; readonly errorMessage: string }
  | { readonly status: 'unknown'; readonly action: AdminOrderTransitionAction; readonly errorMessage: string }
  | {
      readonly status: 'succeeded'
      readonly action: AdminOrderTransitionAction
      readonly result: OrderStatusResult
      readonly refreshErrorMessage?: string
    }

export interface AdminOrderDetailSource {
  getAdminOrderDetail(orderId: number): Promise<AdminOrderDetail>
  markOrderPaid(orderId: number): Promise<OrderStatusResult>
  completeOrder(orderId: number): Promise<OrderStatusResult>
}

export interface AdminOrderDetailFeature {
  readonly detail: AdminOrderDetailState
  readonly transition: AdminOrderTransitionState
  retry(): void
  advanceStatus(): Promise<void>
}

export function useAdminOrderDetail(
  orderId: number,
  source: AdminOrderDetailSource = getDefaultOrderApi(),
): AdminOrderDetailFeature {
  const [detail, setDetail] = useState<AdminOrderDetailState>({ status: 'loading' })
  const [transition, setTransition] = useState<AdminOrderTransitionState>({ status: 'idle' })
  const requestSequenceRef = useRef(0)
  const activeTransitionRef = useRef<Promise<void>>()

  const load = useCallback(() => {
    const sequence = ++requestSequenceRef.current
    setDetail({ status: 'loading' })
    void source.getAdminOrderDetail(orderId).then((order) => {
      if (sequence === requestSequenceRef.current) {
        setDetail({ status: 'content', order })
      }
    }).catch((cause: unknown) => {
      if (sequence === requestSequenceRef.current) {
        setDetail({ status: 'error', errorMessage: getDetailErrorMessage(cause) })
      }
    })
  }, [orderId, source])

  useEffect(() => {
    load()
    return () => {
      requestSequenceRef.current += 1
    }
  }, [load])

  const advanceStatus = useCallback((): Promise<void> => {
    if (activeTransitionRef.current) {
      return activeTransitionRef.current
    }
    if (detail.status !== 'content') {
      return Promise.resolve()
    }
    const action = getTransitionAction(detail.order)
    if (!action) {
      return Promise.resolve()
    }
    const currentOrder = detail.order
    const operation = (async () => {
      setTransition({ status: 'submitting', action })
      try {
        const result = action === 'mark_paid'
          ? await source.markOrderPaid(orderId)
          : await source.completeOrder(orderId)
        setDetail({
          status: 'content',
          order: { ...currentOrder, status: result.status, updated_at: result.updated_at },
        })
        let refreshErrorMessage: string | undefined
        try {
          const refreshed = await source.getAdminOrderDetail(orderId)
          setDetail({ status: 'content', order: refreshed })
        } catch (cause) {
          refreshErrorMessage = toMessage(cause, '状态已更新，但详情刷新失败')
        }
        setTransition({
          status: 'succeeded',
          action,
          result,
          ...(refreshErrorMessage ? { refreshErrorMessage } : {}),
        })
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('订单状态更新失败')
        if (error instanceof BusinessError && error.code === 40921) {
          try {
            const refreshed = await source.getAdminOrderDetail(orderId)
            setDetail({ status: 'content', order: refreshed })
          } catch {
            // 保留明确冲突错误，由管理员手动重试读取权威状态。
          }
        }
        setTransition(isOrderCommandUnknownError(error)
          ? { status: 'unknown', action, errorMessage: '更新结果可能未知，请重新加载核对权威状态' }
          : { status: 'failed', action, errorMessage: getTransitionErrorMessage(error) })
      }
    })()
    activeTransitionRef.current = operation
    void operation.finally(() => {
      if (activeTransitionRef.current === operation) {
        activeTransitionRef.current = undefined
      }
    }).catch(() => undefined)
    return operation
  }, [detail, orderId, source])

  return { detail, transition, retry: load, advanceStatus }
}

export function getTransitionAction(order: AdminOrderDetail): AdminOrderTransitionAction | undefined {
  if (order.status.value === 'pending') {
    return 'mark_paid'
  }
  if (order.status.value === 'paid') {
    return 'complete'
  }
  return undefined
}

function getDetailErrorMessage(cause: unknown): string {
  if (cause instanceof BusinessError) {
    if (cause.code === 40411) {
      return '订单不存在'
    }
    if (cause.statusCode === 403) {
      return '当前账号没有管理订单的权限'
    }
  }
  if (cause instanceof SessionExpiredError) {
    return '登录状态已失效，请重新登录'
  }
  return toMessage(cause, '管理订单详情加载失败')
}

function getTransitionErrorMessage(error: Error): string {
  if (error instanceof BusinessError) {
    if (error.code === 40921) {
      return '订单状态已变化，详情已按服务端结果重新加载'
    }
    if (error.code === 40411) {
      return '订单不存在'
    }
    if (error.statusCode === 403) {
      return '当前账号没有该操作权限'
    }
  }
  if (error instanceof SessionExpiredError) {
    return '登录状态已失效，请重新登录'
  }
  return error.message || '订单状态更新失败'
}

function toMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}
