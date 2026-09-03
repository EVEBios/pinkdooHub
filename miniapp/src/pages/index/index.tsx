import { Button, Image, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import type { ProductListItem } from '@/api/endpoints/products'
import {
  ADMIN_ORDER_LIST_PATH,
  ADMIN_INVENTORY_LIST_PATH,
  ADMIN_PRODUCT_LIST_PATH,
  ADMIN_USER_LIST_PATH,
  useAuth,
} from '@/auth'
import { type ProductTypeFilter, useProductList } from '@/features/product/use_product_list'
import { buildProductDetailUrl } from '@/features/product/product_detail_route'
import { resolveAssetUrl } from '@/utils/asset_url'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function ProductListPage() {
  const { logout, status, user } = useAuth()
  const {
    keyword,
    loadNextPage,
    productType,
    retry,
    setKeyword,
    setProductType,
    state,
  } = useProductList()
  const [logoutError, setLogoutError] = useState('')

  async function handleLogout(): Promise<void> {
    setLogoutError('')
    try {
      await logout()
    } catch {
      setLogoutError('服务端登出未确认，本机会话已清除')
    }
  }

  return (
    <View className='product-page'>
      <View className='product-page__header'>
        <View className='product-page__header-inner'>
          <Text className='product-page__brand'>pinkdooHub</Text>
          <View className='product-page__intro'>
            <Text className='product-page__title'>发现下一幅拼豆作品</Text>
            <Text className='product-page__subtitle'>选一场体验，或带一套材料回家。</Text>
          </View>
          <AccountActions
            onLogout={() => void handleLogout()}
            status={status}
            userNickname={user?.nickname}
            userRole={user?.role}
          />
          {logoutError && <Text className='product-page__account-error'>{logoutError}</Text>}
        </View>
      </View>

      <View className='product-page__content'>
        <ProductFilters
          keyword={keyword}
          productType={productType}
          onKeywordChange={setKeyword}
          onProductTypeChange={setProductType}
        />

        {state.status === 'loading' && (
          <PageState title='正在加载商品…' description='正在向 FastAPI 请求第一页数据' />
        )}

        {state.status === 'empty' && (
          <PageState title='暂时没有可浏览的商品' description='只有已经上架且未删除的商品会显示在这里' />
        )}

        {state.status === 'error' && (
          <PageState title='商品加载失败' description={state.errorMessage ?? '请稍后重试'}>
            <Button className='product-page__state-action' onClick={retry}>重新加载</Button>
          </PageState>
        )}

        {state.status === 'content' && (
          <>
            <View className='product-page__summary'>
              <Text>本页 {state.items.length} 件</Text>
              <Text>全部 {state.total} 件</Text>
            </View>
            <View className='product-grid'>
              {state.items.map((product) => (
                <ProductCard key={product.id} product={product} />
              ))}
            </View>
            {state.errorMessage && (
              <Text className='product-page__pagination-error'>{state.errorMessage}</Text>
            )}
            {state.page < state.pages ? (
              <Button
                className='product-page__load-more'
                disabled={state.loadingMore}
                onClick={loadNextPage}
              >
                {state.loadingMore ? '正在加载…' : state.errorMessage ? '重试加载更多' : '加载更多'}
              </Button>
            ) : (
              <Text className='product-page__end'>已经到底了</Text>
            )}
          </>
        )}
      </View>
    </View>
  )
}

interface ProductFiltersProps {
  productType: ProductTypeFilter
  keyword: string
  onProductTypeChange(productType: ProductTypeFilter): void
  onKeywordChange(keyword: string): void
}

const PRODUCT_TYPE_FILTERS: ReadonlyArray<{ value: ProductTypeFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'experience', label: '拼豆体验' },
  { value: 'kit', label: '材料套装' },
]

function ProductFilters({ keyword, onKeywordChange, onProductTypeChange, productType }: ProductFiltersProps) {
  return (
    <View className='product-filters'>
      <Input
        className='product-filters__search'
        maxlength={100}
        placeholder='搜索商品名称'
        placeholderClass='product-filters__search-placeholder'
        value={keyword}
        onInput={(event) => onKeywordChange(event.detail.value)}
      />
      <View className='product-filters__types'>
        {PRODUCT_TYPE_FILTERS.map((filter) => (
          <Button
            key={filter.value}
            className={`product-filters__type${productType === filter.value ? ' product-filters__type--active' : ''}`}
            onClick={() => onProductTypeChange(filter.value)}
          >
            {filter.label}
          </Button>
        ))}
      </View>
    </View>
  )
}

interface AccountActionsProps {
  status: ReturnType<typeof useAuth>['status']
  userNickname?: string
  userRole?: string
  onLogout(): void
}

function AccountActions({ onLogout, status, userNickname, userRole }: AccountActionsProps) {
  if (status === 'authenticated' && userNickname) {
    const isAdmin = userRole === 'admin' || userRole === 'super_admin'
    const adminActions = [
      { label: '库存流水', url: ADMIN_INVENTORY_LIST_PATH },
      { label: '管理商品', url: ADMIN_PRODUCT_LIST_PATH },
      { label: '管理订单', url: ADMIN_ORDER_LIST_PATH },
      { label: '管理用户', url: ADMIN_USER_LIST_PATH },
    ] as const

    return (
      <View className='product-page__account'>
        <Text className='product-page__account-user'>你好，{userNickname}</Text>
        <View className='product-page__account-actions'>
          <View className='product-page__account-group'>
            <Text className='product-page__account-section'>我的</Text>
            <Button
              className='product-page__account-action'
              onClick={() => void Taro.navigateTo({ url: '/pages/orders/index' })}
            >
              <Text className='product-page__account-action-label'>我的订单</Text>
              <Text className='product-page__account-action-meta'>查看</Text>
            </Button>
          </View>
          {isAdmin && (
            <View className='product-page__account-group'>
              <Text className='product-page__account-section'>店铺管理</Text>
              {adminActions.map((action) => (
                <Button
                  key={action.url}
                  className='product-page__account-action'
                  onClick={() => void Taro.navigateTo({ url: action.url })}
                >
                  <Text className='product-page__account-action-label'>{action.label}</Text>
                  <Text className='product-page__account-action-meta'>管理</Text>
                </Button>
              ))}
            </View>
          )}
        </View>
        <Button className='product-page__account-logout' onClick={onLogout}>退出</Button>
      </View>
    )
  }
  if (status === 'initializing') {
    return <Text className='product-page__account-hint'>正在恢复登录状态…</Text>
  }
  return (
    <View className='product-page__account'>
      {status === 'error' && <Text className='product-page__account-hint'>登录状态暂不可用，不影响浏览</Text>}
      <Button
        className='product-page__account-login'
        onClick={() => void Taro.navigateTo({ url: '/pages/login/index' })}
      >
        登录
      </Button>
    </View>
  )
}

interface PageStateProps {
  title: string
  description: string
  children?: React.ReactNode
}

function PageState({ children, description, title }: PageStateProps) {
  return (
    <View className='product-page__state'>
      <Text className='product-page__state-title'>{title}</Text>
      <Text className='product-page__state-description'>{description}</Text>
      {children}
    </View>
  )
}

function ProductCard({ product }: { product: ProductListItem }) {
  const [imageFailed, setImageFailed] = useState(false)
  const experience = product.product_type.value === 'experience'

  return (
    <View
      className='product-card'
      onClick={() => void Taro.navigateTo({
        url: buildProductDetailUrl(product.id, product.product_type.value),
      })}
    >
      {imageFailed ? (
        <View className='product-card__image product-card__image--fallback'>
          <Text>图片暂不可用</Text>
        </View>
      ) : (
        <Image
          className='product-card__image'
          lazyLoad
          mode='aspectFill'
          src={resolveAssetUrl(product.cover_image)}
          onError={() => setImageFailed(true)}
        />
      )}
      <View className='product-card__body'>
        <Text className='product-card__type'>{product.product_type.label}</Text>
        <Text className='product-card__name'>{product.name}</Text>
        <Text className='product-card__price'>
          ¥{formatPrice(product.display_price)}{experience ? ' 起' : ''}
        </Text>
      </View>
    </View>
  )
}
