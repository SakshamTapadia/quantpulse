'use client'
import { useRegimeStore } from '@/lib/store'
import { REGIME_COLORS, RegimeName } from '@/lib/api'
import { RegimeBadge } from './RegimeBadge'

export function RegimeHeatmap() {
  const { regimes, selectedTicker, setSelectedTicker } = useRegimeStore()
  const entries = Object.entries(regimes).sort(([a], [b]) => a.localeCompare(b))

  if (entries.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-slate-500 text-sm">
        Waiting for regime signals…
      </div>
    )
  }

  return (
    <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
      {entries.map(([ticker, signal]) => {
        const color = REGIME_COLORS[signal.regime_name as RegimeName]
        const isSelected = ticker === selectedTicker
        return (
          <button
            key={ticker}
            onClick={() => setSelectedTicker(ticker)}
            className="relative rounded-lg p-3 text-left transition-all hover:scale-105"
            style={{
              backgroundColor: isSelected ? `${color}33` : `${color}11`,
              border: `1px solid ${isSelected ? color : `${color}44`}`,
              boxShadow: isSelected ? `0 0 12px ${color}44` : 'none',
            }}
          >
            <div className="font-mono font-bold text-sm text-white">{ticker}</div>
            <div className="text-xs mt-0.5" style={{ color }}>
              {signal.regime_name.replace('_', '-')}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">
              {(signal.confidence * 100).toFixed(0)}%
            </div>
          </button>
        )
      })}
    </div>
  )
}
