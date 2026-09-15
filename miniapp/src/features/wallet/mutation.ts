import {
  BusinessError,
  ContractError,
  HttpError,
  NetworkError,
  RequestCancelledError,
  SessionExpiredError,
  TimeoutError,
} from '@/api'

export function isWalletMutationUnknown(error: Error): boolean {
  return error instanceof NetworkError || error instanceof TimeoutError ||
    error instanceof RequestCancelledError || error instanceof ContractError ||
    (error instanceof HttpError && (error.statusCode ?? 0) >= 500) ||
    (error instanceof BusinessError && (error.statusCode ?? 0) >= 500 &&
      error.statusCode !== 503)
}

export function getWalletErrorMessage(error: Error, fallback: string): string {
  if (error instanceof SessionExpiredError) return '登录状态已失效，请重新登录'
  if (error instanceof BusinessError) {
    if (error.code === 40441) return '钱包不存在或不可见'
    if (error.code === 40941) return '调整后余额必须保持在 0.00–1000.00 元'
    if (error.code === 40942) return '钱包余额不足，请选择微信支付或先调整订单'
    if (error.code === 40943) return '该操作标识已用于另一笔资金操作，请重新发起'
    if (error.code === 40944 || error.code === 40945) return '资金状态已经变化，请重新加载核对'
    if (error.code === 40946) return '退款状态已经变化，请重新加载核对'
    if (error.code === 40947) return '余额调整会侵占待退款额度，请先处理相关订单'
    if (error.code === 40948) return '该订单已超过可退款期限'
    if (error.code === 40931) return '材料套装库存不足，请调整购买数量'
    if (error.code === 42231) return '商品当前不可下单，请重新选择'
    if (error.code === 42232) return '体验配置当前不可用，请重新选择'
    if (error.code === 42241) return '单笔充值金额必须为 1.00–1000.00 元'
    if (error.statusCode === 403) return '当前账号没有该资金操作权限'
    if (error.statusCode === 503 && error.operation === 'wallet.admin.order.create') {
      return '管理员代客商品扣款能力暂未开放，请稍后再试'
    }
    if (error.statusCode === 503) return '微信支付暂未开通，请稍后再试'
  }
  return error.message || fallback
}
