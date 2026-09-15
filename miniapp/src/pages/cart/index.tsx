import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import { isAdminRole, useAuth } from '@/auth'
import {
  cartItemKey,
  type CartItem,
  type ColorKitCartItem,
  useCart,
} from '@/features/order'
import { BeadColorSwatch } from '@/components/bead_color_swatch'
import { AdminWorkbenchRedirect } from '@/navigation/admin_workbench_redirect'
import { formatPrice } from '@/utils/format'

import './index.scss'

type CartMutationRunner = (item: CartItem, mutation: () => Promise<void>) => Promise<void>

type CartDisplayEntry =
  | { readonly kind: 'item'; readonly item: CartItem }
  | { readonly kind: 'color-kit'; readonly items: readonly ColorKitCartItem[] }

export default function CartPage() {
  const auth = useAuth()

  if (auth.status === 'initializing') {
    return <CartState title='正在确认账户身份…' description='确认后将恢复当前设备的购物车' />
  }
  if (auth.status === 'error') {
    return (
      <CartState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='cart-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </CartState>
    )
  }
  if (auth.status === 'authenticated') {
    if (!auth.user) {
      return (
        <CartState title='账户信息不完整' description='请重新检查登录状态后再打开购物车'>
          <Button className='cart-state__action' onClick={auth.retryInitialization}>重新检查</Button>
        </CartState>
      )
    }
    if (isAdminRole(auth.user.role)) {
      return <AdminWorkbenchRedirect />
    }
    if (auth.user.role !== 'user') {
      return (
        <CartState title='账户角色暂不支持' description='请重新检查登录状态后再打开购物车'>
          <Button className='cart-state__action' onClick={auth.retryInitialization}>重新检查</Button>
        </CartState>
      )
    }
  }

  return <CustomerCartPage />
}

function CustomerCartPage() {
  const cart = useCart()
  const [busyKey, setBusyKey] = useState<string>()

  if (cart.status === 'initializing') {
    return <CartState title='正在恢复购物车…' description='购物车保存在当前设备本地' />
  }
  if (cart.status === 'error') {
    return (
      <CartState title='购物车恢复失败' description={cart.initializationError?.message ?? '请稍后重试'}>
        <Button className='cart-state__action' onClick={cart.retryInitialization}>重新加载</Button>
      </CartState>
    )
  }
  if (cart.items.length === 0) {
    return (
      <CartState title='购物车还是空的' description='选择一个真实的体验配置，或者加入一个材料包'>
        <Button className='cart-state__action' onClick={() => void Taro.switchTab({ url: '/pages/index/index' })}>
          去看看商品
        </Button>
      </CartState>
    )
  }

  const runMutation: CartMutationRunner = async (item, mutation) => {
    const key = cartItemKey(item)
    if (busyKey) {
      return
    }
    setBusyKey(key)
    try {
      await mutation()
    } catch (cause) {
      await Taro.showToast({
        title: cause instanceof Error ? cause.message : '购物车更新失败',
        icon: 'none',
      })
    } finally {
      setBusyKey(undefined)
    }
  }

  return (
    <View className='cart-page'>
      <View className='cart-page__header'>
        <Text className='cart-page__title'>购物清单</Text>
        <Text className='cart-page__subtitle'>{cart.items.length} 项待确认，数量与价格将在订单创建时重新校验。</Text>
      </View>
      <View className='cart-page__notice'>
        <Text>购物车价格仅供预览；创建订单时后端会重新校验商品、配置、库存和金额。</Text>
      </View>
      <View className='cart-list'>
        {groupCartItems(cart.items).map((entry) => entry.kind === 'color-kit'
          ? (
            <ColorKitCartGroup
              busyKey={busyKey}
              items={entry.items}
              key={`color-kit:${entry.items[0].productId}`}
              onRemove={(item) => runMutation(item, () => cart.removeItem(item))}
              onUpdateQuantity={(item, quantity) => (
                runMutation(item, () => cart.updateQuantity(item, quantity))
              )}
            />
          )
          : (
            <StandardCartItem
              busy={busyKey === cartItemKey(entry.item)}
              item={entry.item}
              key={cartItemKey(entry.item)}
              runMutation={runMutation}
              updateQuantity={(quantity) => cart.updateQuantity(entry.item, quantity)}
              remove={() => cart.removeItem(entry.item)}
            />
          ))}
      </View>
      <View className='cart-page__next-step'>
        <Text>本地价格仅供预览；订单确认页不会把名称、配置或价格发送给后端。</Text>
        <Button
          className='cart-page__checkout'
          onClick={() => void Taro.navigateTo({ url: '/pages/order-confirm/index' })}
        >
          去确认订单
        </Button>
      </View>
    </View>
  )
}

function StandardCartItem({
  busy,
  item,
  remove,
  runMutation,
  updateQuantity,
}: {
  readonly busy: boolean
  readonly item: CartItem
  readonly remove: () => Promise<void>
  readonly runMutation: CartMutationRunner
  readonly updateQuantity: (quantity: number) => Promise<void>
}) {
  return (
    <View className='cart-item'>
      <View className='cart-item__content'>
        <Text className='cart-item__type'>{item.productType === 'experience' ? '拼豆体验' : '拼豆套装'}</Text>
        <Text className='cart-item__name'>{item.productName}</Text>
        {item.configurationLabel && (
          <Text className='cart-item__configuration'>{item.configurationLabel}</Text>
        )}
        <Text className='cart-item__price'>预览单价 ¥{formatPrice(item.unitPrice)}</Text>
      </View>
      <View className='cart-item__controls'>
        <Button
          className='cart-item__quantity-button'
          disabled={busy || item.quantity <= 1}
          onClick={() => void runMutation(item, () => updateQuantity(item.quantity - 1))}
        >−</Button>
        <Text className='cart-item__quantity'>{item.quantity}</Text>
        <Button
          className='cart-item__quantity-button'
          disabled={busy || item.quantity >= 99}
          onClick={() => void runMutation(item, () => updateQuantity(item.quantity + 1))}
        >+</Button>
        <Button
          className='cart-item__remove'
          disabled={busy}
          onClick={() => void runMutation(item, remove)}
        >移除</Button>
      </View>
    </View>
  )
}

function ColorKitCartGroup({
  busyKey,
  items,
  onRemove,
  onUpdateQuantity,
}: {
  readonly busyKey?: string
  readonly items: readonly ColorKitCartItem[]
  readonly onRemove: (item: ColorKitCartItem) => Promise<void>
  readonly onUpdateQuantity: (item: ColorKitCartItem, quantity: number) => Promise<void>
}) {
  const firstItem = items[0]
  const totalWeight = items.reduce(
    (sum, item) => sum + item.quantity * item.saleUnitGrams,
    0,
  )
  return (
    <View className='cart-item cart-color-group'>
      <View className='cart-item__content'>
        <Text className='cart-item__type'>拼豆套装</Text>
        <Text className='cart-item__name'>{firstItem.productName}</Text>
        <Text className='cart-color-group__summary'>{items.length} 种颜色 · 共 {totalWeight}g</Text>
        <Text className='cart-item__price'>
          预览单价 ¥{formatPrice(firstItem.unitPrice)} / {firstItem.saleUnitGrams}g
        </Text>
      </View>
      <View className='cart-color-group__list'>
        {items.map((item) => {
          const busy = busyKey === cartItemKey(item)
          return (
            <View className='cart-color-row' key={cartItemKey(item)}>
              <View className='cart-color-row__identity'>
                <CartColorSwatch item={item} />
                <View className='cart-color-row__copy'>
                  <Text className='cart-color-row__label'>{item.configurationLabel}</Text>
                  <Text className='cart-color-row__weight'>
                    {item.quantity * item.saleUnitGrams}g
                  </Text>
                </View>
              </View>
              <View className='cart-color-row__actions'>
                <View className='cart-color-row__stepper'>
                  <Button
                    className='cart-color-row__step'
                    disabled={busy || item.quantity <= 1}
                    onClick={() => void onUpdateQuantity(item, item.quantity - 1)}
                  >−</Button>
                  <Text className='cart-color-row__current'>
                    {item.quantity * item.saleUnitGrams}g
                  </Text>
                  <Button
                    className='cart-color-row__step'
                    disabled={busy || item.quantity >= 99}
                    onClick={() => void onUpdateQuantity(item, item.quantity + 1)}
                  >+</Button>
                </View>
                <Button
                  className='cart-color-row__remove'
                  disabled={busy}
                  onClick={() => void onRemove(item)}
                >移除</Button>
              </View>
            </View>
          )
        })}
      </View>
    </View>
  )
}

function CartColorSwatch({ item }: { readonly item: ColorKitCartItem }) {
  return (
    <BeadColorSwatch
      className='cart-color-row__swatch'
      emptyClassName='cart-color-row__swatch--empty'
      emptyLabel='无色样'
      swatchHex={item.swatchHex}
      swatchImageUrl={item.imageUrl}
    />
  )
}

function groupCartItems(items: readonly CartItem[]): readonly CartDisplayEntry[] {
  const colorItemsByProduct = new Map<number, ColorKitCartItem[]>()
  items.forEach((item) => {
    if (!isColorKitCartItem(item)) {
      return
    }
    const group = colorItemsByProduct.get(item.productId) ?? []
    group.push(item)
    colorItemsByProduct.set(item.productId, group)
  })

  const emittedColorProducts = new Set<number>()
  return items.flatMap((item): CartDisplayEntry[] => {
    if (!isColorKitCartItem(item)) {
      return [{ kind: 'item', item }]
    }
    if (emittedColorProducts.has(item.productId)) {
      return []
    }
    emittedColorProducts.add(item.productId)
    return [{ kind: 'color-kit', items: colorItemsByProduct.get(item.productId) ?? [item] }]
  })
}

function isColorKitCartItem(item: CartItem): item is ColorKitCartItem {
  return item.productType === 'kit' && item.kitKind === 'color_selectable'
}

function CartState({
  children,
  description,
  title,
}: {
  title: string
  description: string
  children?: React.ReactNode
}) {
  return (
    <View className='cart-page cart-page--state'>
      <Text className='cart-state__title'>{title}</Text>
      <Text className='cart-state__description'>{description}</Text>
      {children}
    </View>
  )
}
