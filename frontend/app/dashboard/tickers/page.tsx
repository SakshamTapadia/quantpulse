import { getToken, getAllRegimes, type RegimeSignal } from '@/lib/api'
import { RegimeBadge } from '@/components/regime/RegimeBadge'
import { ProbabilityBar } from '@/components/regime/ProbabilityBar'

export const dynamic = 'force-dynamic'

export default async function TickersPage() {
  let regimes: Record<string, RegimeSignal> = {}

  try {
    const token = await getToken()
    regimes = await getAllRegimes(token)
  } catch { /* show empty state */ }

  const tickers = Object.entries(regimes).sort(([a], [b]) => a.localeCompare(b))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Tickers</h1>
        <p className="text-sm text-slate-500 mt-1">
          Regime classification for all {tickers.length} tracked instruments
        </p>
      </div>

      {tickers.length === 0 ? (
        <div className="bg-panel border border-border rounded-xl p-8 text-center text-slate-500">
          No regime data available yet. Run inference first.
        </div>
      ) : (
        <div className="bg-panel border border-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-slate-400 text-xs uppercase tracking-wider">
                <th className="text-left px-5 py-3">Ticker</th>
                <th className="text-left px-5 py-3">Regime</th>
                <th className="text-left px-5 py-3">Confidence</th>
                <th className="text-left px-5 py-3">Probabilities</th>
                <th className="text-right px-5 py-3">Updated</th>
              </tr>
            </thead>
            <tbody>
              {tickers.map(([ticker, signal]) => (
                <tr key={ticker} className="border-b border-border/50 hover:bg-white/5 transition-colors">
                  <td className="px-5 py-3 font-mono font-bold text-white">{ticker}</td>
                  <td className="px-5 py-3">
                    <RegimeBadge regime={signal.regime_name} size="sm" />
                  </td>
                  <td className="px-5 py-3 text-slate-300">
                    {(signal.confidence * 100).toFixed(1)}%
                  </td>
                  <td className="px-5 py-3 w-48">
                    <ProbabilityBar probs={signal.ensemble_prob} />
                  </td>
                  <td className="px-5 py-3 text-right text-slate-500 text-xs">
                    {new Date(signal.updated_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
