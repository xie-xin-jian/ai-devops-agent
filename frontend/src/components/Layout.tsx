import Sidebar from './Sidebar'
import Toast from './Toast'

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full overflow-hidden bg-bg-primary text-text-primary">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <main className="flex-1 overflow-hidden">{children}</main>
      </div>
      <Toast />
    </div>
  )
}
