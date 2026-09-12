import { useCallback, useEffect, useRef, useState } from 'react'

import { BusinessError, SessionExpiredError } from '@/api'
import type { OrderDetail, OrderStatusResult } from '@/api/endpoints/orders'

import { getDefaultOrderApi } from './runtime'
import { isOrderCommandUnknownError } from './submission'

export type OrderDetailState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | { readonly status: 'content'; readonly order: OrderDetail }

export type OrderCancellationState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting' }
  | { readonly status: 'failed'; readonly errorMessage: string }
  | { readonly status: 'unknown'; readonly errorMessage: string }
  | {
      readonly status: 'succeeded'
      readonly result: OrderStatusResult
      readonly refreshErrorMessage?: string
    }

export interface OrderDetailSource {
  getOrderDetail(orderId: number): Promise<OrderDetail>
  cancelOrder(orderId: number): Promise<OrderStatusResult>
}

export interface OrderDetailFeature {
  readonly detail: OrderDetailState
  readonly cancellation: OrderCancellationState
  retry(): void
  cancel(): Promise<void>
}

export function useOrderDetail(
  orderId: number,
  source: OrderDetailSource = getDefaultOrderApi(),
): OrderDetailFeature {
  const [detail, setDetail] = useState<OrderDetailState>({ status: 'loading' })
  const [cancellation, setCancellation] = useState<OrderCancellationState>({ status: 'idle' })
  const requestSequenceRef = useRef(0)
  const activeCancellationRef = useRef<Promise<void>>()

  const load = useCallback(() => {
    const sequence = ++requestSequenceRef.current
    setDetail({ status: 'loading' })
    void source.getOrderDetail(orderId).then((order) => {
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

  const cancel = useCallback((): Promise<void> => {
    if (activeCancellationRef.current) {
      return activeCancellationRef.current
    }
    if (detail.status !== 'content' || detail.order.status.value !== 'pending') {
      return Promise.resolve()
    }
    const currentOrder = detail.order
    const operation = (async () => {
      setCancellation({ status: 'submitting' })
      try {
        const result = await source.cancelOrder(orderId)
        setDetail({
          status: 'content',
          order: { ...currentOrder, status: result.status, updated_at: result.updated_at },
        })
        setCancellation({ status: 'succeeded', result })
        try {
          const refreshed = await source.getOrderDetail(orderId)
          setDetail({ status: 'content', order: refreshed })
        } catch (cause) {
          setCancellation({
            status: 'succeeded',
            result,
            refreshErrorMessage: toMessage(cause, '订单已取消，但详情刷新失败'),
          })
        }
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('取消订单失败')
        setCancellation(isOrderCommandUnknownError(error)
          ? { status: 'unknown', errorMessage: '取消结果可能未知，请从我的订单重新核对' }
          : { status: 'failed', errorMessage: getCancelErrorMessage(error) })
        if (error instanceof BusinessError && error.code === 40921) {
          try {
            const refreshed = await source.getOrderDetail(orderId)
            setDetail({ status: 'content', order: refreshed })
          } catch {
            // 明确冲突仍保留原错误；用户可通过“重新加载”再次读取权威状态。
          }
        }
      }
    })()
    activeCancellationRef.current = operation
    void operation.finally(() => {
      if (activeCancellationRef.current === operation) {
        activeCancellationRef.current = undefined
      }
    }).catch(() => undefined)
    return operation
  }, [detail, orderId, source])

  return { detail, cancellation, retry: load, cancel }
}

function getDetailErrorMessage(cause: unknown): string {
  if (cause instanceof BusinessError && cause.code === 40411) {
    return '订单不存在或不可访问'
  }
  if (cause instanceof SessionExpiredError) {
    return '登录状态已失效，请重新登录'
  }
  return toMessage(cause, '订单详情加载失败')
}

function getCancelErrorMessage(error: Error): string {
  if (error instanceof BusinessError) {
    if (error.code === 40921) {
      return '订单当前状态不允许取消，请重新加载详情'
    }
    if (error.code === 40411) {
      return '订单不存在或不可访问'
    }
  }
  if (error instanceof SessionExpiredError) {
    return '登录状态已失效，请重新登录'
  }
  return error.message || '取消订单失败'
}

function toMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}
