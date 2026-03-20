import { getToken, getAlerts } from '@/lib/api'
import { AlertFeed } from '@/components/alerts/AlertFeed'

export const dynamic = 'force-dynamic'

export default async function AlertsPage() {
  let alerts: Awaited<ReturnType<typeof getAlerts>> = []

  try {
    const token = await getToken()
    alerts = await getAlerts(token, 100)
  } catch { /* show empty state */ }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Alerts</h1>
        <p className="text-sm text-slate-500 mt-1">
          {alerts.length} recent alerts — regime transition events and risk flags
        </p>
      </div>

      <div className="bg-panel border border-border rounded-xl p-4">
        <AlertFeed alerts={alerts} />
      </div>
    </div>
  )
}
