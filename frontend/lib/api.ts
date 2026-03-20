const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
export const WS_URL  = process.env.NEXT_PUBLIC_WS_URL  ?? 'ws://localhost:8000'

// Inside Docker, server-side Next.js can't reach localhost:8000 — use internal DNS.
// INTERNAL_API_URL is set as a runtime env var on the frontend container.
function baseUrl(): string {
  if (typeof window === 'undefined') {
    return process.env.INTERNAL_API_URL ?? API_URL
  }
  return API_URL
}

// ── Types ─────────────────────────────────────────────────────────────────────

export type RegimeName = 'trending' | 'mean_reverting' | 'choppy' | 'high_vol'

export interface RegimeSignal {
  regime: 0 | 1 | 2 | 3
  regime_name: RegimeName
  confidence: number
  ensemble_prob: [number, number, number, number]
  updated_at: string
}

export interface OHLCVBar {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface Alert {
  id: number
  time: string
  ticker: string | null
  alert_type: string
  severity: 1 | 2 | 3
  payload: Record<string, unknown>
  read: boolean
}

export interface RegimeHistoryRow {
  time: string
  regime: number
  confidence: number
}

// ── Colour map ────────────────────────────────────────────────────────────────

export const REGIME_COLORS: Record<RegimeName, string> = {
  trending:       '#22c55e',
  mean_reverting: '#3b82f6',
  choppy:         '#f59e0b',
  high_vol:       '#ef4444',
}

export const REGIME_LABELS: Record<RegimeName, string> = {
  trending:       'Trending',
  mean_reverting: 'Mean-Reverting',
  choppy:         'Choppy',
  high_vol:       'High Volatility',
}

// ── Fetch helpers ─────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, token?: string): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${baseUrl()}${path}`, { headers, next: { revalidate: 30 } })
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`)
  return res.json() as Promise<T>
}

export async function getToken(username = 'admin', password = 'changeme'): Promise<string> {
  const body = new URLSearchParams({ username, password })
  const res = await fetch(`${baseUrl()}/auth/token`, { method: 'POST', body })
  if (!res.ok) throw new Error('Auth failed')
  const data = await res.json()
  return data.access_token as string
}

export async function getAllRegimes(token: string): Promise<Record<string, RegimeSignal>> {
  const data = await apiFetch<{ regimes: Record<string, RegimeSignal> }>('/api/v1/regime', token)
  return data.regimes
}

export async function getTickerRegime(ticker: string, token: string): Promise<RegimeSignal> {
  const data = await apiFetch<RegimeSignal & { ticker: string }>(`/api/v1/regime/${ticker}`, token)
  return data
}

export async function getOHLCV(ticker: string, token: string, limit = 252): Promise<OHLCVBar[]> {
  const data = await apiFetch<{ bars: OHLCVBar[] }>(`/api/v1/ohlcv/${ticker}?limit=${limit}`, token)
  return data.bars
}

export async function getRegimeHistory(ticker: string, token: string): Promise<RegimeHistoryRow[]> {
  const data = await apiFetch<{ history: RegimeHistoryRow[] }>(`/api/v1/regime/${ticker}/history`, token)
  return data.history
}

export async function getAlerts(token: string, limit = 50): Promise<Alert[]> {
  const data = await apiFetch<{ alerts: Alert[] }>(`/api/v1/alerts?limit=${limit}`, token)
  return data.alerts
}

export async function getTickers(token: string): Promise<string[]> {
  const data = await apiFetch<{ tickers: string[] }>('/api/v1/tickers', token)
  return data.tickers
}
