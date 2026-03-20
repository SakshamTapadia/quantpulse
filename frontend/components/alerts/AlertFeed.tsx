import { Alert } from '@/lib/api'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

const SEVERITY_STYLES = {
  1: 'border-slate-600 bg-slate-800/50 text-slate-300',
  2: 'border-amber-600/50 bg-amber-900/20 text-amber-300',
  3: 'border-red-600/50 bg-red-900/20 text-red-300',
}

const SEVERITY_DOT = { 1: 'bg-slate-400', 2: 'bg-amber-400', 3: 'bg-red-400' }

interface Props { alerts: Alert[] }

export function AlertFeed({ alerts }: Props) {
  if (alerts.length === 0) {
    return <p className="text-slate-500 text-sm py-4 text-center">No alerts</p>
  }

  return (
    <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
      {alerts.map((a) => (
        <div
          key={a.id}
          className={clsx('rounded-lg border p-3', SEVERITY_STYLES[a.severity])}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className={clsx('w-2 h-2 rounded-full shrink-0 mt-0.5', SEVERITY_DOT[a.severity])} />
              <div>
                <span className="font-mono text-xs font-semibold">{a.alert_type}</span>
                {a.ticker && (
                  <span className="ml-2 font-mono text-xs opacity-70">{a.ticker}</span>
                )}
                {a.payload && typeof a.payload === 'object' && 'to_regime_name' in a.payload && (
                  <span className="ml-2 text-xs opacity-60">
                    → {String(a.payload.to_regime_name).replace('_', '-')}
                  </span>
                )}
              </div>
            </div>
            <span className="text-xs opacity-50 shrink-0">
              {formatDistanceToNow(new Date(a.time), { addSuffix: true })}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
