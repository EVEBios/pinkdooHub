import { attentionStore } from '@/features/attention/runtime'
import Taro from '@tarojs/taro'

import type { TableSessionApi } from '@/api/endpoints/table_sessions'
import { BusinessError } from '@/api/errors'
import { formatPrice } from '@/utils/format'

export async function confirmTablePayment(source: TableSessionApi, sessionNo: string): Promise<boolean> {
  const session = await source.getAdminSession(sessionNo)
  if (session.status.value !== 'awaiting_payment' || !session.order_id || !session.order_total_amount) {
    throw new Error('这次会话已不处于待付款状态，请刷新桌台')
  }
  const result = await Taro.showModal({
    title: `${session.table.table_no} · 确认已收款`,
    content: `顾客：${session.user_nickname}\n订单：${session.order_no}\n整单应收：¥${formatPrice(session.order_total_amount)}\n体验时长：${(session.order_experience_durations ?? []).join("、")} 分钟\n已在线下收取全部款项，确认后立即开始计时；每组体验结束后另有 10 分钟缓冲。`,
    confirmText: '收款计时',
  })
  if (!result.confirm) return false
  try {
    await source.confirmAdminPayment(session.order_id, sessionNo)
    attentionStore.invalidate(true)
  } catch (cause) {
    // 超时或并发付款后，以同一会话的服务端事实判断，不能重新发起收款。
    const current = await source.getAdminSession(sessionNo).catch(() => null)
    if (current?.status.value === 'active' && current.payment_id) return true
    if (current?.status.value === 'closed') throw new Error('这次桌台会话已结束，请重新绑定桌台后处理')
    if (cause instanceof BusinessError) throw new Error(tableAdminError(cause))
    throw new Error('收款结果尚未确认，请刷新会话；仍待付款时再核对收款状态')
  }
  return true
}

export function tableAdminError(cause: unknown): string {
  if (cause instanceof BusinessError) {
    switch (cause.code) {
      case 40961: return '桌台已被占用或暂停开台，请刷新后选择空闲桌台'
      case 40962:
      case 40966: return '这次桌台会话已结束或付款超时，请刷新后重新绑定桌台'
      case 40965: return '本次操作信息已变化，请核对原操作结果'
      case 42262: return '所选体验时长已不可用，请重新选择'
      default: break
    }
  }
  return cause instanceof Error && /[\u3400-\u9fff]/u.test(cause.message)
    ? cause.message : '操作未完成，请刷新后重试'
}
