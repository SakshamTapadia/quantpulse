'use client'
import { useRegimeWS } from '@/hooks/useRegimeWS'

export function WSProvider({ children }: { children: React.ReactNode }) {
  useRegimeWS()
  return <>{children}</>
}
