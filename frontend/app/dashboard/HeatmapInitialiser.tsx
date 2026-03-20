'use client'
import { useEffect } from 'react'
import { useRegimeStore } from '@/lib/store'
import { RegimeSignal } from '@/lib/api'

interface Props {
  regimes: Record<string, RegimeSignal>
  token: string
}

export function HeatmapInitialiser({ regimes, token }: Props) {
  const { setRegimes, setToken } = useRegimeStore()
  useEffect(() => {
    setToken(token)
    setRegimes(regimes)
  }, [])
  return null
}
