import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import type {
  AddCartItemInput,
  CartItem,
  CartItemIdentity,
  CartReconciliationResult,
  CartSnapshot,
  CartStatus,
} from './cart'
import { getDefaultCartRuntime, type CartRuntime } from './runtime'

export interface CartContextValue {
  readonly status: CartStatus
  readonly items: readonly CartItem[]
  readonly initializationError?: Error
  addItem(item: AddCartItemInput): Promise<void>
  addItems(items: readonly AddCartItemInput[]): Promise<void>
  updateQuantity(identity: CartItemIdentity, quantity: number): Promise<void>
  removeItem(identity: CartItemIdentity): Promise<void>
  clear(): Promise<void>
  reconcileSubmittedItems(items: readonly CartItem[]): Promise<CartReconciliationResult>
  retryInitialization(): void
}

interface CartProviderProps extends PropsWithChildren {
  runtime?: CartRuntime
}

const CartContext = createContext<CartContextValue | undefined>(undefined)

const INITIAL_SNAPSHOT: CartSnapshot = { status: 'initializing', items: [] }

export function CartProvider({ children, runtime: runtimeProp }: CartProviderProps) {
  const runtimeRef = useRef<CartRuntime>()
  runtimeRef.current ??= runtimeProp ?? getDefaultCartRuntime()
  const runtime = runtimeRef.current
  const [snapshot, setSnapshot] = useState<CartSnapshot>(INITIAL_SNAPSHOT)

  useEffect(() => runtime.store.subscribe(setSnapshot), [runtime])

  useEffect(() => {
    void runtime.store.restore().catch(() => undefined)
  }, [runtime])

  const retryInitialization = useCallback(() => {
    void runtime.store.restore().catch(() => undefined)
  }, [runtime])

  const value = useMemo<CartContextValue>(() => ({
    status: snapshot.status,
    items: snapshot.items,
    initializationError: snapshot.initializationError,
    addItem: (item) => runtime.store.addItem(item),
    addItems: (items) => runtime.store.addItems(items),
    updateQuantity: (identity, quantity) => runtime.store.updateQuantity(identity, quantity),
    removeItem: (identity) => runtime.store.removeItem(identity),
    clear: () => runtime.store.clear(),
    reconcileSubmittedItems: (items) => runtime.store.reconcileSubmittedItems(items),
    retryInitialization,
  }), [retryInitialization, runtime, snapshot])

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>
}

export function useCart(): CartContextValue {
  const value = useContext(CartContext)
  if (!value) {
    throw new Error('useCart 必须在 CartProvider 内使用')
  }
  return value
}
