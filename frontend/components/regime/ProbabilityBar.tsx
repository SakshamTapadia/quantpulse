import { REGIME_COLORS, REGIME_LABELS, RegimeName } from '@/lib/api'

const NAMES: RegimeName[] = ['trending', 'mean_reverting', 'choppy', 'high_vol']

interface Props {
  probs: [number, number, number, number]
}

export function ProbabilityBar({ probs }: Props) {
  return (
    <div className="space-y-2">
      {NAMES.map((name, i) => {
        const pct = (probs[i] * 100).toFixed(1)
        const color = REGIME_COLORS[name]
        return (
          <div key={name} className="flex items-center gap-3">
            <div className="w-28 text-xs text-slate-400 text-right shrink-0">
              {REGIME_LABELS[name]}
            </div>
            <div className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, backgroundColor: color }}
              />
            </div>
            <div className="w-10 text-xs font-mono text-slate-300 text-right">{pct}%</div>
          </div>
        )
      })}
    </div>
  )
}
