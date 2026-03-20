import { Suspense } from 'react'
import { getToken, getAllRegimes, getOHLCV, getAlerts, getRegimeHistory, type Alert } from '@/lib/api'
import { RegimeHeatmap } from '@/components/regime/RegimeHeatmap'
import { HeatmapInitialiser } from './HeatmapInitialiser'
import { TickerDetail } from './TickerDetail'
import { AlertFeed } from '@/components/alerts/AlertFeed'

export const dynamic = 'force-dynamic'

export default async function DashboardPage() {
  let token = ''
  let regimes: Record<string, any> = {}
  let alerts: Alert[] = []

  try {
    token = await getToken()
    ;[regimes, alerts] = await Promise.all([
      getAllRegimes(token),
      getAlerts(token, 20),
    ])
  } catch { /* API not ready yet - show empty state */ }

  return (
    <>
      {/* Hydrate Zustand store with server-fetched data */}
      <HeatmapInitialiser regimes={regimes} token={token} />

      <div className="space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-white">Market Regime Dashboard</h1>
          <p className="text-sm text-slate-500 mt-1">
            Real-time regime classification across {Object.keys(regimes).length} tickers
          </p>
        </div>

        {/* Regime summary cards */}
        <RegimeSummary regimes={regimes} />

        {/* Heatmap */}
        <section>
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Ticker Heatmap
          </h2>
          <div className="bg-panel border border-border rounded-xl p-4">
            <RegimeHeatmap />
          </div>
        </section>

        {/* Ticker detail + Alerts side by side */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <Suspense fallback={<div className="h-96 bg-panel rounded-xl animate-pulse" />}>
              <TickerDetail token={token} />
            </Suspense>
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Alert Feed
            </h2>
            <div className="bg-panel border border-border rounded-xl p-4">
              <AlertFeed alerts={alerts} />
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

function RegimeSummary({ regimes }: { regimes: Record<string, any> }) {
  const counts = { trending: 0, mean_reverting: 0, choppy: 0, high_vol: 0 }
  Object.values(regimes).forEach((r: any) => {
    if (r.regime_name in counts) counts[r.regime_name as keyof typeof counts]++
  })
  const cards = [
    { label: 'Trending',       count: counts.trending,       color: '#22c55e' },
    { label: 'Mean-Reverting', count: counts.mean_reverting, color: '#3b82f6' },
    { label: 'Choppy',         count: counts.choppy,         color: '#f59e0b' },
    { label: 'High Vol',       count: counts.high_vol,       color: '#ef4444' },
  ]
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      {cards.map(({ label, count, color }) => (
        <div key={label} className="bg-panel border border-border rounded-xl p-4">
          <div className="text-2xl font-bold text-white">{count}</div>
          <div className="text-xs mt-1" style={{ color }}>{label}</div>
        </div>
      ))}
    </div>
  )
}
