import { Button, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useMemo, useState } from 'react'

import { buildLoginUrl, useAuth, WALLET_RECHARGE_PATH } from '@/auth'
import { moneyToCents, normalizeMoneyDraft, useMemberWallet, useRecharge } from '@/features/wallet'
import { formatPrice } from '@/utils/format'

import './index.scss'

// Provider 能力开放后仍需接入并验证 Taro.requestPayment 才能解除客户端门禁。
const WECHAT_CLIENT_PAYMENT_READY = false

export default function WalletRechargePage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <RechargeState title='正在确认会员身份…' description='充值仅对本人会员账户开放' />
  }
  if (auth.status === 'error') {
    return (
      <RechargeState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='recharge-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </RechargeState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <RechargeState title='登录后充值' description='登录成功后会回到这里'>
        <Button
          className='recharge-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(WALLET_RECHARGE_PATH) })}
        >去登录</Button>
      </RechargeState>
    )
  }
  return <AuthenticatedRecharge />
}

export function AuthenticatedRecharge() {
  const member = useMemberWallet()
  const recharge = useRecharge()
  const [draft, setDraft] = useState('')
  const normalized = useMemo(() => normalizeMoneyDraft(draft), [draft])

  if (member.state.status === 'loading') {
    return <RechargeState title='正在读取余额…' description='将同时核对账户上限与支付能力' />
  }
  if (member.state.status === 'error') {
    return (
      <RechargeState title='余额加载失败' description={member.state.errorMessage}>
        <Button className='recharge-state__action' onClick={member.retry}>重新加载</Button>
      </RechargeState>
    )
  }

  const { user, wallet } = member.state.member
  const amountCents = normalized ? moneyToCents(normalized) : undefined
  const balanceCents = moneyToCents(wallet.balance)
  const limitCents = moneyToCents(wallet.balance_limit)
  const amountValid = amountCents !== undefined && amountCents >= 100 && amountCents <= 100000
  const withinLimit = amountValid && balanceCents !== undefined && limitCents !== undefined &&
    balanceCents + amountCents <= limitCents
  const providerReady = wallet.capabilities.topup_enabled && WECHAT_CLIENT_PAYMENT_READY
  const accountReady = wallet.status === 'active' && user.status === 'normal'
  const canSubmit = providerReady && accountReady && withinLimit && recharge.state.status !== 'submitting'

  async function confirmRecharge(): Promise<void> {
    if (!canSubmit || !normalized) return
    const confirmation = await Taro.showModal({
      title: '确认充值金额',
      content: `本次充值 ¥${normalized}，完成后预计余额 ¥${formatPrice(((balanceCents! + amountCents!) / 100).toFixed(2))}。`,
      confirmText: '前往支付',
      confirmColor: '#a92e51',
    })
    if (confirmation.confirm) await recharge.submit(normalized)
  }

  const validationMessage = draft.length === 0
    ? '请输入固定两位小数金额'
    : !amountValid
      ? '单笔充值必须为 ¥1.00–¥1000.00'
      : !withinLimit
        ? `充值后不可超过余额上限 ¥${formatPrice(wallet.balance_limit)}`
        : undefined

  return (
    <View className='recharge-page'>
      <View className='recharge-page__header'>
        <Text className='recharge-page__eyebrow'>余额充值</Text>
        <Text className='recharge-page__title'>为下一次创作预存余额</Text>
        <Text className='recharge-page__subtitle'>当前余额 ¥{formatPrice(wallet.balance)} · 上限 ¥{formatPrice(wallet.balance_limit)}</Text>
      </View>
      <View className='recharge-form'>
        <Text className='recharge-form__label'>充值金额</Text>
        <View className='recharge-form__money'>
          <Text className='recharge-form__currency'>¥</Text>
          <Input
            className='recharge-form__input'
            maxlength={7}
            placeholder='1.00–1000.00'
            type='digit'
            value={draft}
            onInput={(event) => setDraft(event.detail.value)}
          />
        </View>
        {validationMessage && <Text className='recharge-form__validation'>{validationMessage}</Text>}
        {!accountReady && <Text className='recharge-form__warning'>当前账号或钱包不可主动充值。</Text>}
        {!providerReady && (
          <View className='recharge-provider'>
            <Text className='recharge-provider__status'>微信支付暂未开通</Text>
            <Text className='recharge-provider__detail'>商户号、小程序 AppID 关联、HTTPS 通知与客户端支付确认能力完成后开放；当前不会发起支付或生成成功结果。</Text>
          </View>
        )}
        {(recharge.state.status === 'failed' || recharge.state.status === 'unknown') && (
          <Text className='recharge-form__error'>{recharge.state.errorMessage}</Text>
        )}
        {recharge.state.status === 'succeeded' && <Text className='recharge-form__success'>充值请求已提交，请以资金明细为准。</Text>}
        <Button
          className='recharge-form__submit'
          disabled={!canSubmit}
          loading={recharge.state.status === 'submitting'}
          onClick={() => void confirmRecharge()}
        >{providerReady ? recharge.state.status === 'submitting' ? '正在提交…' : '确认充值' : '微信支付暂未开通'}</Button>
      </View>
      <Text className='recharge-page__footnote'>余额仅用于购买 pinkdooHub 自有商品与服务，不可提现或转账。</Text>
    </View>
  )
}

function RechargeState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='recharge-page recharge-page--state'>
      <Text className='recharge-state__title'>{title}</Text>
      <Text className='recharge-state__description'>{description}</Text>
      {children}
    </View>
  )
}
