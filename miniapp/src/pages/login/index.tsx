import { Button, Form, Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ApiClientError, BusinessError } from '@/api'
import {
  buildRegisterUrl,
  parseLoginRedirect,
  resolveAuthenticatedLanding,
  SessionPersistenceClearError,
  useAuth,
} from '@/auth'
import { resolveEnv } from '@/config/env'
import {
  resolvePathNavigationTarget,
  useLatestDestinationNavigation,
} from '@/navigation/use_latest_destination_navigation'

import './index.scss'

export default function LoginPage() {
  const router = useRouter()
  const redirect = parseLoginRedirect(router.params.redirect)
  const { login, loginWithWechat, logout, retryInitialization, status, user } = useAuth()
  const registerNavigationRef = useRef(false)
  const sessionResetRef = useRef(false)
  const { navigationError, openDestination, resetNavigation } = useLatestDestinationNavigation()
  const { authMode } = resolveEnv()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [registerNavigationError, setRegisterNavigationError] = useState('')
  const [openingRegister, setOpeningRegister] = useState(false)
  const [resettingSession, setResettingSession] = useState(false)

  const destination = useMemo(
    () => status === 'authenticated'
      ? resolveAuthenticatedLanding(user?.role, redirect)
      : undefined,
    [redirect, status, user?.role],
  )

  useEffect(() => {
    if (!destination) {
      resetNavigation()
      return
    }
    void openDestination(resolvePathNavigationTarget(destination))
  }, [destination, openDestination, resetNavigation])

  async function submitLogin(): Promise<void> {
    const validationMessage = validateLogin(username, password)
    if (validationMessage) {
      setErrorMessage(validationMessage)
      return
    }

    setSubmitting(true)
    setErrorMessage('')
    try {
      await login(username, password)
    } catch (cause) {
      setPassword('')
      setErrorMessage(getLoginErrorMessage(cause))
    } finally {
      setSubmitting(false)
    }
  }

  async function submitWeChatLogin(): Promise<void> {
    setSubmitting(true)
    setErrorMessage('')
    try {
      await loginWithWechat()
    } catch (cause) {
      setErrorMessage(getLoginErrorMessage(cause))
    } finally {
      setSubmitting(false)
    }
  }

  async function openRegister(): Promise<void> {
    if (registerNavigationRef.current) return
    registerNavigationRef.current = true
    setOpeningRegister(true)
    setRegisterNavigationError('')
    try {
      // 替换登录页，避免“登录 → 注册 → 登录”往返不断堆高小程序页面栈。
      await Taro.redirectTo({ url: buildRegisterUrl(redirect) })
    } catch {
      setRegisterNavigationError('注册页暂时无法打开，请重试。')
    } finally {
      registerNavigationRef.current = false
      setOpeningRegister(false)
    }
  }

  async function resetAuthenticatedSession(): Promise<void> {
    if (sessionResetRef.current) return
    sessionResetRef.current = true
    setResettingSession(true)
    try {
      await logout()
    } catch (cause) {
      const title = cause instanceof SessionPersistenceClearError
        ? cause.message
        : '服务端登出未确认，本机会话已清除'
      void Taro.showToast({ title, icon: 'none', duration: 2500 }).catch(() => undefined)
    } finally {
      sessionResetRef.current = false
      setResettingSession(false)
    }
  }

  const authenticatedLandingProblem = status === 'authenticated' && !destination
    ? user
      ? '账户角色暂不支持，请重新检查或退出当前会话。'
      : '账户信息不完整，请重新检查或退出当前会话。'
    : ''

  return (
    <View className='login-page'>
      <View className='login-card'>
        <Text className='login-card__eyebrow'>pinkdooHub</Text>
        <Text className='login-card__title'>欢迎回来</Text>
        <Text className='login-card__subtitle'>
          {authMode === 'wechat' ? '使用微信安全登录' : '内部测试使用现有账号登录'}
        </Text>

        {authenticatedLandingProblem && (
          <View className='login-navigation'>
            <View className='login-navigation__error' ariaRole='alert'>
              <Text>{authenticatedLandingProblem}</Text>
            </View>
            <Button
              className='login-navigation__retry'
              disabled={resettingSession}
              onClick={retryInitialization}
            >重新检查</Button>
            <Button
              className='login-navigation__retry'
              disabled={resettingSession}
              onClick={() => void resetAuthenticatedSession()}
            >{resettingSession ? '正在退出…' : '退出当前会话'}</Button>
          </View>
        )}

        {navigationError && destination && (
          <View className='login-navigation'>
            <View className='login-navigation__error' ariaRole='alert'>
              <Text>{navigationError}</Text>
            </View>
            <Button
              className='login-navigation__retry'
              onClick={() => void openDestination(resolvePathNavigationTarget(destination))}
            >
              重新进入
            </Button>
          </View>
        )}

        {authMode === 'wechat' ? (
          <View className='login-form'>
            {errorMessage && (
              <View className='login-form__error' ariaRole='alert'>
                <Text>{errorMessage}</Text>
              </View>
            )}
            <Button
              className='login-form__submit login-form__submit--wechat'
              disabled={submitting || status === 'initializing' || status === 'authenticated'}
              hoverClass='login-form__submit--pressed'
              onClick={() => void submitWeChatLogin()}
            >
              {status === 'initializing'
                ? '正在恢复会话…'
                : status === 'authenticated'
                  ? '登录已完成'
                  : submitting ? '登录中…' : '微信一键登录'}
            </Button>
          </View>
        ) : (
        <Form className='login-form'>
          <Text className='login-form__label'>用户名</Text>
          <Input
            alwaysEmbed
            className='login-form__input'
            maxlength={32}
            placeholder='请输入用户名'
            value={username}
            onInput={(event) => setUsername(event.detail.value)}
          />

          <Text className='login-form__label'>密码</Text>
          <Input
            alwaysEmbed
            className='login-form__input'
            maxlength={128}
            password
            placeholder='请输入密码'
            value={password}
            onInput={(event) => setPassword(event.detail.value)}
          />

          {errorMessage && (
            <View className='login-form__error' ariaRole='alert'>
              <Text>{errorMessage}</Text>
            </View>
          )}

          <Button
            className='login-form__submit'
            disabled={submitting || status === 'initializing' || status === 'authenticated'}
            hoverClass='login-form__submit--pressed'
            onClick={() => void submitLogin()}
          >
            {status === 'initializing'
              ? '正在恢复会话…'
              : status === 'authenticated'
                ? '登录已完成'
                : submitting ? '登录中…' : '登录'}
          </Button>
        </Form>
        )}

        {authMode === 'password' && (
        <>
          {registerNavigationError && (
            <View className='login-navigation__error' ariaRole='alert'>
              <Text>{registerNavigationError}</Text>
            </View>
          )}
          <Button
            className='login-card__register'
            disabled={openingRegister || status === 'initializing' || status === 'authenticated'}
            onClick={() => void openRegister()}
          >
            {openingRegister ? '正在打开注册…' : registerNavigationError ? '重新打开注册' : '没有账号？立即注册'}
          </Button>
        </>
        )}

        <Text className='login-card__notice'>
          {authMode === 'wechat'
            ? '小程序只向服务端提交一次性 code，不保存 OpenID 或 session_key。'
            : '密码只用于本次请求，不会保存在本地。'}
        </Text>
      </View>
    </View>
  )
}

export function validateLogin(username: string, password: string): string {
  if (!username) {
    return '请输入用户名'
  }
  if (!password) {
    return '请输入密码'
  }
  return ''
}

export function getLoginErrorMessage(cause: unknown): string {
  if (cause instanceof BusinessError) {
    if (cause.code === 1002 || cause.code === 1003) {
      return '用户名或密码错误'
    }
    if (cause.code === 1005) {
      return '账号已被禁用，请联系管理员'
    }
  }
  if (cause instanceof ApiClientError) {
    return cause.message
  }
  return '登录失败，请稍后重试'
}
