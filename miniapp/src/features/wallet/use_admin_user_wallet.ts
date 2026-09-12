import { useCallback, useEffect, useRef, useState } from 'react'

import type { AdminUserWallet } from '@/api/endpoints/wallet'

import { getWalletErrorMessage } from './mutation'
import { getDefaultWalletApi } from './runtime'

export type AdminUserWalletState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | { readonly status: 'content'; readonly wallet: AdminUserWallet }

export interface AdminUserWalletSource {
  getAdminUserWallet(userId: number): Promise<AdminUserWallet>
}

export function useAdminUserWallet(
  userId: number,
  source: AdminUserWalletSource = getDefaultWalletApi(),
) {
  const [state, setState] = useState<AdminUserWalletState>({ status: 'loading' })
  const sequenceRef = useRef(0)
  const load = useCallback(() => {
    const sequence = ++sequenceRef.current
    setState({ status: 'loading' })
    void source.getAdminUserWallet(userId).then((wallet) => {
      if (sequence === sequenceRef.current) setState({ status: 'content', wallet })
    }).catch((cause: unknown) => {
      if (sequence !== sequenceRef.current) return
      const error = cause instanceof Error ? cause : new Error('用户钱包加载失败')
      setState({ status: 'error', errorMessage: getWalletErrorMessage(error, '用户钱包加载失败') })
    })
  }, [source, userId])
  useEffect(() => {
    load()
    return () => { sequenceRef.current += 1 }
  }, [load])
  return { state, retry: load }
}
