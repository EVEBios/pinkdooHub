import { Button, Text, View } from '@tarojs/components'
import { useEffect, useMemo } from 'react'

import type { UserProfile } from '@/api/endpoints/auth'
import {
  ADMIN_WORKBENCH_PATH,
  isAdminRole,
  MALL_PATH,
  useAuth,
} from '@/auth'
import {
  type DestinationNavigationTarget,
  useLatestDestinationNavigation,
} from '@/navigation/use_latest_destination_navigation'

import './index.scss'

type EntryDestination = Readonly<DestinationNavigationTarget & {
  url: typeof ADMIN_WORKBENCH_PATH | typeof MALL_PATH
}>

export default function EntryPage() {
  const auth = useAuth()
  const { navigationError, openDestination, resetNavigation } = useLatestDestinationNavigation()

  const destination = useMemo(
    () => resolveEntryDestination(auth.status, auth.user?.role),
    [auth.status, auth.user?.role],
  )

  useEffect(() => {
    if (!destination) {
      resetNavigation()
      return
    }
    void openDestination(destination)
  }, [destination, openDestination, resetNavigation])

  if (auth.status === 'error') {
    return (
      <EntryState
        title='登录状态暂不可用'
        description={auth.initializationError?.message ?? '请稍后重试'}
        descriptionIsError
      >
        <Button className='entry-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </EntryState>
    )
  }
  if (auth.status === 'authenticated' && !auth.user) {
    return (
      <EntryState title='账户信息不完整' description='请重新检查登录状态后再继续' descriptionIsError>
        <Button className='entry-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </EntryState>
    )
  }
  if (auth.status === 'authenticated' && auth.user && !destination) {
    return (
      <EntryState title='账户角色无法识别' description='请重新检查登录状态后再继续' descriptionIsError>
        <Button className='entry-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </EntryState>
    )
  }

  const enteringWorkbench = destination?.url === ADMIN_WORKBENCH_PATH
  return (
    <EntryState
      title={enteringWorkbench ? '正在进入店铺工作台…' : '正在进入 pinkdooHub…'}
      description={enteringWorkbench ? '工作人员操作与顾客商城相互独立' : '正在确认本次使用身份'}
    >
      {navigationError && (
        <>
          <View className='entry-state__error' ariaRole='alert'>
            <Text>{navigationError}</Text>
          </View>
          {destination && (
            <Button className='entry-state__action' onClick={() => void openDestination(destination)}>
              重新进入
            </Button>
          )}
        </>
      )}
    </EntryState>
  )
}

export function resolveEntryDestination(
  status: ReturnType<typeof useAuth>['status'],
  role: UserProfile['role'] | undefined,
): EntryDestination | undefined {
  if (status === 'guest') {
    return { method: 'switchTab', url: MALL_PATH }
  }
  if (status !== 'authenticated' || !role) {
    return undefined
  }
  if (role === 'user') {
    return { method: 'switchTab', url: MALL_PATH }
  }
  if (isAdminRole(role)) {
    return { method: 'reLaunch', url: ADMIN_WORKBENCH_PATH }
  }
  return undefined
}

function EntryState({ children, description, descriptionIsError = false, title }: {
  readonly title: string
  readonly description: string
  readonly descriptionIsError?: boolean
  readonly children?: React.ReactNode
}) {
  return (
    <View className='entry-state'>
      <Text className='entry-state__title'>{title}</Text>
      {descriptionIsError ? (
        <View className='entry-state__description' ariaRole='alert'>
          <Text>{description}</Text>
        </View>
      ) : (
        <Text className='entry-state__description'>{description}</Text>
      )}
      {children}
    </View>
  )
}
