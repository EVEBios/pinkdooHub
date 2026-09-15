import ReactTestUtil from '@tarojs/test-utils-react'

import { NetworkError } from '@/api'

import { type AdminUserDisableSource, useAdminUserDisable } from '../use_admin_user_disable'

function Harness({ source }: { readonly source: AdminUserDisableSource }) {
  const { disableUser, state } = useAdminUserDisable(source)
  return (
    <div>
      <span className='status'>{state.status}</span>
      <span className='message'>{state.status === 'failed' || state.status === 'unknown' ? state.errorMessage : ''}</span>
      <button className='disable' onClick={() => void disableUser(5)}>disable</button>
    </div>
  )
}

describe('useAdminUserDisable', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('网络错误进入 unknown 且不自动重试', async () => {
    const source: AdminUserDisableSource = {
      disableUser: jest.fn(async () => { throw new NetworkError({ operation: 'users.admin.disable' }, new Error('offline')) }),
    }
    await testUtils.mount(Harness, { props: { source } })
    testUtils.fireEvent.click(requireElement(testUtils, '.disable'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('unknown')
    expect(requireElement(testUtils, '.message').textContent).toContain('不会自动重试')
    expect(source.disableUser).toHaveBeenCalledTimes(1)
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
