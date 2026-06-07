import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtUSD } from '@/lib/format';
import { fetchDetailedBalanceSheet } from '@/lib/adapter';
import { cn } from '@/lib/utils';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { ArrowLeft, Edit3, RefreshCw } from 'lucide-react';
import type { DetailedBalanceSheet } from '@/types/domain';

function DataBadge({ source }: { source: 'live-db' | 'static-file' }) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 text-[10px] font-mono font-bold px-2 py-0.5 rounded-full uppercase tracking-wide',
      source === 'live-db' ? 'bg-decision-promote-bg text-decision-promote' : 'bg-amber-100 text-amber-800 border border-amber-300',
    )}>
      {source === 'live-db' ? 'Live DB' : 'Static File'}
    </span>
  );
}

function ProgressBar({ pct, color = 'bg-primary' }: { pct: number; color?: string }) {
  return (
    <div className="h-2 w-full rounded-full bg-white/10 overflow-hidden">
      <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  );
}

function AssetRow({ label, amount, total, hint, color }: {
  label: string;
  amount: number;
  total: number;
  hint?: string;
  color: string;
}) {
  const pct = total > 0 ? (amount / total) * 100 : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[13.5px]">
        <span className="text-panel-muted">{label}</span>
        <span className="font-semibold text-panel-foreground">{fmtUSD(amount)} <span className="text-[11px] text-panel-muted">({pct.toFixed(0)}%)</span></span>
      </div>
      <ProgressBar pct={pct} color={color} />
      {hint && <div className="text-[11px] text-panel-muted">{hint}</div>}
    </div>
  );
}

function SimpleRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2.5 text-[13.5px] border-b border-border last:border-0">
      <span className="text-panel-muted">{label}</span>
      <span className="font-semibold text-panel-foreground">{value}</span>
    </div>
  );
}

function RatioRow({ label, formula, value, status }: {
  label: string;
  formula: string;
  value: string;
  status: 'ok' | 'warn' | 'bad';
}) {
  const colors = { ok: 'text-decision-promote', warn: 'text-decision-markdown', bad: 'text-decision-clear' };
  return (
    <div className="flex items-center justify-between py-3 border-b border-border last:border-0 gap-4">
      <div className="min-w-0">
        <div className="text-[13px] font-semibold text-panel-foreground">{label}</div>
        <div className="text-[11.5px] text-panel-muted font-mono mt-0.5">{formula}</div>
      </div>
      <span className={cn('text-[13px] font-bold whitespace-nowrap shrink-0', colors[status])}>{value}</span>
    </div>
  );
}

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
            <button onClick={() => refetch()} disabled={isFetching} className="h-8 w-8 flex items-center justify-center rounded-md hover:bg-accent disabled:opacity-40 transition-colors" title="Refresh">
              <RefreshCw className={cn('h-4 w-4', isFetching && 'animate-spin')} />
            </button>
            <button onClick={() => navigate('/financial/update')} className="flex items-center gap-1.5 text-[13px] text-primary hover:underline transition-colors">
              <Edit3 className="h-4 w-4" /> Update
            </button>
            <button onClick={() => navigate('/financial')} className="flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground transition-colors">
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

        {data && a && l && r && (
          <>
            {data.missing_snapshot && (
              <div className="rounded-lg border border-primary/30 bg-primary/5 px-4 py-3 text-[12.5px] text-foreground flex items-center justify-between gap-4">
                <span>Add this retailer's monthly USD financial snapshot to include cash, bank balances, receivables, and liabilities.</span>
                <button onClick={() => navigate('/financial/update')} className="text-primary font-semibold hover:underline whitespace-nowrap">Update Financials</button>
              </div>
            )}

            <Section variant="panel" title="What You Own" subtitle={`Total assets: ${fmtUSD(a.total_usd)}`}>
              <div className="space-y-5">
                <AssetRow label="Stock at cost" amount={a.inventory_at_cost_usd} total={totalA} hint={`Retail value ${fmtUSD(a.inventory_at_retail_usd)}`} color="bg-primary" />
                <AssetRow label="Cash on hand" amount={a.cash_on_hand_usd} total={totalA} color="bg-decision-promote" />
                <AssetRow label="Bank / wallet USD" amount={a.bank_balance_usd} total={totalA} color="bg-decision-promote" />
                <AssetRow label="Customer receivables" amount={a.receivables_usd} total={totalA} hint="Money customers owe and you expect to collect" color="bg-primary" />
                <AssetRow label="Equipment and fixtures" amount={a.equipment_fixtures_usd} total={totalA} color="bg-muted-foreground" />
                {a.other_assets_usd > 0 && <AssetRow label="Other assets" amount={a.other_assets_usd} total={totalA} color="bg-muted-foreground" />}
              </div>
            </Section>

            <Section variant="panel" title="What You Owe" subtitle={`Total liabilities: ${fmtUSD(l.total_usd)}`}>
              <div>
                <SimpleRow label="Supplier payables" value={fmtUSD(l.supplier_payables_usd)} />
                <SimpleRow label="Rent payable" value={fmtUSD(l.rent_payable_usd)} />
                <SimpleRow label="Salary payable" value={fmtUSD(l.salary_payable_usd)} />
                <SimpleRow label="Loan balance" value={fmtUSD(l.loan_balance_usd)} />
                <SimpleRow label="Tax / VAT payable" value={fmtUSD(l.tax_vat_payable_usd)} />
                <SimpleRow label="Customer deposits" value={fmtUSD(l.customer_deposits_usd)} />
                <SimpleRow label="Other liabilities" value={fmtUSD(l.other_usd)} />
              </div>
            </Section>

            <div className="relative panel-dark rounded-xl border border-decision-promote/30 p-6 overflow-hidden">
              <div className="absolute inset-0 opacity-20" style={{ background: 'radial-gradient(620px 220px at 15% 120%, hsl(158 65% 36% / 0.45), transparent)' }} />
              <div className="relative">
                <div className="text-[12px] font-mono font-bold uppercase tracking-[0.16em] text-decision-promote mb-2">Net Worth</div>
                <div className="text-data text-[40px] text-decision-promote leading-none">{fmtUSD(data.equity_usd)}</div>
                <div className="text-[13px] text-panel-muted mt-3">{fmtUSD(a.total_usd)} total assets - {fmtUSD(l.total_usd)} liabilities = your equity</div>
              </div>
            </div>

            <Section variant="panel" title="Health Ratios" subtitle="Financial health indicators with plain-English formulas">
              <div>
                <RatioRow label="Liquidity" formula={`${fmtUSD(a.total_usd)} / ${fmtUSD(l.total_usd)}`} value={`${r.current_ratio.toFixed(2)}x`} status={r.current_ratio >= 1.5 ? 'ok' : 'warn'} />
                <RatioRow label="Stock lock-up" formula={`${fmtUSD(a.inventory_at_cost_usd)} / ${fmtUSD(a.total_usd)}`} value={`${r.inventory_pct_of_assets.toFixed(1)}% of money is in stock`} status={r.inventory_pct_of_assets > 80 ? 'warn' : 'ok'} />
                <RatioRow label="Debt burden" formula={`${fmtUSD(l.total_usd)} / ${fmtUSD(data.equity_usd)}`} value={`${r.debt_to_equity.toFixed(2)}x debt-to-equity`} status={r.debt_to_equity < 0.5 ? 'ok' : r.debt_to_equity < 1 ? 'warn' : 'bad'} />
                <RatioRow label="Concentration risk" formula="Top 5 SKUs as percent of inventory value" value={`${r.top5_concentration_pct.toFixed(0)}% concentrated in top 5`} status={r.top5_concentration_pct > 60 ? 'warn' : 'ok'} />
              </div>
            </Section>
          </>
        )}
      </main>
    </>
  );
}
