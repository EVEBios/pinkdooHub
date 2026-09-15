import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { buildLoginUrl, useAuth, WALLET_TRANSACTION_LIST_PATH } from '@/auth'
import { CommerceReceipt, buildCommerceAttentionUrl } from '@/features/attention'
import '../attention/index.scss'

export default function WalletResultPage() {
  const auth = useAuth()
  const rawId = useRouter().params.id
  const id = rawId && /^[1-9]\d*$/.test(rawId) ? Number(rawId) : undefined
  if (auth.status !== 'authenticated' || !auth.user) return <View className='attention-page'><Text>登录后查看余额变动</Text><Button className='attention-page__retry' onClick={() => void Taro.navigateTo({ url: buildLoginUrl() })}>去登录</Button></View>
  if (auth.user.role !== 'user' || !id || !Number.isSafeInteger(id)) return <View className='attention-page'><Text>余额变动记录不可用，请从会员中心重新进入</Text></View>
  return <View className='attention-page'>
    <View className='attention-page__header'><Text className='attention-page__title'>余额变动详情</Text><Text className='attention-page__description'>核对这笔调整的金额与门店说明</Text></View>
    <CommerceReceipt key={`${auth.user.id}:${id}`} scope='wallet' target={id} />
    <Button className='attention-page__all' onClick={() => void Taro.navigateTo({ url: WALLET_TRANSACTION_LIST_PATH })}>查看资金明细</Button>
    <Button className='attention-page__all' onClick={() => void Taro.navigateTo({ url: buildCommerceAttentionUrl('wallet') })}>查看其他余额变动</Button>
  </View>
}
