'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import clsx from 'clsx'
import { useRegimeStore } from '@/lib/store'

const NAV = [
  { href: '/dashboard',         label: 'Dashboard' },
  { href: '/dashboard/tickers', label: 'Tickers' },
  { href: '/dashboard/alerts',  label: 'Alerts' },
  { href: '/dashboard/training',label: 'Training' },
]

export function Sidebar() {
  const pathname = usePathname()
  const connected = useRegimeStore((s) => s.connected)

  return (
    <aside className="w-56 shrink-0 flex flex-col bg-panel border-r border-border h-screen sticky top-0">
      <div className="px-5 py-4 border-b border-border">
        <div className="font-bold text-white text-lg tracking-tight">QuantPulse</div>
        <div className="flex items-center gap-1.5 mt-1">
          <span className={clsx('w-1.5 h-1.5 rounded-full', connected ? 'bg-green-400' : 'bg-slate-500')} />
          <span className="text-xs text-slate-500">{connected ? 'Live' : 'Disconnected'}</span>
        </div>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={clsx(
              'flex items-center px-3 py-2 rounded-md text-sm transition-colors',
              pathname === href
                ? 'bg-accent/20 text-accent font-medium'
                : 'text-slate-400 hover:text-white hover:bg-white/5',
            )}
          >
            {label}
          </Link>
        ))}
      </nav>
      <div className="px-5 py-3 border-t border-border">
        <p className="text-xs text-slate-600">v0.1.0</p>
      </div>
    </aside>
  )
}
