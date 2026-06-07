import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { KpiCard } from '@/components/shared/KpiCard';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fetchFinancialProgress } from '@/lib/adapter';
import { fmtUSD } from '@/lib/format';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { cn } from '@/lib/utils';
import { ArrowLeft, Edit3, Landmark, LineChart, ShieldAlert, WalletCards } from 'lucide-react';

function TrendRow({ label, value, max, tone = 'primary' }: { label: string; value: number; max: number; tone?: 'primary' | 'warn' | 'good' }) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  const color = tone === 'good' ? 'bg-decision-promote' : tone === 'warn' ? 'bg-decision-markdown' : 'bg-primary';
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[12.5px]">
        <span className="text-panel-muted">{label}</span>
        <span className="font-semibold text-panel-foreground">{fmtUSD(value)}</span>
      </div>
      <div className="h-2 rounded-full bg-white/10 overflow-hidden">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function FinancialProgress() {
  const navigate = useNavigate();
  const tenantScope = useTenantScopeKey();
  const { data = [], isLoading, isError, error } = useQuery({
    queryKey: ['financial-progress', tenantScope],
    queryFn: fetchFinancialProgress,
    staleTime: 60_000,
  });
  const latest = data[data.length - 1];
  const maxValue = Math.max(1, ...data.flatMap((item) => [item.total_assets_usd, item.total_liabilities_usd, item.monthly_sales_usd, item.monthly_expenses_usd]));

  return (
    <>
      <TopBar
        title="Financial Progress"
        subtitle="Monthly USD trend for assets, liabilities, runway, and cashflow"
        actions={
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/financial/update')} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-primary hover:underline"><Edit3 className="h-4 w-4" /> Update</button>
            <button onClick={() => navigate('/financial')} className="flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /> Back</button>
          </div>
        }
      />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        {isLoading && <PageSkeleton />}
        {isError && <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-5 py-4 text-[13px] text-destructive">{(error as Error).message}</div>}
        {!isLoading && !isError && data.length === 0 && (
          <div className="relative panel-dark rounded-2xl overflow-hidden px-6 py-9 text-center shadow-lg-soft">
            <div className="absolute inset-0 opacity-25" style={{ background: 'radial-gradient(640px 260px at 50% -20%, hsl(38 100% 62% / 0.35), transparent)' }} />
            <div className="relative">
              <div className="mx-auto mb-4 h-12 w-12 rounded-xl border border-primary/25 bg-primary/10 flex items-center justify-center shadow-glow-sm">
                <LineChart className="h-5 w-5 text-primary-glow" />
              </div>
              <div className="text-[16px] font-semibold text-panel-foreground">No financial snapshots yet</div>
              <p className="text-[13px] text-panel-muted mt-1">Add the current month to start tracking progress.</p>
              <button onClick={() => navigate('/financial/update')} className="mt-4 inline-flex h-10 items-center rounded-md bg-primary-glow px-4 text-[13px] font-semibold text-primary-foreground shadow-glow hover:opacity-90">Update Financials</button>
            </div>
          </div>
        )}
        {latest && (
          <>
            <div className="relative panel-dark rounded-2xl overflow-hidden shadow-lg-soft">
              <div className="absolute inset-0 opacity-30" style={{
                background: 'radial-gradient(740px 280px at 82% -20%, hsl(38 100% 62% / 0.32), transparent), radial-gradient(640px 260px at 5% 120%, hsl(158 65% 36% / 0.25), transparent)',
              }} />
              <div className="relative grid gap-6 p-6 lg:grid-cols-[1.2fr_0.8fr] lg:p-7">
                <div>
                  <div className="inline-flex items-center gap-2 text-[10.5px] font-mono uppercase tracking-[0.2em] text-panel-muted">
                    <span className="h-1.5 w-1.5 rounded-full bg-decision-promote" /> Monthly Finance Trail
                  </div>
                  <h2 className="font-display text-[27px] leading-tight text-panel-foreground mt-3">
                    {data.length} snapshots tracked with {fmtUSD(latest.equity_usd)} latest equity.
                  </h2>
                  <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-panel-muted">
                    Follow whether cash, liabilities, sales, and operating expenses are moving in the right direction month by month.
                  </p>
                </div>
                <div className="rounded-xl border border-panel-border bg-white/5 p-4">
                  <div className="text-[10.5px] font-mono uppercase tracking-[0.16em] text-panel-muted">Latest position</div>
                  <div className="mt-4 grid grid-cols-2 gap-3">
                    <div><div className="text-[11px] text-panel-muted">Runway</div><div className="text-data text-[24px] text-primary-glow">{latest.cash_runway_months.toFixed(1)} mo</div></div>
                    <div><div className="text-[11px] text-panel-muted">Debt/equity</div><div className="text-data text-[24px] text-panel-foreground">{latest.debt_to_equity.toFixed(2)}x</div></div>
                    <div><div className="text-[11px] text-panel-muted">Inventory</div><div className="text-data text-[24px] text-panel-foreground">{latest.inventory_pct_of_assets.toFixed(1)}%</div></div>
                    <div><div className="text-[11px] text-panel-muted">Net month</div><div className="text-data text-[24px] text-decision-promote">{fmtUSD(latest.monthly_sales_usd - latest.monthly_expenses_usd - latest.owner_draw_usd)}</div></div>
                  </div>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <KpiCard label="Assets" icon={WalletCards} variant="success" value={fmtUSD(latest.total_assets_usd)} hint="Inventory plus entered assets" />
              <KpiCard label="Liabilities" icon={ShieldAlert} variant="danger" value={fmtUSD(latest.total_liabilities_usd)} hint="Amounts owed" />
              <KpiCard label="Equity" icon={Landmark} variant="panel" value={fmtUSD(latest.equity_usd)} hint="Assets minus liabilities" />
              <KpiCard label="Runway" icon={LineChart} variant="data" value={`${latest.cash_runway_months.toFixed(1)} mo`} hint="Cash divided by monthly burn" />
            </div>

            <Section variant="panel" title="Monthly Trend" subtitle="Each row is one retailer-entered USD snapshot">
              <div className="space-y-5">
                {data.map((item) => (
                  <div key={item.period_month} className="rounded-lg border border-panel-border bg-white/[0.045] p-4 transition hover:border-primary/30 hover:bg-white/[0.07]">
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between mb-3">
                      <div className="font-semibold text-[13px] text-panel-foreground">{item.period_month.slice(0, 7)}</div>
                      <div className="text-[12px] text-panel-muted">Runway {item.cash_runway_months.toFixed(1)} mo - Inventory {item.inventory_pct_of_assets.toFixed(1)}% - Debt/equity {item.debt_to_equity.toFixed(2)}x</div>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <TrendRow label="Assets" value={item.total_assets_usd} max={maxValue} tone="good" />
                      <TrendRow label="Liabilities" value={item.total_liabilities_usd} max={maxValue} tone="warn" />
                      <TrendRow label="Sales" value={item.monthly_sales_usd} max={maxValue} tone="primary" />
                      <TrendRow label="Expenses" value={item.monthly_expenses_usd + item.owner_draw_usd} max={maxValue} tone="warn" />
                    </div>
                  </div>
                ))}
              </div>
            </Section>
          </>
        )}
      </main>
    </>
  );
}
