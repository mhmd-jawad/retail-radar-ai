import { NavLink, Outlet } from 'react-router-dom';
import {
  Bell,
  Building2,
  ListChecks,
  LogOut,
  Radio,
  Settings,
  Shield,
  Store,
  Users,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { logoutAccount } from '@/lib/adapter';
import { useAuth } from '@/store/auth';

const nav = [
  { to: '/admin', label: 'Dashboard', icon: Shield, end: true },
  { to: '/admin/shops', label: 'Shops', icon: Store },
  { to: '/admin/competitor-requests', label: 'Competitor Requests', icon: ListChecks },
  { to: '/admin/notifications', label: 'Notifications', icon: Bell },
  { to: '/admin/competitors', label: 'Competitor Catalog', icon: Building2 },
  { to: '/admin/settings', label: 'Admin Settings', icon: Settings },
];

export function AdminShell() {
  const user = useAuth((state) => state.user);
  const clearSession = useAuth((state) => state.clearSession);

  async function handleLogout() {
    try {
      await logoutAccount();
    } catch {
      // Local logout should still clear a stale or expired token.
    } finally {
      clearSession();
      window.location.href = '/login';
    }
  }

  return (
    <div className="min-h-screen flex bg-background text-foreground">
      <aside className="hidden lg:flex w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
        <div className="px-5 pt-6 pb-5 border-b border-sidebar-border">
          <div className="flex items-center gap-2.5">
            <div className="relative h-9 w-9 rounded-lg bg-gradient-data shadow-glow flex items-center justify-center">
              <Radio className="h-5 w-5 text-primary-foreground" />
            </div>
            <div className="min-w-0">
              <div className="font-display font-bold text-sidebar-foreground text-[15px] leading-tight tracking-tight">
                Retail Radar Admin
              </div>
              <div className="text-[10.5px] uppercase tracking-[0.14em] text-sidebar-foreground/50 mt-0.5">
                Control workspace
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto scrollbar-thin px-3 py-4 space-y-1">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'group flex items-center gap-3 rounded-md px-3 py-2 text-[13.5px] font-medium transition-all',
                  isActive
                    ? 'bg-sidebar-accent text-sidebar-accent-foreground shadow-sm'
                    : 'text-sidebar-foreground/75 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground',
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon className={cn('h-4 w-4 shrink-0', isActive && 'text-sidebar-primary')} />
                  <span>{item.label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="px-4 py-4 border-t border-sidebar-border">
          <div className="rounded-lg bg-sidebar-accent/40 p-3 space-y-3">
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-full bg-gradient-data text-primary-foreground flex items-center justify-center text-[11px] font-semibold">
                {initials(user?.full_name || user?.email || 'AD')}
              </div>
              <div className="min-w-0">
                <div className="truncate text-[12px] font-semibold text-sidebar-foreground">
                  {user?.full_name || 'Admin'}
                </div>
                <div className="truncate text-[10.5px] uppercase tracking-wider text-sidebar-foreground/50">
                  {user?.global_role || 'admin'}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-sidebar-foreground/60">
              <Users className="h-3.5 w-3.5" />
              Shop management and requests
            </div>
            <button
              onClick={handleLogout}
              className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-sidebar-foreground/70 hover:text-sidebar-foreground transition"
            >
              <LogOut className="h-3 w-3" />
              Logout
            </button>
          </div>
        </div>
      </aside>
      <div className="flex-1 min-w-0">
        <Outlet />
      </div>
    </div>
  );
}

function initials(value: string) {
  return value
    .split(/[\s@.]+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
}
