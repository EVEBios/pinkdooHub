import {
  ApiClientError,
  BusinessError,
  ContractError,
  HttpError,
  NetworkError,
  RequestCancelledError,
  SessionExpiredError,
  TimeoutError,
} from '@/api'

export function isReservationMutationUnknown(cause: unknown): boolean {
  return cause instanceof NetworkError || cause instanceof TimeoutError ||
    cause instanceof RequestCancelledError || cause instanceof ContractError ||
    (cause instanceof HttpError && (cause.statusCode ?? 0) >= 500)
}

export function getReservationErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof BusinessError) {
    if (cause.code === 40451) return '预约不存在或不可访问'
    if (cause.code === 40452) return '该日期当前没有自定义店休'
    if (cause.code === 40951) return '预约状态已发生变化，请重新加载核对'
    if (cause.code === 40952) return '已不足预约开始前三小时，不能取消'
    if (cause.code === 40953) return '预约已经开始，不能再确认或拒绝'
    if (cause.code === 42251) return '体验商品当前不可预约'
    if (cause.code === 42252) return '体验配置当前不可预约'
    if (cause.code === 42253) return getScheduleErrorMessage(cause.data)
    if (cause.code === 42254) return '请先保存当前联系电话，再提交预约'
    if (cause.code === 42255) return getClosureDateErrorMessage(cause.data)
    if (cause.statusCode === 403) return '当前账号没有执行此操作的权限'
  }
  if (cause instanceof SessionExpiredError) return '登录状态已失效，请重新登录'
  if (cause instanceof ApiClientError && cause.message) return cause.message
  return cause instanceof Error && cause.message ? cause.message : fallback
}

function getScheduleErrorMessage(data: unknown): string {
  const reason = readReason(data)
  const messages: Readonly<Record<string, string>> = {
    minimum_lead_time: '该时段距离现在不足三小时，请选择更晚时间',
    outside_booking_window: '该日期超出未来 30 天预约范围',
    invalid_slot_increment: '开始时间必须为整点或半点',
    outside_business_hours: '体验必须完整安排在 11:00–20:00 营业时间内',
    weekly_closed: '该日期为每周固定店休日，不能预约',
    store_closed: '门店已将该日期设为店休，请选择其他日期',
    option_day_type_mismatch: '所选日期与体验配置的工作日/节假日类型不一致',
  }
  return reason ? messages[reason] ?? '所选预约日期或时段当前不可用' : '所选预约日期或时段当前不可用'
}

function getClosureDateErrorMessage(data: unknown): string {
  const reason = readReason(data)
  if (reason === 'past_date') return '不能设置或恢复过去日期的营业状态'
  if (reason === 'weekly_closed') return '该日期已是每周固定店休日，无需重复添加'
  return '该日期当前不能设置或恢复营业状态'
}

function readReason(value: unknown): string | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value) &&
    typeof (value as Record<string, unknown>).reason === 'string'
    ? (value as Record<string, string>).reason
    : undefined
}
