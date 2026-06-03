import { Search, Command, Bell, ChevronDown } from 'lucide-react';
import { useSettings } from '@/store/settings';
import { useAuth } from '@/store/auth';
import { modeLabel } from '@/lib/adapter';
import { cn } from '@/lib/utils';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
  DropdownMenuLabel, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import type { DataMode } from '@/types/domain';

interface Props {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

const modes: DataMode[] = ['mock-report', 'ie2-live', 'eep-live', 'supabase-ready'];

const modeColor: Record<DataMode, string> = {
  'mock-report': 'bg-amber-100 text-amber-800 border-amber-300',
  'ie2-live': 'bg-decision-promote-bg text-decision-promote border-decision-promote/30',
  'eep-live': 'bg-accent text-accent-foreground border-primary/20',
  'supabase-ready': 'bg-secondary text-secondary-foreground border-border',
};

export function TopBar({ title, subtitle, actions }: Props) {
  const { mode, setMode } = useSettings();
  const user = useAuth((state) => state.user);

  return (
    <header className="sticky top-0 z-40 backdrop-blur-md bg-background/85 border-b border-border">
      <div className="flex items-center gap-4 px-6 lg:px-8 h-16">
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-3">
            <h1 className="font-display text-[19px] font-semibold text-foreground tracking-tight truncate">
              {title}
            </h1>
            {subtitle && (
              <p className="hidden md:block text-[13px] text-muted-foreground truncate">{subtitle}</p>
            )}
          </div>
        </div>

        <div className="hidden md:flex items-center gap-2 rounded-lg border border-border bg-surface-raised px-3 h-9 w-72 text-muted-foreground text-[13px]">
          <Search className="h-4 w-4" />
          <input
            placeholder="Search SKU, product, brand..."
            className="bg-transparent outline-none flex-1 placeholder:text-muted-foreground/70 text-foreground"
          />
          <kbd className="hidden lg:flex items-center gap-0.5 text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground/80">
            <Command className="h-2.5 w-2.5" />K
          </kbd>
        </div>

        {actions}

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              className={cn(
                'inline-flex items-center gap-1.5 h-9 px-3 rounded-md border text-[12px] font-mono uppercase tracking-wider transition-colors',
                modeColor[mode]
              )}
            >
              <span className={cn('h-1.5 w-1.5 rounded-full', mode === 'ie2-live' ? 'bg-decision-promote animate-pulse' : 'bg-current opacity-70')} />
              {modeLabel(mode)}
              <ChevronDown className="h-3 w-3" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>Data Source Mode</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {modes.map((m) => (
              <DropdownMenuItem key={m} onClick={() => setMode(m)} className="flex items-center justify-between">
                {modeLabel(m)}
                {m === mode && <span className="text-primary text-xs">●</span>}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <button className="relative h-9 w-9 rounded-md border border-border bg-surface-raised flex items-center justify-center hover:bg-muted transition-colors">
          <Bell className="h-4 w-4 text-muted-foreground" />
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-decision-clear ring-2 ring-background" />
        </button>

        <div className="hidden md:flex items-center gap-2 pl-3 border-l border-border">
          <div className="h-9 w-9 rounded-full bg-gradient-data text-primary-foreground flex items-center justify-center text-[12px] font-semibold">
            {initials(user?.full_name || user?.email || 'RR')}
          </div>
        </div>
      </div>
    </header>
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
