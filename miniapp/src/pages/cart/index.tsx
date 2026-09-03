import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import { cartItemKey, type CartItem, useCart } from '@/features/order'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function CartPage() {
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
        <Button className='cart-state__action' onClick={() => void Taro.navigateTo({ url: '/pages/index/index' })}>
          去看看商品
        </Button>
      </CartState>
    )
  }

  const runMutation = async (item: CartItem, mutation: () => Promise<void>) => {
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
        {cart.items.map((item) => {
          const key = cartItemKey(item)
          const busy = busyKey === key
          return (
            <View className='cart-item' key={key}>
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
                  onClick={() => void runMutation(item, () => (
                    cart.updateQuantity(item.productId, item.experienceOptionId, item.quantity - 1)
                  ))}
                >−</Button>
                <Text className='cart-item__quantity'>{item.quantity}</Text>
                <Button
                  className='cart-item__quantity-button'
                  disabled={busy || item.quantity >= 99}
                  onClick={() => void runMutation(item, () => (
                    cart.updateQuantity(item.productId, item.experienceOptionId, item.quantity + 1)
                  ))}
                >+</Button>
                <Button
                  className='cart-item__remove'
                  disabled={busy}
                  onClick={() => void runMutation(item, () => (
                    cart.removeItem(item.productId, item.experienceOptionId)
                  ))}
                >移除</Button>
              </View>
            </View>
          )
        })}
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
