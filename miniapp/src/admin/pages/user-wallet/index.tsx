import { Button, Input, Text, Textarea, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useMemo, useState } from 'react'

import type { WalletTransaction } from '@/api/endpoints/wallet'
import { ADMIN_USER_LIST_PATH, buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  getWalletTransactionLabel,
  buildAdminWalletOrderUrl,
  moneyToCents,
  normalizeMoneyDraft,
  parseAdminUserWalletRoute,
  useAdminUserWallet,
  useAdminWalletAdjustment,
  useAdminWalletTransactions,
} from '@/features/wallet'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function AdminUserWalletPage() {
  const auth = useAuth()
  const route = parseAdminUserWalletRoute(useRouter().params)
  if (!route) return <AdminWalletState title='资金账户地址无效' description='请从管理用户列表重新进入' />
  if (auth.status === 'initializing') {
    return <AdminWalletState title='正在确认管理员身份…' description='资金写入仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <AdminWalletState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='admin-wallet-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </AdminWalletState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <AdminWalletState title='登录后管理资金' description='登录后请从管理用户重新选择目标账户'>
        <Button
          className='admin-wallet-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_USER_LIST_PATH) })}
        >去登录</Button>
      </AdminWalletState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <AdminWalletState title='无管理权限' description='当前账号不会请求管理端资金 API' />
  }
  return <AuthenticatedAdminUserWallet currentUserId={auth.user?.id ?? 0} userId={route.userId} />
}

export function AuthenticatedAdminUserWallet({ currentUserId, userId }: {
  readonly currentUserId: number
  readonly userId: number
}) {
  const detail = useAdminUserWallet(userId)
  const ledger = useAdminWalletTransactions(userId)
  const adjustment = useAdminWalletAdjustment(userId)
  const [direction, setDirection] = useState<'increase' | 'decrease'>('increase')
  const [amountDraft, setAmountDraft] = useState('')
  const [reason, setReason] = useState('')
  const normalizedAmount = useMemo(() => normalizeMoneyDraft(amountDraft), [amountDraft])

  if (detail.state.status === 'loading') {
    return <AdminWalletState title='正在读取用户钱包…' description='正在核对用户、余额与能力边界' />
  }
  if (detail.state.status === 'error') {
    return (
      <AdminWalletState title='用户钱包加载失败' description={detail.state.errorMessage}>
        <Button className='admin-wallet-state__action' onClick={detail.retry}>重新加载</Button>
      </AdminWalletState>
    )
  }

  const { user, wallet } = detail.state.wallet
  const amountCents = normalizedAmount ? moneyToCents(normalizedAmount) : undefined
  const balanceCents = moneyToCents(wallet.balance)
  const limitCents = moneyToCents(wallet.balance_limit)
  const signedCents = amountCents === undefined ? undefined : direction === 'increase' ? amountCents : -amountCents
  const projectedCents = signedCents === undefined || balanceCents === undefined ? undefined : balanceCents + signedCents
  const amountValid = amountCents !== undefined && amountCents >= 1 && amountCents <= 100000
  const projectedValid = amountValid && projectedCents !== undefined && limitCents !== undefined &&
    projectedCents >= 0 && projectedCents <= limitCents
  const targetAllowed = user.role === 'user' && user.id !== currentUserId && wallet.status === 'active'
  const assistedOrderAllowed = targetAllowed && user.status === 'normal'
  const intentLocked = adjustment.state.status === 'submitting' || adjustment.state.status === 'unknown'
  const canSubmit = targetAllowed && projectedValid && reason.trim().length >= 1 && reason.trim().length <= 256 &&
    !intentLocked
  const canRetrySameIntent = targetAllowed && adjustment.state.status === 'unknown'
  const adjustmentActionDisabled = adjustment.state.status === 'unknown' ? !canRetrySameIntent : !canSubmit
  const change = normalizedAmount
    ? direction === 'increase' ? normalizedAmount : `-${normalizedAmount}`
    : undefined

  async function confirmAdjustment(): Promise<void> {
    if (!canSubmit || !change || projectedCents === undefined) return
    const confirmation = await Taro.showModal({
      title: direction === 'increase' ? '确认增加余额？' : '确认扣减余额？',
      content: `${user.nickname}（ID ${user.id}）\n变化 ${direction === 'increase' ? '+' : '−'}¥${normalizedAmount}\n调整后 ¥${(projectedCents / 100).toFixed(2)}\n原因：${reason.trim()}`,
      confirmText: '确认调账',
      confirmColor: direction === 'increase' ? '#a92e51' : '#b42318',
    })
    if (!confirmation.confirm) return
    if (await adjustment.submit(change, reason.trim())) {
      setAmountDraft('')
      setReason('')
      detail.retry()
      ledger.retry()
    }
  }

  async function retrySameAdjustment(): Promise<void> {
    if (!canRetrySameIntent) return
    if (await adjustment.retrySameIntent()) {
      setAmountDraft('')
      setReason('')
      detail.retry()
      ledger.retry()
    }
  }

  return (
    <View className='admin-wallet-page'>
      <View className='admin-wallet-page__header'>
        <Text className='admin-wallet-page__eyebrow'>用户资金 · #{user.id}</Text>
        <Text className='admin-wallet-page__title'>{user.nickname}</Text>
        <Text className='admin-wallet-page__subtitle'>@{user.username} · {user.status === 'normal' ? '正常' : '已禁用'} · 普通用户资金账本</Text>
      </View>

      <View className='admin-wallet-balance'>
        <Text className='admin-wallet-balance__label'>当前余额</Text>
        <Text className='admin-wallet-balance__amount'>¥{formatPrice(wallet.balance)}</Text>
        <Text className='admin-wallet-balance__limit'>账户上限 ¥{formatPrice(wallet.balance_limit)}</Text>
      </View>

      <View className='admin-wallet-commerce'>
        <Text className='admin-wallet-commerce__title'>针对商品扣款</Text>
        <Text className='admin-wallet-commerce__description'>选择当前可售商品或体验配置，由服务端按权威价格创建真实已支付订单并原子扣减余额。</Text>
        {!assistedOrderAllowed && (
          <Text className='admin-wallet-commerce__warning'>已禁用用户或不可消费的钱包只能人工纠错，不能创建代客商品订单。</Text>
        )}
        <Button
          className='admin-wallet-commerce__action'
          disabled={!assistedOrderAllowed}
          onClick={() => void Taro.navigateTo({ url: buildAdminWalletOrderUrl(user.id) })}
        >{assistedOrderAllowed ? '选择商品并扣款' : '该用户不可代客消费'}</Button>
      </View>

      <View className='admin-wallet-adjustment'>
        <Text className='admin-wallet-adjustment__title'>人工余额纠错</Text>
        <Text className='admin-wallet-adjustment__description'>已禁用普通用户仍可纠错；不得操作自己或 ADMIN+ 资金。每次提交由 Idempotency-Key 防重复。</Text>
        <View className='admin-wallet-adjustment__direction'>
          <Button
            className={`admin-wallet-adjustment__choice${direction === 'increase' ? ' admin-wallet-adjustment__choice--active' : ''}`}
            disabled={intentLocked}
            onClick={() => { if (!intentLocked) setDirection('increase') }}
          >增加余额</Button>
          <Button
            className={`admin-wallet-adjustment__choice${direction === 'decrease' ? ' admin-wallet-adjustment__choice--active' : ''}`}
            disabled={intentLocked}
            onClick={() => { if (!intentLocked) setDirection('decrease') }}
          >扣减余额</Button>
        </View>
        <Text className='admin-wallet-adjustment__label'>变化金额</Text>
        <Input
          className='admin-wallet-adjustment__input'
          maxlength={7}
          disabled={intentLocked}
          placeholder='0.01–1000.00'
          type='digit'
          value={amountDraft}
          onInput={(event) => { if (!intentLocked) setAmountDraft(event.detail.value) }}
        />
        <Text className='admin-wallet-adjustment__label'>调整原因</Text>
        <Textarea
          className='admin-wallet-adjustment__reason'
          maxlength={256}
          disabled={intentLocked}
          placeholder='必填，1–256 个字符；会进入不可变资金流水'
          value={reason}
          onInput={(event) => { if (!intentLocked) setReason(event.detail.value) }}
        />
        {projectedCents !== undefined && projectedValid && (
          <Text className='admin-wallet-adjustment__projection'>预计余额 ¥{(projectedCents / 100).toFixed(2)}</Text>
        )}
        {amountDraft && !amountValid && <Text className='admin-wallet-adjustment__error'>金额必须为 ¥0.01–¥1000.00</Text>}
        {amountValid && !projectedValid && <Text className='admin-wallet-adjustment__error'>调整后余额必须保持在 ¥0.00–¥1000.00</Text>}
        {!targetAllowed && <Text className='admin-wallet-adjustment__error'>该目标不是可调账的普通用户资金账户。</Text>}
        {(adjustment.state.status === 'failed' || adjustment.state.status === 'unknown') && (
          <Text className={`admin-wallet-adjustment__error admin-wallet-adjustment__error--${adjustment.state.status}`}>
            {adjustment.state.errorMessage}
          </Text>
        )}
        {adjustment.state.status === 'succeeded' && <Text className='admin-wallet-adjustment__success'>调账已提交并刷新账本。</Text>}
        <Button
          className='admin-wallet-adjustment__submit'
          disabled={adjustmentActionDisabled}
          loading={adjustment.state.status === 'submitting'}
          onClick={() => void (adjustment.state.status === 'unknown'
            ? retrySameAdjustment()
            : confirmAdjustment())}
        >{adjustment.state.status === 'submitting'
            ? '正在提交…'
            : intentLocked ? '重试同一笔调账' : '确认调账'}</Button>
      </View>

      <View className='admin-wallet-ledger'>
        <Text className='admin-wallet-ledger__title'>资金明细</Text>
        {ledger.state.status === 'loading' && <Text className='admin-wallet-ledger__state'>正在加载…</Text>}
        {ledger.state.status === 'empty' && <Text className='admin-wallet-ledger__state'>暂无资金记录</Text>}
        {ledger.state.status === 'error' && (
          <View className='admin-wallet-ledger__state'>
            <Text>{ledger.state.errorMessage}</Text>
            <Button onClick={ledger.retry}>重新加载</Button>
          </View>
        )}
        {ledger.state.status === 'content' && (
          <>
            <Text className='admin-wallet-ledger__summary'>已加载 {ledger.state.items.length} / {ledger.state.total} 笔</Text>
            {ledger.state.items.map((transaction) => <AdminTransactionRow key={transaction.id} transaction={transaction} />)}
            {ledger.state.page < ledger.state.pages ? (
              <Button className='admin-wallet-ledger__more' disabled={ledger.state.loadingMore} onClick={ledger.loadNextPage}>
                {ledger.state.loadingMore ? '正在加载…' : '加载更多'}
              </Button>
            ) : <Text className='admin-wallet-ledger__end'>已显示全部记录</Text>}
          </>
        )}
      </View>
    </View>
  )
}

function AdminTransactionRow({ transaction }: { readonly transaction: WalletTransaction }) {
  const income = transaction.direction === 'income'
  return (
    <View className='admin-wallet-transaction'>
      <View className='admin-wallet-transaction__heading'>
        <Text>{getWalletTransactionLabel(transaction.transaction_type)}</Text>
        <Text className={`admin-wallet-transaction__amount admin-wallet-transaction__amount--${transaction.direction}`}>
          {income ? '+' : '−'}¥{formatPrice(transaction.change_amount.replace('-', ''))}
        </Text>
      </View>
      <Text className='admin-wallet-transaction__reason'>{transaction.reason}</Text>
      <Text className='admin-wallet-transaction__meta'>¥{formatPrice(transaction.before_balance)} → ¥{formatPrice(transaction.after_balance)} · {transaction.created_at}</Text>
      {transaction.operator_nickname && <Text className='admin-wallet-transaction__meta'>操作人：{transaction.operator_nickname}</Text>}
    </View>
  )
}

function AdminWalletState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='admin-wallet-state'>
      <Text className='admin-wallet-state__title'>{title}</Text>
      <Text className='admin-wallet-state__description'>{description}</Text>
      {children}
    </View>
  )
}
