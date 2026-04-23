import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { KpiCard } from '@/components/shared/KpiCard';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtPct, fmtUSD } from '@/lib/format';
import { Wallet, TrendingUp, Activity, AlertTriangle, DollarSign } from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar, Legend } from 'recharts';
import { cn } from '@/lib/utils';

export default function Financial() {
  const { data: r, isLoading } = useReport();
  if (isLoading || !r) return (<><TopBar title="Financial Health" /><PageSkeleton /></>);
  const f = r.financial;

  return (
    <>
      <TopBar title="Financial Health" subtitle="Cash, margin, and balance sheet posture" />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Cash Runway" icon={Wallet} variant="warning" value={`${f.cashflow_health.cash_runway_months.toFixed(1)} mo`} hint={`Cash on hand ${fmtUSD(f.cashflow_health.cash_on_hand_usd, { compact: true })}`} />
          <KpiCard label="Current Ratio" icon={Activity} value={f.balance_sheet_health.current_ratio.toFixed(2)} hint="Healthy ≥ 1.5" />
          <KpiCard label="Blended Margin" icon={TrendingUp} variant="success" value={fmtPct(f.profitability.blended_margin_pct)} hint="Floor 35%" />
          <KpiCard label="Annual Revenue" icon={DollarSign} variant="data" value={fmtUSD(f.profitability.annual_revenue_projection_usd, { compact: true })} hint="Projected 12mo" />
        </div>

        <Section title="Monthly Cashflow" subtitle="Inflow, outflow, and net position">
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={f.cashflow_health.series}>
                <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="month" stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v) => `$${Math.round(v/1000)}k`} />
                <Tooltip contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }} formatter={(v: number) => fmtUSD(v, { compact: true })} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="in" fill="hsl(var(--decision-promote))" name="Inflow" radius={[4,4,0,0]} />
                <Bar dataKey="out" fill="hsl(var(--decision-clear))" name="Outflow" radius={[4,4,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Section>

        <div className="grid lg:grid-cols-3 gap-6">
          <Section title="Balance Sheet Health">
            <div className="space-y-3">
              <Row label="Total Assets" value={fmtUSD(f.balance_sheet_health.total_assets_usd, { compact: true })} />
              <Row label="Liabilities" value={fmtUSD(f.balance_sheet_health.liabilities_usd, { compact: true })} />
              <Row label="Equity" value={fmtUSD(f.balance_sheet_health.equity_usd, { compact: true })} />
              <Row label="Inventory % of Assets" value={fmtPct(f.balance_sheet_health.inventory_pct_of_assets)} warn={f.balance_sheet_health.inventory_pct_of_assets > 70} />
              <Row label="Top-5 Concentration" value={fmtPct(f.balance_sheet_health.inventory_concentration_top5_pct)} />
            </div>
          </Section>
          <Section title="Profitability">
            <div className="space-y-3">
              <Row label="Blended Margin" value={fmtPct(f.profitability.blended_margin_pct)} good={f.profitability.blended_margin_pct >= 45} />
              <Row label="Breakeven Revenue" value={fmtUSD(f.profitability.breakeven_revenue_usd, { compact: true }) + '/mo'} />
              <Row label="Annual Projection" value={fmtUSD(f.profitability.annual_revenue_projection_usd, { compact: true })} />
              <Row label="OPEX Coverage" value={`${f.profitability.opex_coverage_ratio.toFixed(2)}x`} warn={f.profitability.opex_coverage_ratio < 1.2} />
            </div>
          </Section>
          <Section title="Lollar Exposure" subtitle="Lebanese pound vs fresh USD risk">
            <div className="rounded-lg p-5 bg-decision-promote-bg">
              <div className="text-[10.5px] uppercase font-mono text-decision-promote">Exposure</div>
              <div className="text-data text-[42px] font-bold text-decision-promote leading-none mt-2">{fmtPct(f.cashflow_health.lollar_exposure_pct)}</div>
              <p className="text-[12.5px] text-muted-foreground mt-3 leading-snug">
                96% of receivables are in fresh USD. Cash sales dominate. Generator/electricity OPEX hedged through monthly USD pre-pay.
              </p>
            </div>
          </Section>
        </div>

        <Section title="Financial Alerts & Risk Factors">
          <ul className="space-y-2">
            {f.alerts.map(a => (
              <li key={a.id} className="flex items-start gap-3 p-3 rounded-lg border border-border">
                <AlertTriangle className={cn('h-4 w-4 mt-0.5', a.severity === 'high' ? 'text-decision-clear' : a.severity === 'medium' ? 'text-decision-markdown' : 'text-muted-foreground')} />
                <div className="flex-1">
                  <div className="text-[13px] font-semibold">{a.title}</div>
                  <p className="text-[12.5px] text-muted-foreground">{a.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </Section>
      </main>
    </>
  );
}

function Row({ label, value, good, warn }: { label: string; value: string; good?: boolean; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border last:border-0">
      <span className="text-[12.5px] text-muted-foreground">{label}</span>
      <span className={cn('text-data text-[15px] font-semibold', good && 'text-decision-promote', warn && 'text-decision-markdown')}>{value}</span>
    </div>
  );
}
