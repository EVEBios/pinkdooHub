import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useRef, useState } from 'react'

import {
  ADMIN_INVENTORY_LIST_PATH,
  ADMIN_ORDER_LIST_PATH,
  ADMIN_PRODUCT_LIST_PATH,
  ADMIN_RESERVATION_LIST_PATH,
  ADMIN_STORE_CLOSURE_LIST_PATH,
  ADMIN_USER_LIST_PATH,
  ADMIN_WORKBENCH_PATH,
  buildLoginUrl,
  isAdminRole,
  MALL_PATH,
  SessionPersistenceClearError,
  useAuth,
} from '@/auth'

import './index.scss'

const WORKBENCH_GROUPS = [
  {
    title: '今日处理',
    description: '先完成需要及时回应的门店事务',
    tone: 'ink',
    actions: [
      { label: '预约审核', meta: '确认、拒绝与联系顾客', url: ADMIN_RESERVATION_LIST_PATH },
      { label: '订单处理', meta: '支付确认与履约', url: ADMIN_ORDER_LIST_PATH },
    ],
  },
  {
    title: '商品与库存',
    description: '维护在售内容和库存变动记录',
    tone: 'berry',
    actions: [
      { label: '商品管理', meta: '商品、价格与配置', url: ADMIN_PRODUCT_LIST_PATH },
      { label: '库存流水', meta: '变动记录与来源', url: ADMIN_INVENTORY_LIST_PATH },
    ],
  },
  {
    title: '门店与权限',
    description: '安排营业时间并管理工作人员账号',
    tone: 'rose',
    actions: [
      { label: '营业日历', meta: '固定店休与单日店休', url: ADMIN_STORE_CLOSURE_LIST_PATH },
      { label: '用户与权限', meta: '账号状态与资金入口', url: ADMIN_USER_LIST_PATH },
    ],
  },
] as const

export default function AdminWorkbenchPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <WorkbenchState title='正在确认工作人员身份…' description='管理功能仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <WorkbenchState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='workbench-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </WorkbenchState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <WorkbenchState title='登录后进入店铺工作台' description='登录后仍会根据服务端角色校验权限'>
        <WorkbenchLoginAction />
      </WorkbenchState>
    )
  }
  if (!auth.user) {
    return (
      <WorkbenchState title='账户信息不完整' description='请重新检查登录状态后再进入工作台'>
        <Button className='workbench-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </WorkbenchState>
    )
  }
  if (!isAdminRole(auth.user.role)) {
    return (
      <WorkbenchState title='无管理权限' description='当前账号不会请求任何管理端数据'>
        <Button className='workbench-state__action' onClick={() => void Taro.switchTab({ url: MALL_PATH })}>
          返回商城
        </Button>
      </WorkbenchState>
    )
  }
  return <AuthenticatedWorkbench onLogout={auth.logout} user={auth.user} />
}

function AuthenticatedWorkbench({ onLogout, user }: {
  readonly onLogout: () => Promise<void>
  readonly user: NonNullable<ReturnType<typeof useAuth>['user']>
}) {
  const logoutInFlightRef = useRef(false)
  const loginNavigationRef = useRef(false)
  const actionNavigationRef = useRef('')
  const [loggingOut, setLoggingOut] = useState(false)
  const [openingLogin, setOpeningLogin] = useState(false)
  const [logoutNavigationError, setLogoutNavigationError] = useState('')
  const [activeActionUrl, setActiveActionUrl] = useState('')
  const [actionNavigationFailure, setActionNavigationFailure] = useState<{
    readonly label: string
    readonly url: string
  }>()
  const roleLabel = user.role === 'super_admin' ? '超级管理员' : '管理员'

  async function openAction(action: { readonly label: string; readonly url: string }): Promise<void> {
    if (actionNavigationRef.current || logoutInFlightRef.current || loginNavigationRef.current) return
    actionNavigationRef.current = action.url
    setActiveActionUrl(action.url)
    setActionNavigationFailure(undefined)
    try {
      await Taro.navigateTo({ url: action.url })
    } catch {
      setActionNavigationFailure(action)
    } finally {
      if (actionNavigationRef.current === action.url) {
        actionNavigationRef.current = ''
        setActiveActionUrl('')
      }
    }
  }

  async function openLogin(): Promise<void> {
    if (loginNavigationRef.current || actionNavigationRef.current) return
    loginNavigationRef.current = true
    setOpeningLogin(true)
    setLogoutNavigationError('')
    try {
      await Taro.reLaunch({ url: buildLoginUrl() })
    } catch {
      setLogoutNavigationError('登录页暂时无法打开，请重试。')
    } finally {
      loginNavigationRef.current = false
      setOpeningLogin(false)
    }
  }

  async function logout(): Promise<void> {
    if (logoutInFlightRef.current || actionNavigationRef.current || loginNavigationRef.current) return
    logoutInFlightRef.current = true
    setLoggingOut(true)
    let logoutWarning = ''
    try {
      try {
        await onLogout()
      } catch (cause) {
        if (cause instanceof SessionPersistenceClearError) {
          // 设备中仍可能留有可恢复凭据，保留 AuthProvider 的全局错误态，
          // 不能强行跳到会被历史 Session 再次接管的登录页。
          void Taro.showToast({ title: cause.message, icon: 'none', duration: 2500 })
          return
        }
        logoutWarning = '服务端登出未确认，本机会话已清除'
      }
      await openLogin()
      if (logoutWarning) {
        void Taro.showToast({
          title: logoutWarning,
          icon: 'none',
          duration: 2500,
        })
      }
    } finally {
      logoutInFlightRef.current = false
      setLoggingOut(false)
    }
  }

  return (
    <View className='workbench-page'>
      <View className='workbench-page__header'>
        <View className='workbench-page__heading'>
          <Text className='workbench-page__title'>店铺工作台</Text>
          <Text className='workbench-page__brand'>pinkdooHub</Text>
        </View>
        <Text className='workbench-page__identity'>{user.nickname} · @{user.username} · {roleLabel}</Text>
        <Text className='workbench-page__subtitle'>处理今日事务，维护商品与门店。</Text>
      </View>

      <View className='workbench-groups'>
        {WORKBENCH_GROUPS.map((group) => (
          <View
            key={group.title}
            className={`workbench-group workbench-group--${group.tone}`}
          >
            <View className='workbench-group__heading'>
              <Text className='workbench-group__title'>{group.title}</Text>
              <Text className='workbench-group__description'>{group.description}</Text>
            </View>
            <View className='workbench-group__actions'>
              {group.actions.map((action) => (
                <Button
                  key={action.url}
                  ariaLabel={`${action.label}，${action.meta}${activeActionUrl === action.url ? '，正在打开' : ''}`}
                  className={`workbench-action${activeActionUrl === action.url ? ' workbench-action--pending' : ''}`}
                  hoverClass='workbench-action--pressed'
                  onClick={() => void openAction(action)}
                >
                  <View className='workbench-action__copy'>
                    <Text className='workbench-action__label'>{action.label}</Text>
                    <Text className='workbench-action__meta'>{action.meta}</Text>
                  </View>
                  <Text className='workbench-action__enter'>进入</Text>
                </Button>
              ))}
            </View>
          </View>
        ))}
      </View>

      {actionNavigationFailure && (
        <View ariaRole='alert' className='workbench-navigation-error'>
          <Text className='workbench-navigation-error__message'>
            {actionNavigationFailure.label}暂时无法打开，请重试。
          </Text>
          <Button
            className='workbench-navigation-error__action'
            disabled={activeActionUrl.length > 0}
            onClick={() => void openAction(actionNavigationFailure)}
          >
            重新进入{actionNavigationFailure.label}
          </Button>
        </View>
      )}
      {logoutNavigationError && (
        <View ariaRole='alert' className='workbench-logout__error'>
          <Text>{logoutNavigationError}</Text>
        </View>
      )}
      <Button
        className='workbench-logout__button'
        disabled={loggingOut || openingLogin || activeActionUrl.length > 0}
        onClick={() => void (logoutNavigationError ? openLogin() : logout())}
      >
        {loggingOut ? '正在退出…' : openingLogin ? '正在返回…' : logoutNavigationError ? '返回登录' : '退出当前账号'}
      </Button>
    </View>
  )
}

function WorkbenchLoginAction() {
  const openingRef = useRef(false)
  const [opening, setOpening] = useState(false)
  const [navigationError, setNavigationError] = useState('')

  async function openLogin(): Promise<void> {
    if (openingRef.current) return
    openingRef.current = true
    setOpening(true)
    setNavigationError('')
    try {
      await Taro.navigateTo({ url: buildLoginUrl(ADMIN_WORKBENCH_PATH) })
    } catch {
      setNavigationError('登录页暂时无法打开，请重试。')
    } finally {
      openingRef.current = false
      setOpening(false)
    }
  }

  return (
    <>
      {navigationError && (
        <View ariaRole='alert' className='workbench-state__error'>
          <Text>{navigationError}</Text>
        </View>
      )}
      <Button
        className='workbench-state__action'
        disabled={opening}
        onClick={() => void openLogin()}
      >{opening ? '正在打开…' : '去登录'}</Button>
    </>
  )
}

function WorkbenchState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='workbench-state'>
      <Text className='workbench-state__title'>{title}</Text>
      <Text className='workbench-state__description'>{description}</Text>
      {children}
    </View>
  )
}
