import { Button, Form, Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  ApiClientError,
  BusinessError,
  ContractError,
  HttpError,
  NetworkError,
  RequestCancelledError,
  TimeoutError,
} from '@/api'
import type { RegistrationRequest, UserProfile } from '@/api/endpoints/auth'
import {
  buildLoginUrl,
  parseLoginRedirect,
  resolveAuthenticatedLanding,
  SessionPersistenceClearError,
  useAuth,
} from '@/auth'
import {
  resolvePathNavigationTarget,
  useLatestDestinationNavigation,
} from '@/navigation/use_latest_destination_navigation'

import './index.scss'

interface RegistrationForm extends RegistrationRequest {
  confirmPassword: string
}

const EMPTY_FORM: RegistrationForm = {
  username: '',
  password: '',
  confirmPassword: '',
  nickname: '',
  phone: '',
}

export default function RegisterPage() {
  const redirect = parseLoginRedirect(useRouter().params.redirect)
  const { logout, register, retryInitialization, status, user } = useAuth()
  const loginNavigationRef = useRef(false)
  const sessionResetRef = useRef(false)
  const { navigationError, openDestination, resetNavigation } = useLatestDestinationNavigation()
  const [form, setForm] = useState<RegistrationForm>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [loginNavigationError, setLoginNavigationError] = useState('')
  const [openingLogin, setOpeningLogin] = useState(false)
  const [resettingSession, setResettingSession] = useState(false)
  const [registeredUser, setRegisteredUser] = useState<UserProfile>()

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

  function updateField<Key extends keyof RegistrationForm>(
    field: Key,
    value: RegistrationForm[Key],
  ): void {
    setForm((current) => ({ ...current, [field]: value }))
  }

  async function submitRegistration(): Promise<void> {
    if (submittingRef.current) {
      return
    }
    const normalized = normalizeRegistrationForm(form)
    const validationMessage = validateRegistration(normalized)
    if (validationMessage) {
      setErrorMessage(validationMessage)
      return
    }

    submittingRef.current = true
    setSubmitting(true)
    setErrorMessage('')
    try {
      const createdUser = await register({
        username: normalized.username,
        password: normalized.password,
        nickname: normalized.nickname,
        phone: normalized.phone,
      })
      setRegisteredUser(createdUser)
      setForm(EMPTY_FORM)
    } catch (cause) {
      setForm((current) => ({ ...current, password: '', confirmPassword: '' }))
      setErrorMessage(getRegistrationErrorMessage(cause))
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  const loginUrl = buildLoginUrl(redirect)

  async function openLogin(): Promise<void> {
    if (loginNavigationRef.current) return
    loginNavigationRef.current = true
    setOpeningLogin(true)
    setLoginNavigationError('')
    try {
      await Taro.redirectTo({ url: loginUrl })
    } catch {
      setLoginNavigationError('登录页暂时无法打开，请重试。')
    } finally {
      loginNavigationRef.current = false
      setOpeningLogin(false)
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

  if (registeredUser) {
    return (
      <View className='registration-page'>
        <View className='registration-card registration-success'>
          <Text className='registration-card__eyebrow'>pinkdooHub</Text>
          <Text className='registration-card__title'>注册成功</Text>
          <Text className='registration-success__description'>
            账号 {registeredUser.username} 已创建，请使用刚才设置的密码登录。
          </Text>
          {loginNavigationError && (
            <View className='registration-navigation__error' ariaRole='alert'>
              <Text>{loginNavigationError}</Text>
            </View>
          )}
          <Button
            className='registration-form__submit'
            disabled={openingLogin}
            type='primary'
            onClick={() => void openLogin()}
          >
            {openingLogin ? '正在打开登录…' : loginNavigationError ? '重新打开登录' : '去登录'}
          </Button>
          <Text className='registration-card__notice'>注册不会自动登录，也不会在本地保存密码。</Text>
        </View>
      </View>
    )
  }

  return (
    <View className='registration-page'>
      <View className='registration-card'>
        <Text className='registration-card__eyebrow'>pinkdooHub</Text>
        <Text className='registration-card__title'>创建账号</Text>
        <Text className='registration-card__subtitle'>注册后默认为普通用户，请继续登录使用</Text>

        {authenticatedLandingProblem && (
          <View className='registration-navigation'>
            <View className='registration-navigation__error' ariaRole='alert'>
              <Text>{authenticatedLandingProblem}</Text>
            </View>
            <Button
              className='registration-navigation__retry'
              disabled={resettingSession}
              onClick={retryInitialization}
            >重新检查</Button>
            <Button
              className='registration-navigation__retry'
              disabled={resettingSession}
              onClick={() => void resetAuthenticatedSession()}
            >{resettingSession ? '正在退出…' : '退出当前会话'}</Button>
          </View>
        )}

        {navigationError && destination && (
          <View className='registration-navigation'>
            <View className='registration-navigation__error' ariaRole='alert'>
              <Text>{navigationError}</Text>
            </View>
            <Button
              className='registration-navigation__retry'
              onClick={() => void openDestination(resolvePathNavigationTarget(destination))}
            >
              重新进入
            </Button>
          </View>
        )}

        <Form className='registration-form'>
          <RegistrationInput
            label='用户名'
            maxlength={32}
            placeholder='请输入 3–32 个字符'
            value={form.username}
            onInput={(value) => updateField('username', value)}
          />
          <RegistrationInput
            label='昵称'
            maxlength={32}
            placeholder='请输入显示昵称'
            value={form.nickname}
            onInput={(value) => updateField('nickname', value)}
          />
          <RegistrationInput
            label='手机号'
            maxlength={11}
            placeholder='请输入 11 位中国大陆手机号'
            type='number'
            value={form.phone}
            onInput={(value) => updateField('phone', value)}
          />
          <RegistrationInput
            label='密码'
            maxlength={64}
            password
            placeholder='8–64 个字符'
            value={form.password}
            onInput={(value) => updateField('password', value)}
          />
          <RegistrationInput
            label='确认密码'
            maxlength={64}
            password
            placeholder='请再次输入密码'
            value={form.confirmPassword}
            onInput={(value) => updateField('confirmPassword', value)}
          />

          {errorMessage && (
            <View className='registration-form__error' ariaRole='alert'>
              <Text>{errorMessage}</Text>
            </View>
          )}

          <Button
            className='registration-form__submit'
            disabled={submitting || status === 'initializing' || status === 'authenticated'}
            type='primary'
            onClick={() => void submitRegistration()}
          >
            {status === 'initializing'
              ? '正在恢复会话…'
              : status === 'authenticated'
                ? '当前会话已登录'
                : submitting ? '注册中…' : '注册'}
          </Button>
        </Form>

        {loginNavigationError && (
          <View className='registration-navigation__error' ariaRole='alert'>
            <Text>{loginNavigationError}</Text>
          </View>
        )}
        <Button
          className='registration-card__login'
          disabled={openingLogin}
          onClick={() => void openLogin()}
        >
          {openingLogin ? '正在返回登录…' : loginNavigationError ? '重新返回登录' : '已有账号？返回登录'}
        </Button>
        <Text className='registration-card__notice'>密码只用于注册请求，不会写入 URL 或本地存储。</Text>
      </View>
    </View>
  )
}

interface RegistrationInputProps {
  label: string
  value: string
  placeholder: string
  maxlength: number
  password?: boolean
  type?: 'number' | 'text'
  onInput(value: string): void
}

function RegistrationInput({
  label,
  maxlength,
  onInput,
  password = false,
  placeholder,
  type = 'text',
  value,
}: RegistrationInputProps) {
  return (
    <>
      <Text className='registration-form__label'>{label}</Text>
      <Input
        className='registration-form__input'
        maxlength={maxlength}
        password={password}
        placeholder={placeholder}
        type={type}
        value={value}
        onInput={(event) => onInput(event.detail.value)}
      />
    </>
  )
}

export function normalizeRegistrationForm(form: RegistrationForm): RegistrationForm {
  return {
    username: form.username.trim(),
    password: form.password,
    confirmPassword: form.confirmPassword,
    nickname: form.nickname.trim(),
    phone: form.phone.trim(),
  }
}

export function validateRegistration(form: RegistrationForm): string {
  if (!form.username) {
    return '请输入用户名'
  }
  if (form.username.length < 3 || form.username.length > 32) {
    return '用户名长度应为 3–32 个字符'
  }
  if (!form.nickname) {
    return '请输入昵称'
  }
  if (form.nickname.length > 32) {
    return '昵称不能超过 32 个字符'
  }
  if (!/^1[3-9]\d{9}$/.test(form.phone)) {
    return '请输入有效的 11 位中国大陆手机号'
  }
  if (form.password.length < 8 || form.password.length > 64) {
    return '密码长度应为 8–64 个字符'
  }
  if (!form.confirmPassword) {
    return '请再次输入密码'
  }
  if (form.password !== form.confirmPassword) {
    return '两次输入的密码不一致'
  }
  return ''
}

export function getRegistrationErrorMessage(cause: unknown): string {
  if (cause instanceof BusinessError) {
    if (cause.code === 1001) {
      return '用户名已被注册，请更换用户名或直接登录'
    }
    if (cause.code === 1007) {
      return '手机号已被注册，请更换手机号或直接登录'
    }
    if (cause.code === 422) {
      return '注册信息不符合要求，请检查后重试'
    }
  }
  if (
    cause instanceof NetworkError ||
    cause instanceof TimeoutError ||
    cause instanceof RequestCancelledError ||
    cause instanceof ContractError ||
    cause instanceof HttpError
  ) {
    return '注册结果暂无法确认，请先尝试登录；若无法登录再重新注册'
  }
  if (cause instanceof ApiClientError) {
    return cause.message
  }
  return '注册失败，请稍后重试'
}
