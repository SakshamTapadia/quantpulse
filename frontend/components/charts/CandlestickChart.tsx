'use client'
import { useEffect, useRef } from 'react'
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
} from 'lightweight-charts'
import { OHLCVBar, RegimeHistoryRow, REGIME_COLORS, RegimeName } from '@/lib/api'

interface Props {
  bars: OHLCVBar[]
  regimeHistory?: RegimeHistoryRow[]
  height?: number
}

const REGIME_NAMES: RegimeName[] = ['trending', 'mean_reverting', 'choppy', 'high_vol']

export function CandlestickChart({ bars, regimeHistory = [], height = 420 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef     = useRef<IChartApi | null>(null)
  const candleRef    = useRef<ISeriesApi<'Candlestick'> | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#161b27' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e2535' },
        horzLines: { color: '#1e2535' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#1e2535' },
      timeScale: { borderColor: '#1e2535', timeVisible: true },
      width: containerRef.current.clientWidth,
      height,
    })

    const candleSeries = chart.addCandlestickSeries({
      upColor:   '#22c55e',
      downColor: '#ef4444',
      borderUpColor:   '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor:   '#22c55e',
      wickDownColor: '#ef4444',
    })

    chartRef.current  = chart
    candleRef.current = candleSeries

    const resize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth })
    }
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.remove()
    }
  }, [height])

  // Update candle data
  useEffect(() => {
    if (!candleRef.current || bars.length === 0) return
    const data: CandlestickData[] = bars.map((b) => ({
      time: b.time.split('T')[0] as any,
      open: b.open, high: b.high, low: b.low, close: b.close,
    }))
    candleRef.current.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [bars])

  // Regime background bands
  useEffect(() => {
    if (!chartRef.current || regimeHistory.length === 0) return
    // Overlay semi-transparent regime markers as price line markers
    const markers = regimeHistory.map((r) => ({
      time: r.time.split('T')[0] as any,
      position: 'aboveBar' as const,
      color: REGIME_COLORS[REGIME_NAMES[r.regime]],
      shape: 'circle' as const,
      size: 0.5,
    }))
    candleRef.current?.setMarkers(markers)
  }, [regimeHistory])

  return <div ref={containerRef} className="chart-container w-full" style={{ height }} />
}
