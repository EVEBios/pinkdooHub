import { useCallback, useEffect, useRef, useState } from 'react'

import type { MemberWallet } from '@/api/endpoints/wallet'

import { getDefaultWalletApi } from './runtime'
import { getWalletErrorMessage } from './mutation'

export type MemberWalletState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | { readonly status: 'content'; readonly member: MemberWallet }

export interface MemberWalletSource {
  getMemberWallet(): Promise<MemberWallet>
}

export function useMemberWallet(source: MemberWalletSource = getDefaultWalletApi()) {
  const [state, setState] = useState<MemberWalletState>({ status: 'loading' })
  const sequenceRef = useRef(0)

  const load = useCallback(() => {
    const sequence = ++sequenceRef.current
    setState({ status: 'loading' })
    void source.getMemberWallet().then((member) => {
      if (sequence === sequenceRef.current) setState({ status: 'content', member })
    }).catch((cause: unknown) => {
      if (sequence !== sequenceRef.current) return
      const error = cause instanceof Error ? cause : new Error('会员钱包加载失败')
      setState({ status: 'error', errorMessage: getWalletErrorMessage(error, '会员钱包加载失败') })
    })
  }, [source])

  useEffect(() => {
    load()
    return () => { sequenceRef.current += 1 }
  }, [load])

  return { state, retry: load }
}
