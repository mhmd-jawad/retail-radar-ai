import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtUSD, fmtPct } from '@/lib/format';
import { fetchDetailedProfitability } from '@/lib/adapter';
import { cn } from '@/lib/utils';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import type { DetailedProfitability, OpExItem } from '@/types/domain';

function CostRow({ item }: { item: OpExItem }) {
  const isVar = item.type === 'variable';
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-border last:border-0 gap-4 text-[13.5px]">
      <div className="min-w-0">
        <span className="font-medium">{item.label}</span>
        {isVar && item.rate_pct != null && (
          <span className="ml-2 text-[11px] text-muted-foreground">({fmtPct(item.rate_pct)} of revenue)</span>
        )}
      </div>
      <div className="text-right shrink-0">
        <div className="font-semibold">{fmtUSD(item.amount_usd)}<span className="text-muted-foreground font-normal text-[11px]">/mo</span></div>
        <div className={cn(
          'text-[10px] uppercase tracking-wide font-semibold mt-0.5',
          isVar ? 'text-amber-600' : 'text-primary',
        )}>
          {isVar ? 'Variable' : 'Fixed'}
        </div>
      </div>
    </div>
  );
}

export default function FinancialCosts() {
  const navigate = useNavigate();
  const tenantScope = useTenantScopeKey();
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery<DetailedProfitability>({
    queryKey: ['financial-profitability', tenantScope],
    queryFn: fetchDetailedProfitability,
    staleTime: 60_000,
  });

  const fixed    = data?.opex_breakdown.filter(i => i.type === 'fixed')    ?? [];
  const variable = data?.opex_breakdown.filter(i => i.type === 'variable') ?? [];
  const totalFixed    = fixed.reduce((s, i) => s + i.amount_usd, 0);
  const totalVariable = variable.reduce((s, i) => s + i.amount_usd, 0);
  const totalMonthly  = totalFixed + totalVariable;

  return (
    <>
      <TopBar
        title="Cost Breakdown"
        subtitle="Fixed and variable operating expenses — monthly view"
        actions={
          <div className="flex items-center gap-2">
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
            {/* Summary cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="rounded-xl border border-border bg-card p-5">
                <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">Fixed Costs</div>
                <div className="text-[26px] font-bold font-display text-primary">{fmtUSD(totalFixed)}</div>
                <div className="text-[11.5px] text-muted-foreground mt-1">per month, regardless of sales</div>
              </div>
              <div className="rounded-xl border border-border bg-card p-5">
                <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">Variable Costs</div>
                <div className="text-[26px] font-bold font-display text-amber-600">{fmtUSD(totalVariable)}</div>
                <div className="text-[11.5px] text-muted-foreground mt-1">scales with revenue / sales volume</div>
              </div>
              <div className="rounded-xl border-2 border-muted bg-card p-5">
                <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">Total Monthly OpEx</div>
                <div className="text-[26px] font-bold font-display text-foreground">{fmtUSD(totalMonthly)}</div>
                <div className="text-[11.5px] text-muted-foreground mt-1">minimum spend to keep operating</div>
              </div>
            </div>

            {/* Cost split visual */}
            <div className="rounded-xl border border-border bg-card px-5 py-4">
              <div className="flex items-center justify-between text-[12px] mb-2">
                <span className="text-muted-foreground">Cost mix</span>
                <span className="font-semibold">{fmtPct((totalFixed / totalMonthly) * 100, 0)} fixed · {fmtPct((totalVariable / totalMonthly) * 100, 0)} variable</span>
              </div>
              <div className="h-4 w-full rounded-full overflow-hidden flex gap-0.5">
                <div className="h-full bg-primary rounded-l-full transition-all" style={{ width: `${(totalFixed / totalMonthly) * 100}%` }} />
                <div className="h-full bg-amber-500 rounded-r-full flex-1" />
              </div>
              <div className="flex items-center gap-4 mt-2 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-primary inline-block" /> Fixed</span>
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-500 inline-block" /> Variable</span>
              </div>
            </div>

            {/* Fixed costs */}
            <Section
              title="Fixed Costs"
              subtitle={`${fmtUSD(totalFixed)}/mo — must be covered even at zero sales`}
              action={
                <span className="text-[11px] font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full">
                  {fixed.length} items
                </span>
              }
            >
              <div>
                {fixed.map((item, i) => <CostRow key={i} item={item} />)}
                <div className="flex items-center justify-between pt-3 text-[13px] font-semibold">
                  <span>Total Fixed</span>
                  <span className="text-primary">{fmtUSD(totalFixed)}/mo</span>
                </div>
              </div>
            </Section>

            {/* Variable costs */}
            <Section
              title="Variable Costs"
              subtitle={`${fmtUSD(totalVariable)}/mo estimate — changes with sales volume`}
              action={
                <span className="text-[11px] font-semibold text-amber-700 bg-amber-100/40 px-2 py-0.5 rounded-full">
                  {variable.length} items
                </span>
              }
            >
              <div>
                {variable.map((item, i) => <CostRow key={i} item={item} />)}
                <div className="flex items-center justify-between pt-3 text-[13px] font-semibold">
                  <span>Total Variable (estimate)</span>
                  <span className="text-amber-600">{fmtUSD(totalVariable)}/mo</span>
                </div>
              </div>
            </Section>

            {/* Breakeven context */}
            <div className="rounded-xl border border-border bg-muted/20 px-5 py-4">
              <div className="text-[12px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">Breakeven Context</div>
              <p className="text-[13.5px] text-foreground">{data.breakeven.plain_english}</p>
              <div className="mt-3 grid grid-cols-2 gap-4 text-[12.5px]">
                <div>
                  <span className="text-muted-foreground">Monthly revenue needed: </span>
                  <span className="font-semibold">{fmtUSD(data.breakeven.result_usd)}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Blended margin: </span>
                  <span className="font-semibold">{fmtPct(data.breakeven.blended_margin_pct)}</span>
                </div>
              </div>
            </div>
          </>
        )}
      </main>
    </>
  );
}
