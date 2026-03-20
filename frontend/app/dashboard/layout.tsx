import { Sidebar } from '@/components/layout/Sidebar'
import { WSProvider } from './WSProvider'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <WSProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </WSProvider>
  )
}
