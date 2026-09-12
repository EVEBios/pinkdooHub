import ReactTestUtil from '@tarojs/test-utils-react'

import type { AdminUserListPage } from '@/api/endpoints/admin_users'

import { type AdminUserListSource, useAdminUserList } from '../use_admin_user_list'

const page: AdminUserListPage = {
  items: [{
    id: 5, username: 'normal_user', nickname: '普通用户', role: 'user', status: 'normal',
    last_login_at: null, created_at: '2026-08-28T08:00:00Z',
  }],
  total: 1, page: 1, page_size: 20, pages: 1,
}

function Harness({ source }: { readonly source: AdminUserListSource }) {
  const { applyFilters, state } = useAdminUserList(source)
  return (
    <div>
      <span className='status'>{state.status}</span>
      <button className='filter' onClick={() => applyFilters({ role: 'user', status: 'normal' })}>filter</button>
    </div>
  )
}

describe('useAdminUserList', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('筛选变化后从第一页重新查询', async () => {
    const source: AdminUserListSource = { listUsers: jest.fn(async () => page) }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.filter'))
    await flush(testUtils)
    expect(source.listUsers).toHaveBeenLastCalledWith({
      page: 1, page_size: 20, role: 'user', status: 'normal',
    })
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}
