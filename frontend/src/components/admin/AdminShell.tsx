import { NavLink, Outlet } from 'react-router-dom';
import {
  Bell,
  Building2,
  LogOut,
  Megaphone,
  Settings,
  Shield,
  Store,
  Target,
  Users,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { logoutAccount } from '@/lib/adapter';
import { useAuth } from '@/store/auth';

type NavSection = {
  heading: string;
  items: { to: string; label: string; icon: React.ElementType; end?: boolean }[];
};

const sections: NavSection[] = [
  {
    heading: 'Platform Operations',
    items: [
      { to: '/admin', label: 'Dashboard', icon: Shield, end: true },
      { to: '/admin/outcomes', label: 'Model Intelligence', icon: Target },
      { to: '/admin/campaigns', label: 'Content Ops', icon: Megaphone },
    ],
  },
  {
    heading: 'Client Management',
    items: [
      { to: '/admin/shops', label: 'Shops', icon: Store },
      { to: '/admin/notifications', label: 'Requests & Alerts', icon: Bell },
    ],
  },
  {
    heading: 'Platform Catalog',
    items: [
      { to: '/admin/competitors', label: 'Competitor Catalog', icon: Building2 },
    ],
  },
  {
    heading: 'Tools',
    items: [
      { to: '/admin/settings', label: 'Settings', icon: Settings },
    ],
  },
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
    <div className="min-h-screen flex bg-[radial-gradient(900px_520px_at_22%_0%,hsl(28_96%_56%/.18),transparent),radial-gradient(760px_500px_at_100%_18%,hsl(152_60%_48%/.12),transparent),radial-gradient(700px_460px_at_88%_100%,hsl(0_84%_60%/.10),transparent),linear-gradient(hsl(15_18%_6%),hsl(12_16%_5%))] text-foreground">
      <aside className="hidden lg:flex w-64 shrink-0 flex-col border-r border-primary/15 bg-sidebar/80 text-sidebar-foreground backdrop-blur-xl">
        <div className="px-5 pt-6 pb-5 border-b border-sidebar-border">
          <div className="flex items-center gap-3">
            <img src="/logo.png" alt="Retail Radar AI" className="h-16 w-16 shrink-0 object-contain" />
            <div className="min-w-0">
              <div className="font-display font-bold text-sidebar-foreground text-[15px] leading-tight tracking-tight">
                Retail Radar Admin
              </div>
              <div className="text-[10.5px] uppercase tracking-[0.14em] text-sidebar-foreground/50 mt-0.5">
                Platform Operations
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto scrollbar-thin px-3 py-4 space-y-5">
          {sections.map((section) => (
            <div key={section.heading}>
              <div className="px-3 mb-1.5 text-[9.5px] font-semibold uppercase tracking-[0.18em] text-sidebar-foreground/35 select-none">
                {section.heading}
              </div>
              <div className="space-y-0.5">
                {section.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      cn(
                        'group flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium transition-all',
                        isActive
                          ? 'bg-gradient-data text-primary-foreground shadow-glow-sm outline-none'
                          : 'text-sidebar-foreground/75 hover:bg-primary/10 hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40',
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <item.icon className={cn('h-4 w-4 shrink-0', isActive ? 'text-primary-foreground' : 'text-sidebar-primary')} />
                        <span>{item.label}</span>
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="px-4 py-4 border-t border-sidebar-border">
          <div className="rounded-xl border border-primary/20 bg-gradient-to-br from-primary/15 via-decision-markdown/10 to-decision-promote/10 p-3 space-y-3">
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-full bg-gradient-data text-primary-foreground flex items-center justify-center text-[11px] font-semibold shadow-glow-sm">
                {initials(user?.full_name || user?.email || 'AD')}
              </div>
              <div className="min-w-0">
                <div className="truncate text-[12px] font-semibold text-sidebar-foreground">
                  {user?.full_name || 'Admin'}
                </div>
                <div className="truncate text-[10.5px] uppercase tracking-wider text-sidebar-foreground/50">
                  Platform Operations Manager
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-sidebar-foreground/60">
              <Users className="h-3.5 w-3.5" />
              Full platform access
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
      <div className="flex-1 min-w-0 bg-background/55 backdrop-blur-[2px]">
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
