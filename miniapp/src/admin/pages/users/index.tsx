import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import type { AdminUserListItem } from '@/api/endpoints/admin_users'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_USER_LIST_PATH,
  type AdminUserRoleFilter,
  type AdminUserStatusFilter,
  useAdminUserDisable,
  useAdminUserList,
} from '@/features/admin_user'

import './index.scss'

const STATUS_FILTERS: ReadonlyArray<{ value: AdminUserStatusFilter; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'normal', label: '正常' },
  { value: 'disabled', label: '已禁用' },
]
const ROLE_FILTERS: ReadonlyArray<{ value: AdminUserRoleFilter; label: string }> = [
  { value: 'all', label: '全部角色' },
  { value: 'user', label: '普通用户' },
  { value: 'admin', label: '管理员' },
  { value: 'super_admin', label: '超级管理员' },
]
const ROLE_LABELS = { user: '普通用户', admin: '管理员', super_admin: '超级管理员' } as const

export default function AdminUsersPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <AdminUsersState title='正在确认管理员身份…' description='管理用户仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <AdminUsersState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='admin-users-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </AdminUsersState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <AdminUsersState title='登录后进入管理用户' description='登录成功后会返回管理用户，并由服务端再次校验角色'>
        <Button
          className='admin-users-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_USER_LIST_PATH) })}
        >去登录</Button>
      </AdminUsersState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <AdminUsersState title='无管理权限' description='当前账号不会请求任何管理端用户 API' />
  }
  return <AuthenticatedAdminUsers currentUserId={auth.user?.id ?? 0} currentRole={auth.user?.role ?? 'user'} />
}

export function AuthenticatedAdminUsers({ currentRole, currentUserId }: {
  readonly currentUserId: number
  readonly currentRole: string
}) {
  const list = useAdminUserList()
  const mutation = useAdminUserDisable()

  async function confirmDisable(user: AdminUserListItem): Promise<void> {
    if (!canDisable(user, currentUserId, currentRole) || mutation.state.status === 'submitting') return
    const confirmation = await Taro.showModal({
      title: '确认禁用用户',
      content: `禁用“${user.nickname}（${user.username}）”后，该账号将无法再次登录。此页面不提供启用操作。`,
      confirmText: '确认禁用',
      confirmColor: '#b42318',
    })
    if (!confirmation.confirm) return
    if (await mutation.disableUser(user.id)) {
      mutation.reset()
      list.retry()
    }
  }

  const mutationMessage = mutation.state.status === 'failed' || mutation.state.status === 'unknown'
    ? mutation.state.errorMessage
    : undefined
  return (
    <View className='admin-users-page'>
      <View className='admin-users-page__header'>
        <Text className='admin-users-page__title'>管理用户</Text>
        <Text className='admin-users-page__subtitle'>仅展示安全摘要；支持角色、状态筛选与幂等禁用</Text>
      </View>

      <View className='admin-user-filters'>
        <Text className='admin-user-filters__label'>状态</Text>
        <View className='admin-user-filters__row'>
          {STATUS_FILTERS.map((filter) => (
            <Button
              key={filter.value}
              className={`admin-user-filters__choice${list.filters.status === filter.value ? ' admin-user-filters__active' : ''}`}
              onClick={() => list.applyFilters({ ...list.filters, status: filter.value })}
            >{filter.label}</Button>
          ))}
        </View>
        <Text className='admin-user-filters__label'>角色</Text>
        <View className='admin-user-filters__row'>
          {ROLE_FILTERS.map((filter) => (
            <Button
              key={filter.value}
              className={`admin-user-filters__choice${list.filters.role === filter.value ? ' admin-user-filters__active' : ''}`}
              onClick={() => list.applyFilters({ ...list.filters, role: filter.value })}
            >{filter.label}</Button>
          ))}
        </View>
      </View>

      {list.state.status === 'loading' && <AdminUsersState title='正在加载管理用户…' description='正在读取服务端第一页' />}
      {list.state.status === 'empty' && <AdminUsersState title='当前筛选下没有用户' description='可切换角色或状态后重试' />}
      {list.state.status === 'error' && (
        <AdminUsersState title='管理用户加载失败' description={list.state.errorMessage ?? '请稍后重试'}>
          <Button className='admin-users-state__action' onClick={list.retry}>重新加载</Button>
        </AdminUsersState>
      )}
      {list.state.status === 'content' && (
        <View className='admin-user-list'>
          <View className='admin-user-list__summary'>
            <Text>已加载 {list.state.items.length} 人</Text>
            <Text>共 {list.state.total} 人</Text>
          </View>
          {list.state.items.map((user) => (
            <UserCard
              key={user.id}
              currentRole={currentRole}
              currentUserId={currentUserId}
              mutationState={mutation.state}
              user={user}
              onDisable={() => void confirmDisable(user)}
            />
          ))}
          {list.state.errorMessage && <Text className='admin-user-list__error'>{list.state.errorMessage}</Text>}
          {list.state.page < list.state.pages ? (
            <Button disabled={list.state.loadingMore} onClick={list.loadNextPage}>
              {list.state.loadingMore ? '正在加载…' : list.state.errorMessage ? '重试加载更多' : '加载更多'}
            </Button>
          ) : <Text className='admin-user-list__end'>已经到底了</Text>}
        </View>
      )}
      {mutationMessage && <Text className='admin-users-page__mutation-error'>{mutationMessage}</Text>}
      {mutation.state.status === 'unknown' && (
        <Button className='admin-users-page__verify' onClick={list.retry}>重新加载列表核对</Button>
      )}
    </View>
  )
}

function UserCard({ currentRole, currentUserId, mutationState, onDisable, user }: {
  readonly user: AdminUserListItem
  readonly currentUserId: number
  readonly currentRole: string
  readonly mutationState: ReturnType<typeof useAdminUserDisable>['state']
  readonly onDisable: () => void
}) {
  const allowed = canDisable(user, currentUserId, currentRole)
  const submittingThis = mutationState.status === 'submitting' && mutationState.userId === user.id
  return (
    <View className='admin-user-card'>
      <View className='admin-user-card__heading'>
        <View>
          <Text className='admin-user-card__nickname'>{user.nickname}</Text>
          <Text className='admin-user-card__username'>@{user.username} · ID {user.id}</Text>
        </View>
        <Text className={`admin-user-card__status admin-user-card__status--${user.status}`}>
          {user.status === 'normal' ? '正常' : '已禁用'}
        </Text>
      </View>
      <Text className='admin-user-card__role'>角色：{ROLE_LABELS[user.role]}</Text>
      <Text className='admin-user-card__time'>创建时间：{user.created_at}</Text>
      <Text className='admin-user-card__time'>最近登录：{user.last_login_at ?? '从未登录'}</Text>
      <Button
        className={`admin-user-card__disable${allowed ? '' : ' admin-user-card__disable--unavailable'}`}
        disabled={!allowed || mutationState.status === 'submitting'}
        onClick={onDisable}
      >{submittingThis ? '正在禁用…' : getDisableLabel(user, currentUserId, currentRole)}</Button>
    </View>
  )
}

function canDisable(user: AdminUserListItem, currentUserId: number, currentRole: string): boolean {
  return user.status === 'normal' && user.id !== currentUserId &&
    !(user.role === 'super_admin' && currentRole !== 'super_admin')
}

function getDisableLabel(user: AdminUserListItem, currentUserId: number, currentRole: string): string {
  if (user.status === 'disabled') return '已禁用'
  if (user.id === currentUserId) return '当前账号'
  if (user.role === 'super_admin' && currentRole !== 'super_admin') return '无权禁用'
  return '禁用用户'
}

function AdminUsersState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='admin-users-state'>
      <Text className='admin-users-state__title'>{title}</Text>
      <Text className='admin-users-state__description'>{description}</Text>
      {children}
    </View>
  )
}
