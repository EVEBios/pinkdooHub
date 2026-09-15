import { StoreBeadStockApi } from '../store_bead_stock'

const rows = Array.from({ length: 221 }, (_, index) => ({ bead_color_id: index + 1, slot_no: index + 1, color_code: `A${index + 1}`, color_name: null, packs: null, revision: 0 }))
const page = { items: rows, page: 1, page_size: 221, total: 221, pages: 1 }
const saved = { id: 1, operator_id: 1, operator_name: '测试店员', created_at: '2026-09-15T00:00:00Z', reason: 'stocktake', note: '', changed_colors: 1, items: [{ ...rows[0], before_packs: null, after_packs: 0, revision: 1 }] }
const body = { reason: 'stocktake' as const, note: '', request_key: 'ad46713a-3af9-4e6c-a401-00fe8b063aaa', items: [{ bead_color_id: 1, expected_revision: 0, packs: 0 }] }

describe('门店库存响应契约', () => {
  const request = jest.fn()
  const api = new StoreBeadStockApi({ request })
  afterEach(() => request.mockReset())
  it('读取全部221色并保留未盘点', async () => {
    request.mockResolvedValue(page)
    expect(await api.list()).toEqual(rows)
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ auth: 'required', query: { page: 1, page_size: 221 } }))
  })
  it.each([
    { ...page, items: rows.slice(1) },
    { ...page, items: [rows[0], ...rows.slice(0, 220)] },
    { ...page, items: [{ ...rows[0], packs: 0 }, ...rows.slice(1)] },
    { ...page, items: [{ ...rows[0], packs: -1, revision: 1 }, ...rows.slice(1)] },
  ])('拒绝不完整、重复或非法库存响应', async value => {
    request.mockResolvedValue(value)
    await expect(api.list()).rejects.toMatchObject({ name: 'ContractError' })
  })
  it('首次零盘点可保存；拒绝与本次提交不一致的回执', async () => {
    request.mockResolvedValue(saved)
    expect(await api.write(body)).toEqual(saved)
    request.mockResolvedValue({ ...saved, items: [{ ...saved.items[0], after_packs: 3 }] })
    await expect(api.write(body)).rejects.toMatchObject({ name: 'ContractError' })
  })
})
