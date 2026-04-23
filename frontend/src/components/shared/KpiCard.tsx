import { cn } from '@/lib/utils';
import type { LucideIcon } from 'lucide-react';
import { ArrowDown, ArrowUp } from 'lucide-react';

interface Props {
  label: string;
  value: string | number;
  hint?: string;
  icon?: LucideIcon;
  trend?: { value: string; direction: 'up' | 'down' | 'flat'; positive?: boolean };
  variant?: 'default' | 'panel' | 'data' | 'warning' | 'danger' | 'success';
  className?: string;
}

export function KpiCard({ label, value, hint, icon: Icon, trend, variant = 'default', className }: Props) {
  const variants = {
    default: 'bg-card border-border',
    panel: 'panel-dark border-panel-border',
    data: 'bg-gradient-data text-primary-foreground border-transparent',
    warning: 'bg-decision-markdown-bg border-decision-markdown/20',
    danger: 'bg-decision-clear-bg border-decision-clear/20',
    success: 'bg-decision-promote-bg border-decision-promote/20',
  };

  const isDark = variant === 'panel' || variant === 'data';

  return (
    <div className={cn('relative overflow-hidden rounded-xl border p-5 shadow-sm-soft transition-shadow hover:shadow-md-soft', variants[variant], className)}>
      <div className="flex items-start justify-between gap-3">
        <div className={cn('text-[11px] font-semibold uppercase tracking-[0.14em]', isDark ? 'text-panel-muted' : 'text-muted-foreground')}>
          {label}
        </div>
        {Icon && (
          <div className={cn('h-8 w-8 rounded-md flex items-center justify-center', isDark ? 'bg-white/10 text-white' : 'bg-accent text-accent-foreground')}>
            <Icon className="h-4 w-4" />
          </div>
        )}
      </div>
      <div className={cn('text-data text-[28px] leading-none mt-3 font-semibold', isDark ? 'text-panel-foreground' : 'text-foreground')}>
        {value}
      </div>
      <div className="flex items-center gap-2 mt-2">
        {trend && (
          <span
            className={cn(
              'inline-flex items-center gap-0.5 text-[11px] font-semibold rounded px-1.5 py-0.5 font-mono',
              trend.positive === false || (trend.positive === undefined && trend.direction === 'down')
                ? 'bg-decision-clear-bg text-decision-clear'
                : 'bg-decision-promote-bg text-decision-promote'
            )}
          >
            {trend.direction === 'up' ? <ArrowUp className="h-3 w-3" /> : trend.direction === 'down' ? <ArrowDown className="h-3 w-3" /> : null}
            {trend.value}
          </span>
        )}
        {hint && (
          <span className={cn('text-[12px]', isDark ? 'text-panel-muted' : 'text-muted-foreground')}>{hint}</span>
        )}
      </div>
    </div>
  );
}
