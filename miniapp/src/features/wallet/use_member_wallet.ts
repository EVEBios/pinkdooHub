import { useCallback, useEffect, useRef, useState } from 'react'

import type { MemberWallet } from '@/api/endpoints/wallet'
import { useRefreshAfterPageReturn } from '@/platform/use_refresh_after_page_return'

import { getDefaultWalletApi } from './runtime'
import { getWalletErrorMessage } from './mutation'

export type MemberWalletState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | {
    readonly status: 'content'
    readonly member: MemberWallet
    readonly refreshErrorMessage?: string
  }

export interface MemberWalletSource {
  getMemberWallet(): Promise<MemberWallet>
}

export function useMemberWallet(source: MemberWalletSource = getDefaultWalletApi()) {
  const [state, setState] = useState<MemberWalletState>({ status: 'loading' })
  const sequenceRef = useRef(0)

  const load = useCallback((preserveContent = false) => {
    const sequence = ++sequenceRef.current
    setState((current) => preserveContent && current.status === 'content'
      ? { ...current, refreshErrorMessage: undefined }
      : { status: 'loading' })
    void source.getMemberWallet().then((member) => {
      if (sequence === sequenceRef.current) setState({ status: 'content', member })
    }).catch((cause: unknown) => {
      if (sequence !== sequenceRef.current) return
      const error = cause instanceof Error ? cause : new Error('会员钱包加载失败')
      const errorMessage = getWalletErrorMessage(error, '会员钱包加载失败')
      setState((current) => preserveContent && current.status === 'content'
        ? { ...current, refreshErrorMessage: errorMessage }
        : { status: 'error', errorMessage })
    })
  }, [source])

  const refresh = useCallback(() => {
    load(true)
  }, [load])
  const retry = useCallback(() => {
    load()
  }, [load])

  useRefreshAfterPageReturn(refresh)

  useEffect(() => {
    load()
    return () => { sequenceRef.current += 1 }
  }, [load])

  return { state, retry }
}
