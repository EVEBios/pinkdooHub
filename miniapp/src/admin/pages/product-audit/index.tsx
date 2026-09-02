import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'

import type { AuditLogItem } from '@/api/endpoints/audit'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  parseProductAuditRoute,
  useProductAuditList,
} from '@/features/audit'
import {
  ADMIN_PRODUCT_LIST_PATH,
  buildAdminProductDetailUrl,
} from '@/features/product'

import './index.scss'

const ACTION_LABELS: Readonly<Record<string, string>> = {
  CREATE_PRODUCT: '创建商品',
  UPDATE_PRODUCT: '修改基本信息',
  DELETE_PRODUCT: '逻辑删除商品',
  ONLINE_PRODUCT: '上架商品',
  OFFLINE_PRODUCT: '下架商品',
  CREATE_EXPERIENCE_OPTION: '创建体验配置',
  UPDATE_EXPERIENCE_OPTION: '修改体验配置',
  DELETE_EXPERIENCE_OPTION: '删除体验配置',
  UPDATE_KIT_PRICE: '修改材料套装价格',
  UPLOAD_PRODUCT_IMAGE: '上传商品图片',
  UPDATE_PRODUCT_IMAGE: '修改商品图片',
  DELETE_PRODUCT_IMAGE: '删除商品图片',
  UPLOAD_OPTION_IMAGE: '上传配置图片',
  UPDATE_OPTION_IMAGE: '修改配置图片',
  DELETE_OPTION_IMAGE: '删除配置图片',
}

export default function ProductAuditPage() {
  const auth = useAuth()
  const route = parseProductAuditRoute(useRouter().params)
  if (!route) {
    return <AuditState title='操作历史地址无效' description='请从管理商品详情重新进入' />
  }
  if (auth.status === 'initializing') {
    return <AuditState title='正在确认管理员身份…' description='商品操作历史仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <AuditState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='product-audit-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </AuditState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <AuditState title='登录后查看操作历史' description='登录后返回管理商品列表，再进入商品详情与操作历史'>
        <Button
          className='product-audit-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_PRODUCT_LIST_PATH) })}
        >去登录</Button>
      </AuditState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <AuditState title='无管理权限' description='当前账号不会请求商品审计 API' />
  }
  return <AuthenticatedProductAudit {...route} />
}

export function AuthenticatedProductAudit({ productId, productType }: {
  readonly productId: number
  readonly productType: 'experience' | 'kit'
}) {
  const { loadNextPage, retry, state } = useProductAuditList(productId)
  const detailUrl = buildAdminProductDetailUrl(productId, productType)
  return (
    <View className='product-audit-page'>
      <View className='product-audit-page__header'>
        <Text className='product-audit-page__eyebrow'>PRODUCT AUDIT</Text>
        <Text className='product-audit-page__title'>商品 #{productId} 操作历史</Text>
        <Text className='product-audit-page__subtitle'>只读记录，按发生时间倒序展示</Text>
      </View>

      {state.status === 'loading' && <AuditState title='正在加载操作历史…' description='正在读取服务端审计记录' />}
      {state.status === 'empty' && <AuditState title='暂无操作历史' description='该商品目前没有可展示的审计记录' />}
      {state.status === 'error' && (
        <AuditState title='操作历史加载失败' description={state.errorMessage}>
          <Button className='product-audit-state__action' onClick={retry}>重新加载</Button>
        </AuditState>
      )}
      {state.status === 'content' && (
        <View className='product-audit-list'>
          <View className='product-audit-list__summary'>
            <Text>已加载 {state.items.length} 条</Text>
            <Text>共 {state.total} 条</Text>
          </View>
          {state.items.map((item) => <AuditCard key={item.id} item={item} />)}
          {state.errorMessage && <Text className='product-audit-list__error'>{state.errorMessage}</Text>}
          {state.page < state.pages ? (
            <Button disabled={state.loadingMore} onClick={loadNextPage}>
              {state.loadingMore ? '正在加载…' : state.errorMessage ? '重试加载更多' : '加载更多'}
            </Button>
          ) : <Text className='product-audit-list__end'>已经到底了</Text>}
        </View>
      )}
      <Button className='product-audit-page__back' onClick={() => void Taro.redirectTo({ url: detailUrl })}>
        返回商品详情
      </Button>
    </View>
  )
}

function AuditCard({ item }: { readonly item: AuditLogItem }) {
  return (
    <View className='product-audit-card'>
      <View className='product-audit-card__heading'>
        <Text className='product-audit-card__action'>{ACTION_LABELS[item.action] ?? item.action}</Text>
        <Text className='product-audit-card__id'>#{item.id}</Text>
      </View>
      <Text className='product-audit-card__operator'>操作人 ID：{item.operator_id}</Text>
      <Text className='product-audit-card__time'>UTC 时间：{item.created_at}</Text>
      <Text className='product-audit-card__ip'>来源 IP：{item.ip_address}</Text>
      {item.description && <Text className='product-audit-card__description'>说明：{item.description}</Text>}
    </View>
  )
}

function AuditState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='product-audit-state'>
      <Text className='product-audit-state__title'>{title}</Text>
      <Text className='product-audit-state__description'>{description}</Text>
      {children}
    </View>
  )
}
