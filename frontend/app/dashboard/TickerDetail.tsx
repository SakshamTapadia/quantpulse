'use client'
import { useEffect, useState } from 'react'
import { useRegimeStore } from '@/lib/store'
import { getOHLCV, getRegimeHistory, OHLCVBar, RegimeHistoryRow, REGIME_LABELS, RegimeName } from '@/lib/api'
import { CandlestickChart } from '@/components/charts/CandlestickChart'
import { RegimeBadge } from '@/components/regime/RegimeBadge'
import { ProbabilityBar } from '@/components/regime/ProbabilityBar'

export function TickerDetail({ token }: { token: string }) {
  const { selectedTicker, regimes } = useRegimeStore()
  const [bars, setBars] = useState<OHLCVBar[]>([])
  const [history, setHistory] = useState<RegimeHistoryRow[]>([])

  useEffect(() => {
    if (!token || !selectedTicker) return
    Promise.all([
      getOHLCV(selectedTicker, token, 252),
      getRegimeHistory(selectedTicker, token),
    ]).then(([b, h]) => { setBars(b); setHistory(h) })
      .catch(() => {})
  }, [selectedTicker, token])

  const signal = regimes[selectedTicker]

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
          {selectedTicker}
        </h2>
        {signal && (
          <RegimeBadge
            regime={signal.regime_name as RegimeName}
            confidence={signal.confidence}
          />
        )}
      </div>

      <div className="bg-panel border border-border rounded-xl overflow-hidden mb-4">
        <CandlestickChart bars={bars} regimeHistory={history} height={380} />
      </div>

      {signal && (
        <div className="bg-panel border border-border rounded-xl p-4">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Regime Probabilities
          </h3>
          <ProbabilityBar probs={signal.ensemble_prob as [number,number,number,number]} />
        </div>
      )}
    </div>
  )
}
