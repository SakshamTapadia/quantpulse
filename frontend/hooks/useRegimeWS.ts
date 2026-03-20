'use client'
import { useEffect } from 'react'
import { useRegimeStore } from '@/lib/store'

export function useRegimeWS() {
  const { connectWS, disconnectWS, connected } = useRegimeStore()

  useEffect(() => {
    connectWS()
    return () => disconnectWS()
  }, [])

  return connected
}
