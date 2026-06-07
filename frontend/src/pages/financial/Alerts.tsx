import { useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { useReport } from '@/hooks/useReport';
import { cn } from '@/lib/utils';
import { ArrowLeft, AlertTriangle, AlertCircle, Info } from 'lucide-react';
import type { Alert } from '@/types/domain';

function AlertCard({ alert }: { alert: Alert }) {
  const config = {
    critical: { icon: AlertTriangle, color: 'border-decision-clear/40 bg-decision-clear-bg', text: 'text-decision-clear',    badge: 'bg-decision-clear text-white' },
    high:     { icon: AlertTriangle, color: 'border-decision-clear/30 bg-decision-clear-bg/50', text: 'text-decision-clear', badge: 'bg-decision-clear/80 text-white' },
    medium:   { icon: AlertCircle,   color: 'border-decision-markdown/30 bg-decision-markdown-bg', text: 'text-decision-markdown', badge: 'bg-decision-markdown text-white' },
    low:      { icon: Info,          color: 'border-border bg-muted/10',  text: 'text-muted-foreground', badge: 'bg-muted text-foreground' },
  } as const;

  const sev = alert.severity in config ? alert.severity : 'low';
  const c = config[sev as keyof typeof config];
  const Icon = c.icon;

  return (
    <div className={cn('rounded-xl border p-5', c.color)}>
      <div className="flex items-start gap-3">
        <Icon className={cn('h-5 w-5 mt-0.5 shrink-0', c.text)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 mb-1">
            <h4 className={cn('font-semibold text-[13.5px]', c.text)}>{alert.title}</h4>
            <span className={cn('text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full whitespace-nowrap shrink-0', c.badge)}>
              {alert.severity}
            </span>
          </div>
          <p className="text-[13px] text-muted-foreground leading-snug">{alert.detail}</p>
          {alert.category && (
            <span className="mt-2 inline-block text-[11px] text-muted-foreground bg-muted px-2 py-0.5 rounded font-mono">
              {alert.category}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function FinancialAlerts() {
  const navigate = useNavigate();
  const { data: report, isLoading } = useReport();

  const alerts  = report?.financial.alerts ?? [];
  const grouped = {
    critical: alerts.filter(a => a.severity === 'critical'),
    high:     alerts.filter(a => a.severity === 'high'),
    medium:   alerts.filter(a => a.severity === 'medium'),
    low:      alerts.filter(a => a.severity === 'low'),
  };

  return (
    <>
      <TopBar
        title="Financial Alerts"
        subtitle={`${alerts.length} active alert${alerts.length !== 1 ? 's' : ''}`}
        actions={
          <button
            onClick={() => navigate('/financial')}
            className="flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" /> Back
          </button>
        }
      />

      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        {isLoading && <PageSkeleton />}

        {alerts.length === 0 && !isLoading && (
          <div className="rounded-xl border border-decision-promote/30 bg-decision-promote-bg p-8 text-center">
            <div className="text-[32px] mb-2">✓</div>
            <div className="text-[16px] font-semibold text-decision-promote">All Clear</div>
            <p className="text-[13px] text-muted-foreground mt-1">No active financial alerts at this time.</p>
          </div>
        )}

        {/* Critical / High first */}
        {(grouped.critical.length > 0 || grouped.high.length > 0) && (
          <div className="space-y-3">
            <h3 className="text-[12px] font-bold uppercase tracking-widest text-decision-clear">
              Urgent — {grouped.critical.length + grouped.high.length} alert{grouped.critical.length + grouped.high.length !== 1 ? 's' : ''}
            </h3>
            {[...grouped.critical, ...grouped.high].map(a => <AlertCard key={a.id} alert={a} />)}
          </div>
        )}

        {grouped.medium.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-[12px] font-bold uppercase tracking-widest text-decision-markdown">
              Review — {grouped.medium.length} alert{grouped.medium.length !== 1 ? 's' : ''}
            </h3>
            {grouped.medium.map(a => <AlertCard key={a.id} alert={a} />)}
          </div>
        )}

        {grouped.low.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-[12px] font-bold uppercase tracking-widest text-muted-foreground">
              Info — {grouped.low.length} alert{grouped.low.length !== 1 ? 's' : ''}
            </h3>
            {grouped.low.map(a => <AlertCard key={a.id} alert={a} />)}
          </div>
        )}
      </main>
    </>
  );
}
