import { Button, Form, Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useEffect, useState } from 'react'

import { ApiClientError, BusinessError } from '@/api'
import { buildRegisterUrl, parseLoginRedirect, useAuth } from '@/auth'

import './index.scss'

export default function LoginPage() {
  const router = useRouter()
  const redirect = parseLoginRedirect(router.params.redirect)
  const { login, status } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    if (status === 'authenticated') {
      void Taro.reLaunch({ url: redirect ?? '/pages/index/index' })
    }
  }, [redirect, status])

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

  return (
    <View className='login-page'>
      <View className='login-card'>
        <Text className='login-card__eyebrow'>pinkdooHub</Text>
        <Text className='login-card__title'>欢迎回来</Text>
        <Text className='login-card__subtitle'>学习 / MVP 阶段使用现有账号登录</Text>

        <Form className='login-form' onSubmit={() => void submitLogin()}>
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

          {errorMessage && <Text className='login-form__error'>{errorMessage}</Text>}

          <Button
            className='login-form__submit'
            disabled={submitting || status === 'initializing'}
            formType='submit'
            type='primary'
          >
            {status === 'initializing' ? '正在恢复会话…' : submitting ? '登录中…' : '登录'}
          </Button>
        </Form>

        <Button
          className='login-card__register'
          onClick={() => void Taro.navigateTo({ url: buildRegisterUrl(redirect) })}
        >
          没有账号？立即注册
        </Button>

        <Text className='login-card__notice'>密码只用于本次请求，不会保存在本地。</Text>
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
