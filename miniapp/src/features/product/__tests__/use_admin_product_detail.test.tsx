import ReactTestUtil from '@tarojs/test-utils-react'

import type { AdminExperienceProductDetail } from '@/api/endpoints/admin_products'

import { type AdminProductDetailSource, useAdminProductDetail } from '../use_admin_product_detail'

const experience: AdminExperienceProductDetail = {
  id: 7,
  name: '草稿体验',
  description: null,
  product_type: { value: 'experience', label: '拼豆体验' },
  status: { value: 'draft', label: '草稿' },
  images: [],
  dimensions: { durations: [], participants: [], day_types: [] },
  options: [],
  created_at: '2026-08-25T07:00:00Z',
  updated_at: '2026-08-25T08:00:00Z',
  is_deleted: false,
}

function Harness({ source }: { readonly source: AdminProductDetailSource }) {
  const { retry, state } = useAdminProductDetail(7, 'experience', source)
  return <div>
    <span className='status'>{state.status}</span>
    <span className='name'>{state.status === 'content' ? state.product.name : ''}</span>
    <button className='retry' onClick={retry}>retry</button>
  </div>
}

describe('useAdminProductDetail', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('按路由类型只调用 Experience 详情源', async () => {
    const source: AdminProductDetailSource = {
      getExperienceProduct: jest.fn(async () => experience),
      getKitProduct: jest.fn(),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('content')
    expect(requireElement(testUtils, '.name').textContent).toBe('草稿体验')
    expect(source.getExperienceProduct).toHaveBeenCalledWith(7)
    expect(source.getKitProduct).not.toHaveBeenCalled()
  })

  it('失败后可显式重试，不自动切换 Product 类型', async () => {
    const source: AdminProductDetailSource = {
      getExperienceProduct: jest.fn()
        .mockRejectedValueOnce(new Error('40401'))
        .mockResolvedValueOnce(experience),
      getKitProduct: jest.fn(),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('error')
    testUtils.fireEvent.click(requireElement(testUtils, '.retry'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('content')
    expect(source.getKitProduct).not.toHaveBeenCalled()
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
  })
}
