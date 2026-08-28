import { useCallback, useRef, useState } from 'react'

import {
  ApiClientError,
  BusinessError,
  SessionExpiredError,
} from '@/api'
import type {
  DeletedExperienceOptionResult,
  ExperienceOptionCreateRequest,
  ExperienceOptionCreateResult,
  ExperienceOptionUpdateRequest,
  ExperienceOptionUpdateResult,
  KitPriceUpdateResult,
} from '@/api/endpoints/admin_products'

import { getDefaultAdminProductApi } from './runtime'
import { isAdminProductMutationUnknownError } from './use_admin_product_mutation'

export type AdminProductConfigurationAction =
  | 'create_option'
  | 'update_option'
  | 'delete_option'
  | 'update_kit_price'

export type AdminProductConfigurationResult =
  | { readonly action: 'create_option'; readonly option: ExperienceOptionCreateResult }
  | { readonly action: 'update_option'; readonly option: ExperienceOptionUpdateResult }
  | { readonly action: 'delete_option'; readonly option: DeletedExperienceOptionResult }
  | { readonly action: 'update_kit_price'; readonly kit: KitPriceUpdateResult }

export type AdminProductConfigurationState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly action: AdminProductConfigurationAction }
  | { readonly status: 'failed'; readonly action: AdminProductConfigurationAction; readonly errorMessage: string }
  | { readonly status: 'unknown'; readonly action: AdminProductConfigurationAction; readonly errorMessage: string }
  | { readonly status: 'succeeded'; readonly result: AdminProductConfigurationResult }

export interface AdminProductConfigurationSource {
  createExperienceOption(productId: number, request: ExperienceOptionCreateRequest): Promise<ExperienceOptionCreateResult>
  updateExperienceOption(optionId: number, request: ExperienceOptionUpdateRequest): Promise<ExperienceOptionUpdateResult>
  deleteExperienceOption(optionId: number): Promise<DeletedExperienceOptionResult>
  updateKitPrice(productId: number, request: { readonly price: string }): Promise<KitPriceUpdateResult>
}

export interface AdminProductConfigurationFeature {
  readonly state: AdminProductConfigurationState
  createOption(productId: number, request: ExperienceOptionCreateRequest): Promise<AdminProductConfigurationResult | undefined>
  updateOption(optionId: number, request: ExperienceOptionUpdateRequest): Promise<AdminProductConfigurationResult | undefined>
  deleteOption(optionId: number): Promise<AdminProductConfigurationResult | undefined>
  updateKitPrice(productId: number, price: string): Promise<AdminProductConfigurationResult | undefined>
  reset(): void
}

export function useAdminProductConfigurationMutation(
  source: AdminProductConfigurationSource = getDefaultAdminProductApi(),
): AdminProductConfigurationFeature {
  const [state, setState] = useState<AdminProductConfigurationState>({ status: 'idle' })
  const activeMutationRef = useRef<Promise<AdminProductConfigurationResult | undefined>>()

  const execute = useCallback((
    action: AdminProductConfigurationAction,
    operation: () => Promise<AdminProductConfigurationResult>,
  ): Promise<AdminProductConfigurationResult | undefined> => {
    if (activeMutationRef.current) return activeMutationRef.current
    const activeMutation = (async () => {
      setState({ status: 'submitting', action })
      try {
        const result = await operation()
        setState({ status: 'succeeded', result })
        return result
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('商品配置写操作失败')
        setState(isAdminProductMutationUnknownError(error)
          ? {
              status: 'unknown',
              action,
              errorMessage: `${actionLabel(action)}结果可能未知，系统不会自动重试；请重新加载商品详情核对`,
            }
          : {
              status: 'failed',
              action,
              errorMessage: getConfigurationErrorMessage(error, action),
            })
        return undefined
      }
    })()
    activeMutationRef.current = activeMutation
    void activeMutation.finally(() => {
      if (activeMutationRef.current === activeMutation) activeMutationRef.current = undefined
    }).catch(() => undefined)
    return activeMutation
  }, [])

  const createOption = useCallback((productId: number, request: ExperienceOptionCreateRequest) => execute(
    'create_option',
    async () => ({ action: 'create_option', option: await source.createExperienceOption(productId, request) }),
  ), [execute, source])
  const updateOption = useCallback((optionId: number, request: ExperienceOptionUpdateRequest) => execute(
    'update_option',
    async () => ({ action: 'update_option', option: await source.updateExperienceOption(optionId, request) }),
  ), [execute, source])
  const deleteOption = useCallback((optionId: number) => execute(
    'delete_option',
    async () => ({ action: 'delete_option', option: await source.deleteExperienceOption(optionId) }),
  ), [execute, source])
  const updateKitPrice = useCallback((productId: number, price: string) => execute(
    'update_kit_price',
    async () => ({ action: 'update_kit_price', kit: await source.updateKitPrice(productId, { price }) }),
  ), [execute, source])
  const reset = useCallback(() => {
    if (!activeMutationRef.current) setState({ status: 'idle' })
  }, [])

  return { state, createOption, updateOption, deleteOption, updateKitPrice, reset }
}

export function getConfigurationErrorMessage(
  error: Error,
  action: AdminProductConfigurationAction,
): string {
  if (error instanceof BusinessError) {
    if (error.code === 40001) return '商品类型不匹配，请从正确的管理详情重新进入'
    if (error.code === 40401 || error.code === 40402 || error.code === 40404) return '商品或配置不存在，请重新加载详情'
    if (error.code === 40903 || error.code === 40912) return '商品或 Option 已被逻辑删除，请重新加载详情'
    if (error.code === 40905) return '已上架商品不能修改，请先下架'
    if (error.code === 40911) return '相同时长、人数和日期类型的 Option 已存在'
    if (error.code === 422) return '提交内容不符合 Option 或价格字段要求，请检查后重试'
    if (error.statusCode === 403) return '当前账号没有管理商品的权限'
  }
  if (error instanceof SessionExpiredError) return '登录状态已失效，请重新登录'
  if (error instanceof ApiClientError && error.message) return error.message
  return `${actionLabel(action)}失败，请稍后重试`
}

function actionLabel(action: AdminProductConfigurationAction): string {
  if (action === 'create_option') return '新增或恢复 Option'
  if (action === 'update_option') return '修改 Option'
  if (action === 'delete_option') return '删除 Option'
  return '修改套装价格'
}
