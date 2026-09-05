import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import type { WalletTransaction } from '@/api/endpoints/wallet'
import { buildLoginUrl, useAuth, WALLET_TRANSACTION_LIST_PATH } from '@/auth'
import { getWalletTransactionLabel, useWalletTransactions } from '@/features/wallet'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function WalletTransactionsPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <LedgerState title='正在确认会员身份…' description='资金明细仅对本人可见' />
  }
  if (auth.status === 'error') {
    return (
      <LedgerState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='wallet-ledger-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </LedgerState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <LedgerState title='登录后查看资金明细' description='登录成功后会回到这里'>
        <Button
          className='wallet-ledger-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(WALLET_TRANSACTION_LIST_PATH) })}
        >去登录</Button>
      </LedgerState>
    )
  }
  return <AuthenticatedWalletTransactions />
}

export function AuthenticatedWalletTransactions() {
  const { loadNextPage, retry, state } = useWalletTransactions()
  return (
    <View className='wallet-ledger-page'>
      <View className='wallet-ledger-page__header'>
        <Text className='wallet-ledger-page__eyebrow'>资金账簿</Text>
        <Text className='wallet-ledger-page__title'>每一笔余额变化，都有来路</Text>
        <Text className='wallet-ledger-page__subtitle'>按服务端提交顺序分页展示，余额以每笔交易后的余额为准。</Text>
      </View>
      {state.status === 'loading' && <LedgerState title='正在加载资金明细…' description='正在读取服务端第一页' />}
      {state.status === 'empty' && <LedgerState title='还没有资金记录' description='充值、支付、退款或人工纠错后会显示在这里' />}
      {state.status === 'error' && (
        <LedgerState title='资金明细加载失败' description={state.errorMessage ?? '请稍后重试'}>
          <Button className='wallet-ledger-state__action' onClick={retry}>重新加载</Button>
        </LedgerState>
      )}
      {state.status === 'content' && (
        <View className='wallet-ledger'>
          <View className='wallet-ledger__summary'>
            <Text>已加载 {state.items.length} 笔</Text>
            <Text>共 {state.total} 笔</Text>
          </View>
          {state.items.map((transaction) => <TransactionRow key={transaction.id} transaction={transaction} />)}
          {state.errorMessage && <Text className='wallet-ledger__error'>{state.errorMessage}</Text>}
          {state.page < state.pages ? (
            <Button className='wallet-ledger__more' disabled={state.loadingMore} onClick={loadNextPage}>
              {state.loadingMore ? '正在加载…' : state.errorMessage ? '重试加载更多' : '加载更多'}
            </Button>
          ) : <Text className='wallet-ledger__end'>已显示全部资金记录</Text>}
        </View>
      )}
    </View>
  )
}

export function TransactionRow({ transaction }: { readonly transaction: WalletTransaction }) {
  const income = transaction.direction === 'income'
  return (
    <View className='wallet-transaction'>
      <View className='wallet-transaction__rail' />
      <View className='wallet-transaction__main'>
        <View className='wallet-transaction__heading'>
          <Text className='wallet-transaction__type'>{getWalletTransactionLabel(transaction.transaction_type)}</Text>
          <Text className={`wallet-transaction__change wallet-transaction__change--${transaction.direction}`}>
            {income ? '+' : '−'}¥{formatPrice(transaction.change_amount.replace('-', ''))}
          </Text>
        </View>
        <Text className='wallet-transaction__reason'>{transaction.reason}</Text>
        <View className='wallet-transaction__balance'>
          <Text>余额 ¥{formatPrice(transaction.before_balance)}</Text>
          <Text>→</Text>
          <Text>¥{formatPrice(transaction.after_balance)}</Text>
        </View>
        <Text className='wallet-transaction__meta'>
          {transaction.source_order_no ? `订单 ${transaction.source_order_no} · ` : ''}{transaction.created_at}
        </Text>
        {transaction.operator_nickname && <Text className='wallet-transaction__operator'>操作人：{transaction.operator_nickname}</Text>}
      </View>
    </View>
  )
}

function LedgerState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='wallet-ledger-state'>
      <Text className='wallet-ledger-state__title'>{title}</Text>
      <Text className='wallet-ledger-state__description'>{description}</Text>
      {children}
    </View>
  )
}
