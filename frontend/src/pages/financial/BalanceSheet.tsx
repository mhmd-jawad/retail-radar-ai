import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtUSD } from '@/lib/format';
import { fetchDetailedBalanceSheet } from '@/lib/adapter';
import { cn } from '@/lib/utils';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import type { DetailedBalanceSheet } from '@/types/domain';

// ── helpers ───────────────────────────────────────────────────────────────────
function DataBadge({ source }: { source: 'live-db' | 'static-file' }) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 text-[10px] font-mono font-bold px-2 py-0.5 rounded-full uppercase tracking-wide',
      source === 'live-db'
        ? 'bg-decision-promote-bg text-decision-promote'
        : 'bg-amber-100 text-amber-800 border border-amber-300',
    )}>
      {source === 'live-db' ? '● Live DB' : '● Static File'}
    </span>
  );
}

function ProgressBar({ pct, color = 'bg-primary' }: { pct: number; color?: string }) {
  return (
    <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
      <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  );
}

function AssetRow({ label, amount, total, hint, color }: {
  label: React.ReactNode; amount: number; total: number; hint?: string; color: string;
}) {
  const pct = total > 0 ? (amount / total) * 100 : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[13.5px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-semibold">
          {fmtUSD(amount)}{' '}
          <span className="text-[11px] text-muted-foreground">({pct.toFixed(0)}%)</span>
        </span>
      </div>
      <ProgressBar pct={pct} color={color} />
      {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

function SimpleRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2.5 text-[13.5px] border-b border-border last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-semibold">{value}</span>
    </div>
  );
}

function RatioRow({ label, formula, value, status }: {
  label: string; formula: string; value: string; status: 'ok' | 'warn' | 'bad';
}) {
  const colors = { ok: 'text-decision-promote', warn: 'text-decision-markdown', bad: 'text-decision-clear' };
  const icons  = { ok: '✓', warn: '⚠', bad: '✕' };
  return (
    <div className="flex items-center justify-between py-3 border-b border-border last:border-0 gap-4">
      <div className="min-w-0">
        <div className="text-[13px] font-semibold">{label}</div>
        <div className="text-[11.5px] text-muted-foreground font-mono mt-0.5">{formula}</div>
      </div>
      <span className={cn('text-[13px] font-bold whitespace-nowrap shrink-0', colors[status])}>
        {icons[status]} {value}
      </span>
    </div>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────
export default function FinancialBalanceSheet() {
  const navigate = useNavigate();
  const tenantScope = useTenantScopeKey();
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery<DetailedBalanceSheet>({
    queryKey: ['financial-balance-sheet', tenantScope],
    queryFn: fetchDetailedBalanceSheet,
    staleTime: 60_000,
  });

  const a = data?.assets;
  const l = data?.liabilities;
  const r = data?.ratios;
  const totalA = a?.total_usd ?? 0;

  return (
    <>
      <TopBar
        title="Balance Sheet"
        subtitle="What you own, what you owe, and what's yours"
        actions={
          <div className="flex items-center gap-2">
            {data && <DataBadge source={data.data_source} />}
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="h-8 w-8 flex items-center justify-center rounded-md hover:bg-accent disabled:opacity-40 transition-colors"
              title="Refresh"
            >
              <RefreshCw className={cn('h-4 w-4', isFetching && 'animate-spin')} />
            </button>
            <button
              onClick={() => navigate('/financial')}
              className="flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-4 w-4" /> Back
            </button>
          </div>
        }
      />

      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        {isLoading && <PageSkeleton />}

        {isError && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-5 py-6 text-center space-y-2">
            <p className="text-[14px] font-semibold text-destructive">Database unavailable</p>
            <p className="text-[12.5px] text-muted-foreground">{(error as Error)?.message ?? 'Could not connect to the database.'}</p>
            <button onClick={() => refetch()} className="mt-2 text-[12px] underline text-muted-foreground hover:text-foreground">Retry</button>
          </div>
        )}

        {data && (
          <>
            {/* Generated at */}
            {data.data_source === 'static-file' && (
              <div className="rounded-lg border border-amber-300/40 bg-amber-50/5 px-4 py-3 text-[12.5px] text-amber-700">
                {/* TODO(live-data): this data comes from financial_profile.json static file.
                    Switch to EEP Live mode to load real-time inventory values. */}
                Demo data — values from <code>financial_profile.json</code>. Switch to EEP Live for real inventory data.
              </div>
            )}

            {/* What you OWN */}
            <Section title="What You OWN" subtitle={`Total assets: ${fmtUSD(a!.total_usd)}`}>
              <div className="space-y-5">
                <AssetRow
                  label="Stock at cost"
                  amount={a!.inventory_at_cost_usd}
                  total={totalA}
                  hint={`Retail value ${fmtUSD(a!.inventory_at_retail_usd)} — markup embedded in price`}
                  color="bg-primary"
                />
                <AssetRow
                  label="Cash on hand"
                  amount={a!.cash_on_hand_usd}
                  total={totalA}
                  color="bg-decision-promote"
                />
                <AssetRow
                  label={<span>Lollar <span className="text-decision-markdown text-[10px]">⚠ trapped in banking</span></span>}
                  amount={a!.lollar_real_usd}
                  total={totalA}
                  hint={`Face value ${fmtUSD(a!.lollar_face_usd)} — real value at 15¢/$1 haircut`}
                  color="bg-decision-markdown"
                />
                {a!.other_assets_usd > 0 && (
                  <AssetRow label="Other assets" amount={a!.other_assets_usd} total={totalA} color="bg-muted-foreground" />
                )}
              </div>
            </Section>

            {/* What you OWE */}
            <Section title="What You OWE" subtitle={`Total liabilities: ${fmtUSD(l!.total_usd)}`}>
              <div>
                <SimpleRow label="Supplier Payables" value={fmtUSD(l!.supplier_payables_usd)} />
                <SimpleRow label="Other Liabilities" value={fmtUSD(l!.other_usd)} />
              </div>
            </Section>

            {/* What's YOURS */}
            <div className="rounded-xl border-2 border-decision-promote/30 bg-decision-promote-bg p-6">
              <div className="text-[12px] font-bold uppercase tracking-widest text-decision-promote mb-2">
                What's YOURS — Net Worth
              </div>
              <div className="text-[40px] font-bold font-display text-decision-promote leading-none">
                {fmtUSD(data.equity_usd)}
              </div>
              <div className="text-[13px] text-muted-foreground mt-3">
                {fmtUSD(a!.total_usd)} total assets − {fmtUSD(l!.total_usd)} liabilities = your equity
              </div>
            </div>

            {/* Health Ratios */}
            <Section title="Health Ratios" subtitle="Financial health indicators with plain-English formulas">
              <div>
                <RatioRow
                  label="Liquidity"
                  formula={`${fmtUSD(a!.total_usd)} ÷ ${fmtUSD(l!.total_usd)}`}
                  value={`${r!.current_ratio.toFixed(2)} — $${r!.current_ratio.toFixed(2)} for every $1 owed`}
                  status={r!.current_ratio >= 1.5 ? 'ok' : 'warn'}
                />
                <RatioRow
                  label="Stock lock-up"
                  formula={`${fmtUSD(a!.inventory_at_cost_usd)} ÷ ${fmtUSD(a!.total_usd)}`}
                  value={`${r!.inventory_pct_of_assets.toFixed(1)}% of your money is in stock`}
                  status={r!.inventory_pct_of_assets > 80 ? 'warn' : 'ok'}
                />
                <RatioRow
                  label="Debt burden"
                  formula={`${fmtUSD(l!.total_usd)} ÷ ${fmtUSD(data.equity_usd)}`}
                  value={`${r!.debt_to_equity.toFixed(2)}x debt-to-equity`}
                  status={r!.debt_to_equity < 0.5 ? 'ok' : r!.debt_to_equity < 1 ? 'warn' : 'bad'}
                />
                <RatioRow
                  label="Concentration risk"
                  formula="Top 5 SKUs as % of inventory value"
                  value={`${r!.top5_concentration_pct.toFixed(0)}% concentrated in top 5`}
                  status={r!.top5_concentration_pct > 60 ? 'warn' : 'ok'}
                />
              </div>
            </Section>
          </>
        )}
      </main>
    </>
  );
}
