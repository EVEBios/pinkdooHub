# 门店用豆库存 API（P2.4）

2026-09-15。仓库实现；持久环境迁移状态以现场记录为准。

本模块为 ADMIN / SUPER_ADMIN 共用的门店未拆封整包台账。单位和筛选规则以[业务规则](../01_requirements/store_bead_stock_plan.md)为准，与商城 10g 库存无写入联动。使用既有 Bearer 身份及统一 `{code,message,data}` 响应，不接受客户端指定操作人。无通知端点、提醒事件或已读状态。

## 端点

根路径 `/api/v1/admin/store-bead-stock`。

| 方法与后缀 | 内容 |
|---|---|
| GET 根路径 | 颜色库存分页；page 默认 1，page_size 默认及最大 221；按目录 sort、slot_no 稳定排序 |
| POST `/batches` | 原子保存 1～221 个变更颜色，成功返回本次完整批次 |
| GET `/batches` | 历史批次，既有分页参数；按 created_at DESC、id DESC 稳定排序 |
| GET `/batches/{id}` | 任一管理员读取完整历史批次 |
| GET `/batches/by-request/{request_key}` | 仅查询当前操作者的原 UUID 请求结果；未知结果恢复用，不以此替代全店历史入口 |

列表使用标准 Page（items、page、page_size、total、pages）。颜色条目含 bead_color_id、slot_no、color_code、color_name、packs、revision。没有余额行时返回 packs=null、revision=0；确认零库存后返回 packs=0、revision>=1。读取不创建余额，也不预填库存。

## 批量提交

```json
{
  "request_key": "a57b30c9-0934-42e1-aecf-00c69a89ff55",
  "reason": "stocktake",
  "note": "早班盘点",
  "items": [
    {"bead_color_id": 1, "expected_revision": 0, "packs": 0},
    {"bead_color_id": 2, "expected_revision": 3, "packs": 5}
  ]
}
```

- packs：严格非负整数，0～999999；不接受布尔、小数或数字字符串。颜色 ID 为正整数，expected_revision 为非负整数。
- items：1～221 条，颜色 ID 不得重复，只提交真实变更；未盘点→0 是有效变更。
- request_key：UUID，按操作者隔离。重复提交相同 key 和相同意图返回原批次；颜色顺序不影响意图，原因和 trim 后备注属于意图。
- reason 默认 stocktake（库存盘点），还支持 restock（补货入库）、opening（开包领用）、other。原因用于说明操作，不代替逐色数量核验，不自动推导数量。
- note 默认空串、最长 500 字符、trim；请求及条目拒绝多余字段。

批次包含 id、operator_id、operator_name、created_at（UTC）、reason、note、changed_colors 和 items。每项保存目录快照（颜色 ID、slot_no、色号、名称）、before_packs（首次为 null）、after_packs 和提交后 revision。历史记录的色号不随目录改名漂移；操作人显示当前昵称，空昵称回退“管理员”。不返回内部 fingerprint。

## 原子性、冲突与重试

Service 在事务内按颜色 ID 加锁目录父行，再检查原批次与余额版本；父行锁覆盖尚无余额的首次盘点竞争。只有涉及的颜色需要版本一致。余额、批次、逐色流水与审计同事务提交；任一项失败则全部回滚。颜色余额只能通过本模块更改，历史不提供编辑/删除接口。

| HTTP | 业务码 | 处理 |
|---|---|---|
| 409 | 40973 | 版本已变化；data.conflicts 返回 bead_color_id、最新 packs、revision。整批未写入，保留草稿，重新读取并再次核对确认 |
| 409 | 40974 | 请求 key 已用于另一意图；不得覆盖原记录 |
| 422 | 42273 | 含未改变的已盘点颜色，整批拒绝 |
| 404 | 通用 NotFound | 颜色或批次不存在；by-request 的 key 不属于当前操作者也返回未找到 |
| 401/403/422 | 既有鉴权/校验契约 | 未登录、无权限或请求校验失败 |

网络错误、超时或无法识别的回执不能直接判定未保存。客户端冻结原请求，先通过 by-request 核查；404 后才用相同 key 与内容重试 POST。保存成功后的刷新失败单独提示，不能再次提交。MySQL 死锁/锁等待使用既有有界重试策略，唯一键竞争仅重放相同已提交意图。
