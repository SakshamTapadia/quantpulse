'use client'
import { useState } from 'react'

const REGIME_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

async function getAuthToken(): Promise<string> {
  const body = new URLSearchParams({ username: 'admin', password: 'changeme' })
  const res = await fetch(`${REGIME_URL}/auth/token`, { method: 'POST', body })
  if (!res.ok) throw new Error('Auth failed')
  const data = await res.json()
  return data.access_token
}

async function triggerAction(endpoint: string, token: string): Promise<unknown> {
  const res = await fetch(`${REGIME_URL}${endpoint}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

const ACTIONS = [
  {
    label: 'Historical Backfill (5y)',
    endpoint: '/trigger/backfill?years=5',
    description: 'Fetch 5 years of OHLCV + macro data from Polygon/FRED and publish to Kafka. Runs in background (~5-10 min).',
    warning: true,
  },
  {
    label: 'EOD Ingestion',
    endpoint: '/trigger/eod',
    description: 'Fetch last 5 days of OHLCV + macro data. Use this to catch up after a missed market close.',
    warning: false,
  },
  {
    label: 'Retrain Models',
    endpoint: '/train',
    description: 'Retrain HMM + Transformer on all data in the feature store. Runs in background (~10-15 min).',
    warning: true,
  },
  {
    label: 'Run Inference',
    endpoint: '/infer',
    description: 'Run regime inference for all tickers from the current feature store and publish signals.',
    warning: false,
  },
]

export default function TrainingPage() {
  const [log, setLog] = useState<string[]>([])
  const [loading, setLoading] = useState<string | null>(null)

  async function run(label: string, endpoint: string) {
    setLoading(label)
    setLog((l) => [...l, `▶ ${label}...`])
    try {
      const token = await getAuthToken()
      const result = await triggerAction(endpoint, token)
      setLog((l) => [...l, `✓ ${label}: ${JSON.stringify(result)}`])
    } catch (e: unknown) {
      setLog((l) => [...l, `✗ ${label}: ${e instanceof Error ? e.message : String(e)}`])
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Training & Inference</h1>
        <p className="text-sm text-slate-500 mt-1">
          Manually trigger data ingestion, model retraining, or on-demand inference
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {ACTIONS.map(({ label, endpoint, description, warning }) => (
          <div key={endpoint} className="bg-panel border border-border rounded-xl p-5">
            <h2 className="font-semibold text-white mb-1">{label}</h2>
            <p className="text-sm text-slate-500 mb-4">{description}</p>
            <button
              onClick={() => run(label, endpoint)}
              disabled={loading !== null}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed border ${
                warning
                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:bg-amber-500/20'
                  : 'bg-accent/20 text-accent border-accent/30 hover:bg-accent/30'
              }`}
            >
              {loading === label ? 'Running...' : label}
            </button>
          </div>
        ))}
      </div>

      {log.length > 0 && (
        <div className="bg-panel border border-border rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Log</h2>
            <button
              onClick={() => setLog([])}
              className="text-xs text-slate-600 hover:text-slate-400"
            >
              Clear
            </button>
          </div>
          <div className="font-mono text-xs space-y-1 max-h-80 overflow-y-auto">
            {log.map((line, i) => (
              <div
                key={i}
                className={
                  line.startsWith('✓') ? 'text-green-400' :
                  line.startsWith('✗') ? 'text-red-400' : 'text-slate-400'
                }
              >
                {line}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
