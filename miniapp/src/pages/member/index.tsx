import { Button, Image, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import type { MemberWallet } from '@/api/endpoints/wallet'
import {
  buildLoginUrl,
  MEMBER_PATH,
  useAuth,
  WALLET_RECHARGE_PATH,
  WALLET_TRANSACTION_LIST_PATH,
} from '@/auth'
import { useMemberWallet } from '@/features/wallet'
import { resolveAssetUrl } from '@/utils/asset_url'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function MemberPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <MemberState title='正在确认会员身份…' description='余额与资金记录仅对本人可见' />
  }
  if (auth.status === 'error') {
    return (
      <MemberState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='member-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </MemberState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <MemberState title='登录后进入会员中心' description='登录成功后会回到这里'>
        <Button
          className='member-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(MEMBER_PATH) })}
        >去登录</Button>
      </MemberState>
    )
  }
  return <AuthenticatedMember />
}

export function AuthenticatedMember() {
  const { retry, state } = useMemberWallet()
  if (state.status === 'loading') {
    return <MemberState title='正在读取会员账户…' description='余额以服务端账本为准' />
  }
  if (state.status === 'error') {
    return (
      <MemberState title='会员账户加载失败' description={state.errorMessage}>
        <Button className='member-state__action' onClick={retry}>重新加载</Button>
      </MemberState>
    )
  }

  const { user, wallet } = state.member
  const walletActive = wallet.status === 'active' && user.status === 'normal'
  return (
    <View className='member-page'>
      <View className='member-page__header'>
        <Text className='member-page__eyebrow'>会员账户 · #{user.id}</Text>
        <Text className='member-page__title'>{user.nickname}</Text>
        <Text className='member-page__identity'>@{user.username} · {walletActive ? '会员账户正常' : '会员账户不可消费'}</Text>
      </View>

      <MemberProfile user={user} />

      <View className='member-balance'>
        <View className='member-balance__ribbon'>
          <Text className='member-balance__label'>可用余额</Text>
          <Text className='member-balance__amount'>¥{formatPrice(wallet.balance)}</Text>
        </View>
        <View className='member-balance__rule'>
          <Text>余额上限</Text>
          <Text>¥{formatPrice(wallet.balance_limit)}</Text>
        </View>
        <Text className='member-balance__note'>余额仅可购买 pinkdooHub 自有商品与服务，不可提现、转账或与其他方式混合支付。</Text>
      </View>

      <View className='member-actions'>
        <Button
          className='member-actions__primary'
          onClick={() => void Taro.navigateTo({ url: WALLET_TRANSACTION_LIST_PATH })}
        >查看资金明细</Button>
        <Button
          className='member-actions__secondary'
          onClick={() => void Taro.navigateTo({ url: WALLET_RECHARGE_PATH })}
        >{wallet.capabilities.topup_enabled && walletActive ? '余额充值' : '充值暂未开通'}</Button>
      </View>

      <View className='member-notice'>
        <Text className='member-notice__title'>充值能力准备中</Text>
        <Text className='member-notice__body'>单笔充值范围为 ¥1.00–¥1000.00，充值后余额不得超过 ¥1000.00。当前微信支付商户能力尚未就绪，页面不会生成虚假支付结果。</Text>
      </View>
    </View>
  )
}

function MemberProfile({ user }: { readonly user: MemberWallet['user'] }) {
  const [avatarFailed, setAvatarFailed] = useState(false)
  const avatarUrl = avatarFailed ? undefined : resolveMemberAvatar(user.avatar)
  return (
    <View className='member-profile'>
      <View className='member-profile__heading'>
        {avatarUrl ? (
          <Image
            className='member-profile__avatar'
            mode='aspectFill'
            src={avatarUrl}
            onError={() => setAvatarFailed(true)}
          />
        ) : (
          <View className='member-profile__avatar member-profile__avatar--fallback'>
            <Text>{user.nickname.slice(0, 1)}</Text>
          </View>
        )}
        <View>
          <Text className='member-profile__title'>个人资料</Text>
          <Text className='member-profile__hint'>会员信息来自当前登录账户</Text>
        </View>
      </View>
      <View className='member-profile__facts'>
        <Text>昵称</Text><Text>{user.nickname}</Text>
        <Text>账号</Text><Text>@{user.username}</Text>
        <Text>手机号</Text><Text>{user.phone ?? '未绑定手机号'}</Text>
        <Text>会员状态</Text><Text>{user.status === 'normal' ? '正常' : '不可用'}</Text>
        <Text>加入时间</Text><Text>{user.created_at}</Text>
      </View>
    </View>
  )
}

function resolveMemberAvatar(avatar: string | null): string | undefined {
  if (!avatar) return undefined
  try {
    return resolveAssetUrl(avatar)
  } catch {
    return undefined
  }
}

function MemberState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='member-page member-page--state'>
      <Text className='member-state__title'>{title}</Text>
      <Text className='member-state__description'>{description}</Text>
      {children}
    </View>
  )
}
