'use client'
import { create } from 'zustand'
import { RegimeSignal, WS_URL } from '@/lib/api'

interface RegimeStore {
  regimes: Record<string, RegimeSignal>
  connected: boolean
  selectedTicker: string
  token: string
  setToken: (t: string) => void
  setSelectedTicker: (t: string) => void
  setRegimes: (r: Record<string, RegimeSignal>) => void
  updateRegime: (ticker: string, signal: RegimeSignal) => void
  connectWS: () => void
  disconnectWS: () => void
}

let ws: WebSocket | null = null

export const useRegimeStore = create<RegimeStore>((set, get) => ({
  regimes: {},
  connected: false,
  selectedTicker: 'SPY',
  token: '',

  setToken: (token) => set({ token }),
  setSelectedTicker: (ticker) => set({ selectedTicker: ticker }),
  setRegimes: (regimes) => set({ regimes }),
  updateRegime: (ticker, signal) =>
    set((state) => ({ regimes: { ...state.regimes, [ticker]: signal } })),

  connectWS: () => {
    if (ws) return
    const token = get().token
    ws = new WebSocket(`${WS_URL}/ws/regime?token=${token}`)

    ws.onopen = () => set({ connected: true })
    ws.onclose = () => {
      set({ connected: false })
      ws = null
      // Reconnect after 3s
      setTimeout(() => get().connectWS(), 3000)
    }
    ws.onerror = () => ws?.close()
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'snapshot') {
          set({ regimes: msg.data })
        } else if (msg.ticker) {
          get().updateRegime(msg.ticker, msg as RegimeSignal)
        }
      } catch {/* ignore parse errors */}
    }
  },

  disconnectWS: () => {
    ws?.close()
    ws = null
    set({ connected: false })
  },
}))
