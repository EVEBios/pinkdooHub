import { useCallback, useRef, useState } from 'react'

import {
  ApiClientError,
  BusinessError,
  ContractError,
  HttpError,
  NetworkError,
  RequestCancelledError,
  SessionExpiredError,
  TimeoutError,
} from '@/api'
import type {
  DeletedProductResult,
  ExperienceProductCreateRequest,
  ExperienceProductCreateResult,
  KitProductCreateRequest,
  KitProductCreateResult,
  ProductBasicInfoResult,
  ProductBasicInfoUpdateRequest,
} from '@/api/endpoints/admin_products'

import { getDefaultAdminProductApi } from './runtime'

export type AdminProductMutationAction =
  | 'create_experience'
  | 'create_kit'
  | 'update_basic_info'
  | 'delete'

export type AdminProductMutationResult =
  | { readonly action: 'create_experience'; readonly product: ExperienceProductCreateResult }
  | { readonly action: 'create_kit'; readonly product: KitProductCreateResult }
  | { readonly action: 'update_basic_info'; readonly product: ProductBasicInfoResult }
  | { readonly action: 'delete'; readonly product: DeletedProductResult }

export type AdminProductMutationState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly action: AdminProductMutationAction }
  | { readonly status: 'failed'; readonly action: AdminProductMutationAction; readonly errorMessage: string }
  | { readonly status: 'unknown'; readonly action: AdminProductMutationAction; readonly errorMessage: string }
  | { readonly status: 'succeeded'; readonly result: AdminProductMutationResult }

export interface AdminProductMutationSource {
  createExperienceProduct(
    request: ExperienceProductCreateRequest,
  ): Promise<ExperienceProductCreateResult>
  createKitProduct(request: KitProductCreateRequest): Promise<KitProductCreateResult>
  updateProductBasicInfo(
    productId: number,
    request: ProductBasicInfoUpdateRequest,
  ): Promise<ProductBasicInfoResult>
  deleteProduct(productId: number): Promise<DeletedProductResult>
}

export interface AdminProductMutationFeature {
  readonly state: AdminProductMutationState
  createExperience(
    request: ExperienceProductCreateRequest,
  ): Promise<AdminProductMutationResult | undefined>
  createKit(request: KitProductCreateRequest): Promise<AdminProductMutationResult | undefined>
  updateBasicInfo(
    productId: number,
    request: ProductBasicInfoUpdateRequest,
  ): Promise<AdminProductMutationResult | undefined>
  deleteProduct(productId: number): Promise<AdminProductMutationResult | undefined>
  reset(): void
}

export function useAdminProductMutation(
  source: AdminProductMutationSource = getDefaultAdminProductApi(),
): AdminProductMutationFeature {
  const [state, setState] = useState<AdminProductMutationState>({ status: 'idle' })
  const activeMutationRef = useRef<Promise<AdminProductMutationResult | undefined>>()

  const execute = useCallback((
    action: AdminProductMutationAction,
    operation: () => Promise<AdminProductMutationResult>,
  ): Promise<AdminProductMutationResult | undefined> => {
    if (activeMutationRef.current) return activeMutationRef.current

    const activeMutation = (async () => {
      setState({ status: 'submitting', action })
      try {
        const result = await operation()
        setState({ status: 'succeeded', result })
        return result
      } catch (cause) {
        const error = toError(cause)
        setState(isAdminProductMutationUnknownError(error)
          ? {
              status: 'unknown',
              action,
              errorMessage: `${getActionLabel(action)}结果可能未知，系统不会自动重试，请返回列表或详情核对`,
            }
          : {
              status: 'failed',
              action,
              errorMessage: getAdminProductMutationErrorMessage(error, action),
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

  const createExperience = useCallback((request: ExperienceProductCreateRequest) => execute(
    'create_experience',
    async () => ({ action: 'create_experience', product: await source.createExperienceProduct(request) }),
  ), [execute, source])

  const createKit = useCallback((request: KitProductCreateRequest) => execute(
    'create_kit',
    async () => ({ action: 'create_kit', product: await source.createKitProduct(request) }),
  ), [execute, source])

  const updateBasicInfo = useCallback((
    productId: number,
    request: ProductBasicInfoUpdateRequest,
  ) => execute(
    'update_basic_info',
    async () => ({
      action: 'update_basic_info',
      product: await source.updateProductBasicInfo(productId, request),
    }),
  ), [execute, source])

  const deleteProduct = useCallback((productId: number) => execute(
    'delete',
    async () => ({ action: 'delete', product: await source.deleteProduct(productId) }),
  ), [execute, source])

  const reset = useCallback(() => {
    if (!activeMutationRef.current) setState({ status: 'idle' })
  }, [])

  return { state, createExperience, createKit, updateBasicInfo, deleteProduct, reset }
}

export function isAdminProductMutationUnknownError(error: Error): boolean {
  return error instanceof NetworkError ||
    error instanceof TimeoutError ||
    error instanceof RequestCancelledError ||
    error instanceof ContractError ||
    (error instanceof HttpError && (error.statusCode ?? 0) >= 500)
}

export function getAdminProductMutationErrorMessage(
  error: Error,
  action: AdminProductMutationAction,
): string {
  if (error instanceof BusinessError) {
    if (error.code === 40401) return '商品不存在，请返回管理商品列表核对'
    if (error.code === 40903) return '商品已被逻辑删除，请重新加载详情'
    if (error.code === 40904) return '已上架商品必须先下架才能删除'
    if (error.code === 40905) return '已上架商品不能修改，请先下架'
    if (error.code === 422) return '提交内容不符合商品字段要求，请检查后重试'
    if (error.statusCode === 403) return '当前账号没有管理商品的权限'
  }
  if (error instanceof SessionExpiredError) return '登录状态已失效，请重新登录'
  if (error instanceof ApiClientError && error.message) return error.message
  return `${getActionLabel(action)}失败，请稍后重试`
}

function getActionLabel(action: AdminProductMutationAction): string {
  if (action === 'create_experience' || action === 'create_kit') return '创建商品'
  if (action === 'update_basic_info') return '编辑商品'
  return '删除商品'
}

function toError(cause: unknown): Error {
  return cause instanceof Error ? cause : new Error('管理商品写操作失败')
}
