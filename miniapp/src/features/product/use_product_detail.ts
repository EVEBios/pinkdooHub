import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  ExperienceProductDetail,
  KitProductDetail,
  ProductDetail,
  ProductDetailRequest,
  ProductType,
} from '@/api/endpoints/products'

import { getDefaultProductApi } from './runtime'

export type ProductDetailState =
  | { status: 'loading' }
  | { status: 'error'; errorMessage: string }
  | { status: 'content'; detail: ProductDetail }

export interface ProductDetailSource {
  getExperienceProduct(request: ProductDetailRequest): Promise<ExperienceProductDetail>
  getKitProduct(request: ProductDetailRequest): Promise<KitProductDetail>
}

export interface ProductDetailFeature {
  state: ProductDetailState
  retry(): void
}

export function useProductDetail(
  productId: number,
  productType: ProductType,
  source: ProductDetailSource = getDefaultProductApi(),
): ProductDetailFeature {
  const [state, setState] = useState<ProductDetailState>({ status: 'loading' })
  const requestSequenceRef = useRef(0)
  const [retrySequence, setRetrySequence] = useState(0)

  useEffect(() => {
    const sequence = ++requestSequenceRef.current
    setState({ status: 'loading' })
    const request = { productId }
    const promise = productType === 'experience'
      ? source.getExperienceProduct(request)
      : source.getKitProduct(request)

    void promise.then((detail) => {
      if (sequence === requestSequenceRef.current) {
        setState({ status: 'content', detail })
      }
    }).catch((cause: unknown) => {
      if (sequence === requestSequenceRef.current) {
        setState({ status: 'error', errorMessage: getProductDetailErrorMessage(cause) })
      }
    })

    return () => {
      requestSequenceRef.current += 1
    }
  }, [productId, productType, retrySequence, source])

  const retry = useCallback(() => {
    setRetrySequence((current) => current + 1)
  }, [])

  return { state, retry }
}

function getProductDetailErrorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : '商品详情加载失败，请稍后重试'
}
