import { BusinessError } from '@/api'

export function getTableErrorMessage(cause: unknown): string {
  if (cause instanceof BusinessError) {
    if (cause.code === 40461 || cause.code === 40463) return '未找到这张桌台，请核对桌号或重新扫码'
    if (cause.code === 40961) return '这张桌台已被占用或暂停使用，请选择其他桌台'
    if (cause.code === 40962 || cause.code === 40966) return '本次占台已结束，请重新选择桌台后付款'
    if (cause.code === 40963) return '你已有一张进行中的桌台，请先查看当前桌台'
    if (cause.code === 40964) return '这笔订单已关联桌台，请刷新订单查看'
    if (cause.code === 40965) return '本次提交与原订单不一致，请到我的订单核对'
    if (cause.code === 42261) return '开台需要一笔待付款且包含体验项目的订单'
    if (cause.statusCode === 503) return '开台暂不可用，请稍后重试或联系店员'
  }
  return cause instanceof Error ? cause.message : '桌台操作失败，请重试'
}
