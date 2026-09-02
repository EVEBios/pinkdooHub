import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  AdminExperienceProductDetail,
  AdminKitProductDetail,
  AdminProductDetail,
  AdminProductType,
} from '@/api/endpoints/admin_products'

import { getDefaultAdminProductApi } from './runtime'

export type AdminProductDetailState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | { readonly status: 'content'; readonly product: AdminProductDetail }

export interface AdminProductDetailSource {
  getExperienceProduct(productId: number): Promise<AdminExperienceProductDetail>
  getKitProduct(productId: number): Promise<AdminKitProductDetail>
}

export interface AdminProductDetailFeature {
  readonly state: AdminProductDetailState
  retry(): void
}

export function useAdminProductDetail(
  productId: number,
  productType: AdminProductType,
  source: AdminProductDetailSource = getDefaultAdminProductApi(),
): AdminProductDetailFeature {
  const [state, setState] = useState<AdminProductDetailState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const requestSequenceRef = useRef(0)

  const retry = useCallback(() => setAttempt((current) => current + 1), [])

  useEffect(() => {
    const sequence = ++requestSequenceRef.current
    setState({ status: 'loading' })
    const request = productType === 'experience'
      ? source.getExperienceProduct(productId)
      : source.getKitProduct(productId)
    void request.then((product) => {
      if (sequence === requestSequenceRef.current) setState({ status: 'content', product })
    }).catch((cause: unknown) => {
      if (sequence === requestSequenceRef.current) {
        setState({
          status: 'error',
          errorMessage: cause instanceof Error && cause.message
            ? cause.message
            : '管理商品详情加载失败，请稍后重试',
        })
      }
    })
    return () => { requestSequenceRef.current += 1 }
  }, [attempt, productId, productType, source])

  return { state, retry }
}
