import { REGIME_COLORS, REGIME_LABELS, RegimeName } from '@/lib/api'
import clsx from 'clsx'

interface Props {
  regime: RegimeName
  confidence?: number
  size?: 'sm' | 'md' | 'lg'
}

export function RegimeBadge({ regime, confidence, size = 'md' }: Props) {
  const color = REGIME_COLORS[regime]
  const label = REGIME_LABELS[regime]

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full font-medium',
        size === 'sm' && 'px-2 py-0.5 text-xs',
        size === 'md' && 'px-3 py-1 text-sm',
        size === 'lg' && 'px-4 py-1.5 text-base',
      )}
      style={{ backgroundColor: `${color}22`, color, border: `1px solid ${color}55` }}
    >
      <span
        className="inline-block rounded-full"
        style={{ width: 6, height: 6, backgroundColor: color }}
      />
      {label}
      {confidence !== undefined && (
        <span className="opacity-60 text-xs ml-1">{(confidence * 100).toFixed(0)}%</span>
      )}
    </span>
  )
}
