import { useCallback, useRef, useState } from 'react'

import {
  ApiClientError,
  BusinessError,
  SessionExpiredError,
} from '@/api'
import type {
  DeletedProductResult,
  OptionImageResult,
  ProductImageResult,
  ProductImageUpdateRequest,
  ProductImageUpdateResult,
  ProductStatusResult,
} from '@/api/endpoints/admin_products'

import { getDefaultAdminProductApi } from './runtime'
import { isAdminProductMutationUnknownError } from './use_admin_product_mutation'

export const MAX_PRODUCT_IMAGE_BYTES = 2 * 1024 * 1024

export type AdminProductLifecycleAction =
  | 'upload_product_image'
  | 'upload_option_image'
  | 'update_image'
  | 'delete_image'
  | 'online'
  | 'offline'

export interface AdminProductImageFile {
  readonly filePath: string
  readonly size: number
  readonly mediaType?: string
}

export type AdminProductLifecycleResult =
  | { readonly action: 'upload_product_image'; readonly image: ProductImageResult }
  | { readonly action: 'upload_option_image'; readonly image: OptionImageResult }
  | { readonly action: 'update_image'; readonly image: ProductImageUpdateResult }
  | { readonly action: 'delete_image'; readonly image: DeletedProductResult }
  | { readonly action: 'online' | 'offline'; readonly product: ProductStatusResult }

export type AdminProductLifecycleState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly action: AdminProductLifecycleAction }
  | {
      readonly status: 'failed'
      readonly action: AdminProductLifecycleAction
      readonly errorMessage: string
      readonly readinessIssues?: readonly string[]
    }
  | { readonly status: 'unknown'; readonly action: AdminProductLifecycleAction; readonly errorMessage: string }
  | { readonly status: 'succeeded'; readonly result: AdminProductLifecycleResult }

export interface AdminProductLifecycleSource {
  uploadProductImage(
    productId: number,
    request: { readonly filePath: string; readonly isCover?: boolean; readonly sort?: number },
  ): Promise<ProductImageResult>
  uploadOptionImage(
    optionId: number,
    request: { readonly filePath: string; readonly sort?: number },
  ): Promise<OptionImageResult>
  updateProductImage(
    imageId: number,
    request: ProductImageUpdateRequest,
  ): Promise<ProductImageUpdateResult>
  deleteProductImage(imageId: number): Promise<DeletedProductResult>
  onlineProduct(productId: number): Promise<ProductStatusResult>
  offlineProduct(productId: number): Promise<ProductStatusResult>
}

export interface AdminProductLifecycleFeature {
  readonly state: AdminProductLifecycleState
  uploadProductImage(
    productId: number,
    file: AdminProductImageFile,
    isCover: boolean,
  ): Promise<AdminProductLifecycleResult | undefined>
  uploadOptionImage(
    optionId: number,
    file: AdminProductImageFile,
  ): Promise<AdminProductLifecycleResult | undefined>
  updateImage(
    imageId: number,
    request: ProductImageUpdateRequest,
  ): Promise<AdminProductLifecycleResult | undefined>
  deleteImage(imageId: number): Promise<AdminProductLifecycleResult | undefined>
  onlineProduct(productId: number): Promise<AdminProductLifecycleResult | undefined>
  offlineProduct(productId: number): Promise<AdminProductLifecycleResult | undefined>
  reset(): void
}

export function useAdminProductLifecycleMutation(
  source: AdminProductLifecycleSource = getDefaultAdminProductApi(),
): AdminProductLifecycleFeature {
  const [state, setState] = useState<AdminProductLifecycleState>({ status: 'idle' })
  const activeMutationRef = useRef<Promise<AdminProductLifecycleResult | undefined>>()

  const execute = useCallback((
    action: AdminProductLifecycleAction,
    operation: () => Promise<AdminProductLifecycleResult>,
  ): Promise<AdminProductLifecycleResult | undefined> => {
    if (activeMutationRef.current) return activeMutationRef.current
    const activeMutation = (async () => {
      setState({ status: 'submitting', action })
      try {
        const result = await operation()
        setState({ status: 'succeeded', result })
        return result
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('商品图片或状态操作失败')
        if (isAdminProductMutationUnknownError(error)) {
          setState({
            status: 'unknown',
            action,
            errorMessage: `${actionLabel(action)}结果可能未知，系统不会自动重试；请重新加载商品详情核对`,
          })
        } else {
          const failure = getAdminProductLifecycleFailure(error, action)
          setState({ status: 'failed', action, ...failure })
        }
        return undefined
      }
    })()
    activeMutationRef.current = activeMutation
    void activeMutation.finally(() => {
      if (activeMutationRef.current === activeMutation) activeMutationRef.current = undefined
    }).catch(() => undefined)
    return activeMutation
  }, [])

  const uploadProductImage = useCallback((
    productId: number,
    file: AdminProductImageFile,
    isCover: boolean,
  ) => execute('upload_product_image', async () => {
    assertClientImage(file)
    return {
      action: 'upload_product_image',
      image: await source.uploadProductImage(productId, { filePath: file.filePath, isCover }),
    }
  }), [execute, source])

  const uploadOptionImage = useCallback((optionId: number, file: AdminProductImageFile) => execute(
    'upload_option_image',
    async () => {
      assertClientImage(file)
      return {
        action: 'upload_option_image',
        image: await source.uploadOptionImage(optionId, { filePath: file.filePath }),
      }
    },
  ), [execute, source])

  const updateImage = useCallback((imageId: number, request: ProductImageUpdateRequest) => execute(
    'update_image',
    async () => ({ action: 'update_image', image: await source.updateProductImage(imageId, request) }),
  ), [execute, source])

  const deleteImage = useCallback((imageId: number) => execute(
    'delete_image',
    async () => ({ action: 'delete_image', image: await source.deleteProductImage(imageId) }),
  ), [execute, source])

  const onlineProduct = useCallback((productId: number) => execute(
    'online',
    async () => ({ action: 'online', product: await source.onlineProduct(productId) }),
  ), [execute, source])

  const offlineProduct = useCallback((productId: number) => execute(
    'offline',
    async () => ({ action: 'offline', product: await source.offlineProduct(productId) }),
  ), [execute, source])

  const reset = useCallback(() => {
    if (!activeMutationRef.current) setState({ status: 'idle' })
  }, [])

  return {
    state,
    uploadProductImage,
    uploadOptionImage,
    updateImage,
    deleteImage,
    onlineProduct,
    offlineProduct,
    reset,
  }
}

export function getAdminProductLifecycleFailure(
  error: Error,
  action: AdminProductLifecycleAction,
): { readonly errorMessage: string; readonly readinessIssues?: readonly string[] } {
  if (error instanceof ClientImageValidationError) return { errorMessage: error.message }
  if (error instanceof BusinessError) {
    if (error.code === 42201) {
      const readinessIssues = parseReadinessIssues(error.data)
      return {
        errorMessage: readinessIssues
          ? '商品尚未满足上架条件，请一次补齐以下项目'
          : '商品尚未满足上架条件，请重新加载详情核对',
        ...(readinessIssues ? { readinessIssues } : {}),
      }
    }
    if (error.code === 42221) return { errorMessage: invalidImageMessage(error.data) }
    if (error.code === 40021) return { errorMessage: 'Option 专属图片不能设置为商品封面' }
    if (error.code === 40401) return { errorMessage: '商品不存在，请返回管理商品列表核对' }
    if (error.code === 40402 || error.code === 40403) {
      return { errorMessage: 'Option 或图片不存在，请重新加载详情' }
    }
    if (error.code === 40901) return { errorMessage: '商品已经上架，请重新加载详情' }
    if (error.code === 40902) return { errorMessage: '商品已经处于非销售状态，请重新加载详情' }
    if (error.code === 40903 || error.code === 40912) {
      return { errorMessage: '商品或 Option 已被逻辑删除，请重新加载详情' }
    }
    if (error.code === 40905) return { errorMessage: '已上架商品不能修改图片，请先下架' }
    if (error.code === 422) return { errorMessage: '图片排序或封面字段不符合要求，请检查后重试' }
    if (error.statusCode === 403) return { errorMessage: '当前账号没有管理商品的权限' }
  }
  if (error instanceof SessionExpiredError) return { errorMessage: '登录状态已失效，请重新登录' }
  if (error instanceof ApiClientError && error.message) return { errorMessage: error.message }
  return { errorMessage: `${actionLabel(action)}失败，请稍后重试` }
}

export function translateReadinessIssue(issue: string): string {
  const fixed: Readonly<Record<string, string>> = {
    'product name is required': '商品名称不能为空',
    'product description is required': '商品描述不能为空',
    'product cover image is required': '必须设置一张 Product 公共封面图',
    'at least one product image is required': '至少需要一张 Product 公共图片',
    'at least one experience option is required': '至少需要一个有效 Experience Option',
    'kit configuration is required': '缺少 Kit 配置',
    'kit price must be greater than 0 and no more than 99999': 'Kit 价格必须大于 0 且不超过 99999',
    'kit stock must be non-negative': 'Kit 库存不能为负数',
  }
  if (fixed[issue]) return `${fixed[issue]}（${issue}）`
  const optionPrice = /^option (\d+) price must be greater than 0$/.exec(issue)
  if (optionPrice) return `Option #${optionPrice[1]} 价格必须大于 0（${issue}）`
  const optionImage = /^option (\d+) has no image$/.exec(issue)
  if (optionImage) return `Option #${optionImage[1]} 至少需要一张专属图片（${issue}）`
  return issue
}

function parseReadinessIssues(data: unknown): readonly string[] | undefined {
  if (typeof data !== 'object' || data === null || Array.isArray(data) || !('issues' in data) ||
    !Array.isArray(data.issues) || data.issues.length === 0 ||
    data.issues.some((issue) => typeof issue !== 'string' || issue.length === 0)) return undefined
  return data.issues as string[]
}

function invalidImageMessage(data: unknown): string {
  const reason = typeof data === 'object' && data !== null && !Array.isArray(data) && 'reason' in data
    ? data.reason
    : undefined
  if (reason === 'unsupported_media_type') return '仅支持 jpg、png 或 webp 图片'
  if (reason === 'empty_file') return '不能上传空文件'
  if (reason === 'file_too_large') return '图片不能超过 2 MiB'
  if (reason === 'invalid_image_content') return '图片内容无效或已损坏'
  if (reason === 'content_type_mismatch') return '图片内容与文件类型不一致'
  return '图片文件无效，请重新选择'
}

function assertClientImage(file: AdminProductImageFile): void {
  if (!file.filePath) throw new ClientImageValidationError('请选择要上传的图片')
  if (file.size > MAX_PRODUCT_IMAGE_BYTES) {
    throw new ClientImageValidationError('图片不能超过 2 MiB')
  }
  if (file.mediaType && !['image/jpeg', 'image/jpg', 'image/png', 'image/webp'].includes(file.mediaType)) {
    throw new ClientImageValidationError('仅支持 jpg、png 或 webp 图片')
  }
}

function actionLabel(action: AdminProductLifecycleAction): string {
  if (action === 'upload_product_image' || action === 'upload_option_image') return '上传图片'
  if (action === 'update_image') return '修改图片'
  if (action === 'delete_image') return '删除图片'
  return action === 'online' ? '上架商品' : '下架商品'
}

class ClientImageValidationError extends Error {}
