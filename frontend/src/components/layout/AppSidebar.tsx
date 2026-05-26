import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, ListChecks, Boxes, Radar, Megaphone, Wallet,
  Upload, ScrollText, Activity, Settings, Radio, Home, ExternalLink,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const grafanaUrl = import.meta.env.VITE_GRAFANA_URL ?? 'http://localhost:3001';

const sections: { label: string; items: { to: string; label: string; icon: any; badge?: string }[] }[] = [
  {
    label: 'Command',
    items: [
      { to: '/', label: 'Home', icon: Home },
      { to: '/overview', label: 'Overview', icon: LayoutDashboard },
      { to: '/queue', label: 'Recommendations', icon: ListChecks, badge: '350' },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { to: '/inventory', label: 'Inventory & Stock', icon: Boxes },
      { to: '/competitive', label: 'Competitive', icon: Radar },
      { to: '/promotions', label: 'Promotions', icon: Megaphone },
      { to: '/financial', label: 'Financial', icon: Wallet },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/upload', label: 'Upload & Batch', icon: Upload },
      { to: '/audit', label: 'Audit Trail', icon: ScrollText },
      { to: '/ops', label: 'Ops & Pipeline', icon: Activity },
      { to: '/settings', label: 'Settings', icon: Settings },
    ],
  },
];

export function AppSidebar() {
  return (
    <aside className="hidden lg:flex w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      <div className="px-5 pt-6 pb-5 border-b border-sidebar-border">
        <div className="flex items-center gap-2.5">
          <div className="relative h-9 w-9 rounded-lg bg-gradient-data shadow-glow flex items-center justify-center">
            <Radio className="h-5 w-5 text-primary-foreground" />
            <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-decision-promote animate-pulse ring-2 ring-sidebar" />
          </div>
          <div className="min-w-0">
            <div className="font-display font-bold text-sidebar-foreground text-[15px] leading-tight tracking-tight">
              Retail Radar AI
            </div>
            <div className="text-[10.5px] uppercase tracking-[0.14em] text-sidebar-foreground/50 mt-0.5">
              Powered by StylePulse
            </div>
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto scrollbar-thin px-3 py-4 space-y-6">
        {sections.map((s) => (
          <div key={s.label}>
            <div className="px-3 mb-2 text-[10.5px] font-semibold tracking-[0.16em] uppercase text-sidebar-foreground/40">
              {s.label}
            </div>
            <ul className="space-y-0.5">
              {s.items.map((it) => (
                <li key={it.to}>
                  <NavLink
                    to={it.to}
                    end={it.to === '/'}
                    className={({ isActive }) =>
                      cn(
                        'group flex items-center gap-3 rounded-md px-3 py-2 text-[13.5px] font-medium transition-all',
                        isActive
                          ? 'bg-sidebar-accent text-sidebar-accent-foreground shadow-sm'
                          : 'text-sidebar-foreground/75 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <it.icon className={cn('h-4 w-4 shrink-0', isActive && 'text-sidebar-primary')} />
                        <span className="flex-1">{it.label}</span>
                        {it.badge && (
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-sidebar-accent/60 text-sidebar-foreground/70">
                            {it.badge}
                          </span>
                        )}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="px-4 py-4 border-t border-sidebar-border">
        <div className="rounded-lg bg-sidebar-accent/40 p-3 space-y-3">
          <div>
            <div className="flex items-center gap-2 text-[11px] text-sidebar-foreground/60 mb-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-decision-promote animate-pulse" />
              ANALYTICS ENGINE
            </div>
            <div className="text-[12px] text-sidebar-foreground/85 leading-snug">
              350 SKUs - 37,102 competitor records - synced 6h ago
            </div>
          </div>
          <a
            href={grafanaUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-sidebar-primary hover:text-sidebar-primary/80 transition"
          >
            Monitoring
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </div>
    </aside>
  );
}
