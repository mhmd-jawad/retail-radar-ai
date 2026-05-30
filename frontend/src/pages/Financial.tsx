import { useNavigate } from 'react-router-dom';
import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { DataSourceBanner } from '@/components/shared/DataSourceBanner';
import { fmtPct, fmtUSD } from '@/lib/format';
import {
  Wallet, TrendingUp, Activity, AlertTriangle, DollarSign,
  BarChart3, ChevronRight, BadgeDollarSign,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// â”€â”€ hub card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
interface HubCardProps {
  to: string;
  icon: React.ElementType;
  title: string;
  metric: string;
  metricLabel: string;
  status: 'ok' | 'warn' | 'bad' | 'data';
  statusText: string;
  description: string;
}

function HubCard({ to, icon: Icon, title, metric, metricLabel, status, statusText, description }: HubCardProps) {
  const navigate = useNavigate();
  const statusColors = {
    ok:   'text-decision-promote border-decision-promote/20 bg-decision-promote-bg',
    warn: 'text-decision-markdown border-decision-markdown/20 bg-decision-markdown-bg',
    bad:  'text-decision-clear border-decision-clear/20 bg-decision-clear-bg',
    data: 'text-primary border-primary/20 bg-primary/5',
  };
  const dotColors = { ok: 'bg-decision-promote', warn: 'bg-decision-markdown', bad: 'bg-decision-clear', data: 'bg-primary' };

  return (
    <button
      onClick={() => navigate(to)}
      className="group text-left rounded-xl border border-border bg-card p-5 hover:border-primary/40 hover:shadow-md transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      <div className="flex items-start justify-between mb-4">
        <div className="h-10 w-10 rounded-lg bg-muted flex items-center justify-center group-hover:bg-primary/10 transition-colors">
          <Icon className="h-5 w-5 text-muted-foreground group-hover:text-primary transition-colors" />
        </div>
        <ChevronRight className="h-4 w-4 text-muted-foreground/40 group-hover:text-primary group-hover:translate-x-0.5 transition-all" />
      </div>

      <div className="mb-1">
        <div className="text-[22px] font-bold font-display leading-none">{metric}</div>
        <div className="text-[11px] text-muted-foreground mt-1 uppercase tracking-wide">{metricLabel}</div>
      </div>

      <div className="text-[14px] font-semibold text-foreground mt-3 mb-1">{title}</div>
      <p className="text-[12px] text-muted-foreground leading-snug mb-3">{description}</p>

      <span className={cn('inline-flex items-center gap-1.5 text-[11px] font-semibold px-2 py-1 rounded-full border', statusColors[status])}>
        <span className={cn('h-1.5 w-1.5 rounded-full', dotColors[status])} />
        {statusText}
      </span>
    </button>
  );
}

// â”€â”€ main hub page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
export default function Financial() {
  const { data: r, isLoading } = useReport();

  if (isLoading || !r) return (<><TopBar title="Financial Health" /><PageSkeleton /></>);

  const f = r.financial;
  const cashRunway   = f.cashflow_health.cash_runway_months;
  const ratio        = f.balance_sheet_health.current_ratio;
  const margin       = f.profitability.blended_margin_pct;
  const revenue      = f.profitability.annual_revenue_projection_usd;
  const equity       = f.balance_sheet_health.equity_usd;
  const lollarPct    = f.cashflow_health.lollar_exposure_pct ?? 4;
  const fixedTotal   = 3500; // TODO(live-data): derive from fetchDetailedProfitability opex_breakdown

  const alerts = f.alerts ?? [];
  const highAlerts = alerts.filter(a => a.severity === 'critical' || a.severity === 'high').length;

  return (
    <>
      <TopBar
        title="Financial Health"
        subtitle="Select a section to view detailed analysis"
      />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <DataSourceBanner />

        {/* Hub cards grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <HubCard
            to="/financial/balance-sheet"
            icon={Wallet}
            title="Balance Sheet"
            metric={fmtUSD(equity, { compact: true })}
            metricLabel="Your Net Worth"
            status={ratio >= 1.5 ? 'ok' : 'warn'}
            statusText={ratio >= 1.5 ? `Liquidity ${ratio.toFixed(2)}x âœ“` : `Liquidity ${ratio.toFixed(2)}x âš `}
            description="What you own, what you owe, and what's truly yours. Asset breakdown with health ratios."
          />
          <HubCard
            to="/financial/profitability"
            icon={TrendingUp}
            title="Profitability"
            metric={fmtPct(margin)}
            metricLabel="Blended Margin"
            status={margin >= 45 ? 'ok' : margin >= 35 ? 'warn' : 'bad'}
            statusText={margin >= 45 ? 'Above 45% floor âœ“' : margin >= 35 ? 'Watch margin floor âš ' : 'Below floor âœ•'}
            description="Margin per category, breakeven formula, and where every $100 in revenue goes."
          />
          <HubCard
            to="/financial/cashflow"
            icon={BarChart3}
            title="Cashflow"
            metric={`${cashRunway.toFixed(1)} mo`}
            metricLabel="Cash Runway"
            status={cashRunway >= 4 ? 'ok' : cashRunway >= 2 ? 'warn' : 'bad'}
            statusText={cashRunway >= 4 ? 'Runway healthy âœ“' : 'Below 4mo threshold âš '}
            description="Monthly inflow vs outflow, net position trend, and 6-month projection."
          />
          <HubCard
            to="/financial/lollar"
            icon={BadgeDollarSign}
            title="Lollar Exposure"
            metric={`${lollarPct}%`}
            metricLabel="Lollar Risk"
            status={lollarPct < 10 ? 'ok' : lollarPct < 25 ? 'warn' : 'bad'}
            statusText={lollarPct < 10 ? 'Low exposure âœ“' : 'Monitor exposure âš '}
            description="Lebanese pound trapped in banking system vs fresh USD receivables breakdown."
          />
          <HubCard
            to="/financial/costs"
            icon={Activity}
            title="Cost Breakdown"
            metric={fmtUSD(fixedTotal, { compact: true })}
            metricLabel="Fixed costs / mo"
            status="data"
            statusText="Fixed + variable"
            description="Full OpEx breakdown â€” fixed monthly costs and variable rates by category."
          />
          <HubCard
            to="/financial/alerts"
            icon={AlertTriangle}
            title="Alerts & Risks"
            metric={String(alerts.length)}
            metricLabel={alerts.length === 1 ? 'active alert' : 'active alerts'}
            status={highAlerts > 0 ? 'bad' : alerts.length > 0 ? 'warn' : 'ok'}
            statusText={highAlerts > 0 ? `${highAlerts} high severity` : alerts.length > 0 ? 'Review recommended' : 'All clear âœ“'}
            description="Financial risk flags, threshold breaches, and recommended actions."
          />
        </div>

        {/* Quick-view KPIs */}
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="text-[13px] font-semibold text-muted-foreground uppercase tracking-wide mb-4">Quick Snapshot</h3>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
            <Metric label="Annual Revenue" value={fmtUSD(revenue, { compact: true })} />
            <Metric label="Breakeven / mo" value={fmtUSD(f.profitability.breakeven_revenue_usd, { compact: true })} />
            <Metric label="OPEX Coverage" value={`${f.profitability.opex_coverage_ratio.toFixed(2)}x`} warn={f.profitability.opex_coverage_ratio < 1.2} />
            <Metric label="Top-5 Concentration" value={fmtPct(f.balance_sheet_health.inventory_concentration_top5_pct)} warn />
          </div>
        </div>
      </main>
    </>
  );
}

function Metric({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div>
      <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1">{label}</div>
      <div className={cn('text-[20px] font-bold font-display', warn ? 'text-decision-markdown' : 'text-foreground')}>{value}</div>
    </div>
  );
}
