import { useCallback, useEffect, useRef, useState } from 'react'

import type { ProductListItem, ProductListPage, ProductListRequest } from '@/api/endpoints/products'

import { getDefaultProductApi } from './runtime'

const PRODUCT_LIST_PAGE_SIZE = 10
const PRODUCT_SEARCH_DEBOUNCE_MS = 300

export type ProductTypeFilter = 'all' | 'experience' | 'kit'

export type ProductListStatus = 'loading' | 'empty' | 'error' | 'content'

export interface ProductListState {
  status: ProductListStatus
  items: readonly ProductListItem[]
  total: number
  page: number
  pages: number
  loadingMore: boolean
  errorMessage?: string
}

export interface ProductListSource {
  listProducts(request?: ProductListRequest): Promise<ProductListPage>
}

export interface ProductListFeature {
  state: ProductListState
  productType: ProductTypeFilter
  keyword: string
  setProductType(productType: ProductTypeFilter): void
  setKeyword(keyword: string): void
  retry(): void
  loadNextPage(): void
}

const initialState: ProductListState = {
  status: 'loading',
  items: [],
  total: 0,
  page: 1,
  pages: 0,
  loadingMore: false,
}

export function useProductList(source: ProductListSource = getDefaultProductApi()): ProductListFeature {
  const [state, setState] = useState<ProductListState>(initialState)
  const [productType, setProductType] = useState<ProductTypeFilter>('all')
  const [keyword, setKeyword] = useState('')
  const [debouncedKeyword, setDebouncedKeyword] = useState('')
  const requestSequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)

  useEffect(() => {
    const normalizedKeyword = keyword.trim()
    if (normalizedKeyword !== debouncedKeyword) {
      const timer = setTimeout(() => {
        setDebouncedKeyword(normalizedKeyword)
      }, PRODUCT_SEARCH_DEBOUNCE_MS)
      return () => clearTimeout(timer)
    }
    return undefined
  }, [keyword, debouncedKeyword])

  const loadFirstPage = useCallback(() => {
    const sequence = ++requestSequenceRef.current
    loadingMoreRef.current = false
    setState(initialState)

    void source.listProducts({
      ...buildProductListFilters(productType, debouncedKeyword),
      page: 1,
      page_size: PRODUCT_LIST_PAGE_SIZE,
    }).then((page) => {
      if (sequence !== requestSequenceRef.current) {
        return
      }
      setState({
        status: page.items.length === 0 ? 'empty' : 'content',
        items: page.items,
        total: page.total,
        page: page.page,
        pages: page.pages,
        loadingMore: false,
      })
    }).catch((cause: unknown) => {
      if (sequence !== requestSequenceRef.current) {
        return
      }
      setState({
        ...initialState,
        status: 'error',
        errorMessage: getProductListErrorMessage(cause),
      })
    })
  }, [source, productType, debouncedKeyword])

  const loadNextPage = useCallback(() => {
    if (state.status !== 'content' || state.page >= state.pages || loadingMoreRef.current) {
      return
    }
    loadingMoreRef.current = true
    const sequence = ++requestSequenceRef.current
    setState((current) => ({ ...current, loadingMore: true, errorMessage: undefined }))

    void source.listProducts({
      ...buildProductListFilters(productType, debouncedKeyword),
      page: state.page + 1,
      page_size: PRODUCT_LIST_PAGE_SIZE,
    }).then((page) => {
      if (sequence !== requestSequenceRef.current) {
        return
      }
      setState((current) => ({
        status: 'content',
        items: [...current.items, ...page.items],
        total: page.total,
        page: page.page,
        pages: page.pages,
        loadingMore: false,
      }))
    }).catch((cause: unknown) => {
      if (sequence !== requestSequenceRef.current) {
        return
      }
      setState((current) => ({
        ...current,
        loadingMore: false,
        errorMessage: getProductListErrorMessage(cause),
      }))
    }).finally(() => {
      if (sequence === requestSequenceRef.current) {
        loadingMoreRef.current = false
      }
    })
  }, [source, state.page, state.pages, state.status, productType, debouncedKeyword])

  useEffect(() => {
    loadFirstPage()
    return () => {
      requestSequenceRef.current += 1
    }
  }, [loadFirstPage])

  return {
    state,
    productType,
    keyword,
    setProductType,
    setKeyword,
    retry: loadFirstPage,
    loadNextPage,
  }
}

function buildProductListFilters(
  productType: ProductTypeFilter,
  keyword: string,
): ProductListRequest {
  return {
    ...(productType === 'all' ? {} : { product_type: productType }),
    ...(keyword === '' ? {} : { keyword }),
  }
}

function getProductListErrorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : '商品加载失败，请稍后重试'
}
