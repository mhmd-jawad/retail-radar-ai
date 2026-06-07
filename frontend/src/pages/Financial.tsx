import { useNavigate } from 'react-router-dom';
import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { DataSourceBanner } from '@/components/shared/DataSourceBanner';
import { fmtPct, fmtUSD } from '@/lib/format';
import {
  Wallet, TrendingUp, Activity, AlertTriangle,
  BarChart3, ChevronRight, LineChart, Edit3, Target,
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
      className="group relative overflow-hidden text-left rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft transition-all duration-150 hover:-translate-y-0.5 hover:border-primary/35 hover:shadow-glow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/35 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="flex items-start justify-between mb-4">
        <div className="h-10 w-10 rounded-lg border border-border bg-muted/70 flex items-center justify-center group-hover:border-primary/30 group-hover:bg-primary/10 transition-colors">
          <Icon className="h-5 w-5 text-muted-foreground group-hover:text-primary-glow transition-colors" />
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
  const navigate = useNavigate();
  const { data: r, isLoading } = useReport();

  if (isLoading || !r) return (<><TopBar title="Financial Health" /><PageSkeleton /></>);

  const f = r.financial;
  const cashRunway   = f.cashflow_health.cash_runway_months;
  const ratio        = f.balance_sheet_health.current_ratio;
  const margin       = f.profitability.blended_margin_pct;
  const revenue      = f.profitability.annual_revenue_projection_usd;
  const equity       = f.balance_sheet_health.equity_usd;
  const fixedTotal   = 3500; // TODO(live-data): derive from fetchDetailedProfitability opex_breakdown

  const alerts = f.alerts ?? [];
  const highAlerts = alerts.filter(a => a.severity === 'critical' || a.severity === 'high').length;

  return (
    <>
      <TopBar
        title="Financial Health"
        subtitle="Select a section to view detailed analysis"
        actions={
          <button
            onClick={() => navigate('/financial/update')}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-primary-glow px-3 text-[13px] font-semibold text-primary-foreground shadow-glow-sm hover:opacity-90"
          >
            <Edit3 className="h-4 w-4" /> Update Financials
          </button>
        }
      />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <DataSourceBanner />

        <div className="relative panel-dark rounded-2xl overflow-hidden shadow-lg-soft">
          <div className="absolute inset-0 opacity-30" style={{
            background: 'radial-gradient(760px 300px at 82% -20%, hsl(38 100% 62% / 0.32), transparent), radial-gradient(620px 260px at 8% 115%, hsl(158 65% 36% / 0.24), transparent)',
          }} />
          <div className="relative grid gap-6 p-6 lg:grid-cols-[1.25fr_0.9fr] lg:p-7">
            <div>
              <div className="inline-flex items-center gap-2 text-[10.5px] font-mono uppercase tracking-[0.2em] text-panel-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-decision-promote animate-pulse" /> USD Finance Control
              </div>
              <h2 className="font-display text-[28px] lg:text-[34px] leading-[1.05] font-semibold text-panel-foreground mt-3 tracking-tight">
                Track liquidity, runway, and owner equity from one monthly snapshot.
              </h2>
              <p className="text-panel-muted text-[14px] mt-3 max-w-2xl">
                Current runway is <span className="text-panel-foreground font-semibold">{cashRunway.toFixed(1)} months</span>, with equity at <span className="text-panel-foreground font-semibold">{fmtUSD(equity, { compact: true })}</span>. Keep the numbers current so recommendations reflect the retailer's real cash position.
              </p>
              <div className="flex flex-wrap gap-3 mt-5">
                <button onClick={() => navigate('/financial/update')} className="inline-flex items-center gap-2 h-10 px-4 rounded-md bg-primary-glow text-primary-foreground text-[13px] font-semibold hover:opacity-90 transition shadow-glow">
                  <Edit3 className="h-4 w-4" /> Update financials
                </button>
                <button onClick={() => navigate('/financial/progress')} className="inline-flex items-center gap-2 h-10 px-4 rounded-md border border-panel-border text-panel-foreground text-[13px] font-medium hover:bg-white/5 transition">
                  <LineChart className="h-4 w-4" /> View progress
                </button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                ['Liquidity', `${ratio.toFixed(2)}x`],
                ['Margin', fmtPct(margin)],
                ['Revenue', fmtUSD(revenue, { compact: true })],
                ['Alerts', String(alerts.length)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg border border-panel-border bg-white/5 p-4">
                  <div className="text-[10.5px] font-mono uppercase tracking-wider text-panel-muted">{label}</div>
                  <div className="text-data text-[26px] text-panel-foreground mt-1.5">{value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Hub cards grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <HubCard
            to="/financial/balance-sheet"
            icon={Wallet}
            title="Balance Sheet"
            metric={fmtUSD(equity, { compact: true })}
            metricLabel="Your Net Worth"
            status={ratio >= 1.5 ? 'ok' : 'warn'}
            statusText={ratio >= 1.5 ? `Liquidity ${ratio.toFixed(2)}x` : `Liquidity ${ratio.toFixed(2)}x watch`}
            description="What you own, what you owe, and what's truly yours. Asset breakdown with health ratios."
          />
          <HubCard
            to="/financial/profitability"
            icon={TrendingUp}
            title="Profitability"
            metric={fmtPct(margin)}
            metricLabel="Blended Margin"
            status={margin >= 45 ? 'ok' : margin >= 35 ? 'warn' : 'bad'}
            statusText={margin >= 45 ? 'Above 45% floor' : margin >= 35 ? 'Watch margin floor' : 'Below floor'}
            description="Margin per category, breakeven formula, and where every $100 in revenue goes."
          />
          <HubCard
            to="/financial/cashflow"
            icon={BarChart3}
            title="Cashflow"
            metric={`${cashRunway.toFixed(1)} mo`}
            metricLabel="Cash Runway"
            status={cashRunway >= 4 ? 'ok' : cashRunway >= 2 ? 'warn' : 'bad'}
            statusText={cashRunway >= 4 ? 'Runway healthy' : 'Below 4mo threshold'}
            description="Monthly inflow vs outflow, net position trend, and 6-month projection."
          />
          <HubCard
            to="/financial/progress"
            icon={LineChart}
            title="Progress"
            metric={fmtUSD(equity, { compact: true })}
            metricLabel="Latest Equity"
            status="data"
            statusText="Monthly USD snapshots"
            description="Track assets, liabilities, equity, cash runway, and sales versus expenses over time."
          />
          <HubCard
            to="/financial/costs"
            icon={Activity}
            title="Cost Breakdown"
            metric={fmtUSD(fixedTotal, { compact: true })}
            metricLabel="Fixed costs / mo"
            status="data"
            statusText="Fixed + variable"
            description="Full OpEx breakdown: fixed monthly costs and variable rates by category."
          />
          <HubCard
            to="/financial/alerts"
            icon={AlertTriangle}
            title="Alerts & Risks"
            metric={String(alerts.length)}
            metricLabel={alerts.length === 1 ? 'active alert' : 'active alerts'}
            status={highAlerts > 0 ? 'bad' : alerts.length > 0 ? 'warn' : 'ok'}
            statusText={highAlerts > 0 ? `${highAlerts} high severity` : alerts.length > 0 ? 'Review recommended' : 'All clear'}
            description="Financial risk flags, threshold breaches, and recommended actions."
          />
          <HubCard
            to="/financial/outcomes"
            icon={Target}
            title="Decision Outcomes"
            metric="Track"
            metricLabel="7d · 14d results"
            status="data"
            statusText="Closed-loop tracking"
            description="See whether approved AI recommendations actually moved the needle — velocity lift, revenue delta, model accuracy."
          />
        </div>

        {/* Quick-view KPIs */}
        <div className="panel-dark rounded-xl border border-panel-border p-5">
          <h3 className="text-[12px] font-mono font-semibold text-panel-muted uppercase tracking-[0.16em] mb-4">Quick Snapshot</h3>
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
      <div className="text-[11px] text-panel-muted uppercase tracking-wide mb-1">{label}</div>
      <div className={cn('text-[20px] font-bold font-display', warn ? 'text-decision-markdown' : 'text-panel-foreground')}>{value}</div>
    </div>
  );
}
