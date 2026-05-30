import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtUSD, fmtPct } from '@/lib/format';
import { fetchDetailedBalanceSheet } from '@/lib/adapter';
import { useReport } from '@/hooks/useReport';
import { cn } from '@/lib/utils';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import type { DetailedBalanceSheet } from '@/types/domain';

// ── page ──────────────────────────────────────────────────────────────────────
export default function FinancialLollar() {
  const navigate = useNavigate();
  const { data: report } = useReport();
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery<DetailedBalanceSheet>({
    queryKey: ['financial-balance-sheet'],
    queryFn: fetchDetailedBalanceSheet,
    staleTime: 60_000,
  });

  const lollarExposurePct = report?.financial.cashflow_health.lollar_exposure_pct ?? 4;

  // Lollar values from balance sheet
  const faceLBP   = data?.assets.lollar_face_usd ?? 0;
  const realUSD   = data?.assets.lollar_real_usd ?? 0;
  const lostUSD   = faceLBP - realUSD;
  const haircut   = faceLBP > 0 ? ((lostUSD / faceLBP) * 100) : 85;
  const totalA    = data?.assets.total_usd ?? 1;
  const lollarPctOfAssets = faceLBP > 0 ? (faceLBP / totalA) * 100 : 0;

  return (
    <>
      <TopBar
        title="Lollar Exposure"
        subtitle="Lebanese pounds trapped in the banking system"
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

        {/* What is Lollar? */}
        <div className="rounded-xl border border-amber-300/40 bg-amber-50/5 px-5 py-4 text-[13px] text-muted-foreground leading-relaxed">
          <strong className="text-foreground">What is "Lollar"?</strong> After Lebanon's 2019 financial crisis, USD deposits
          in local banks became frozen and are only withdrawable in Lebanese Pounds at an unofficial rate — worth roughly
          15¢ on the dollar. This "lollar" is treated as a distinct asset class with a significant real-value haircut.
        </div>

        {/* 3 metric cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-xl border border-border bg-card p-5">
            <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">Face Value (on paper)</div>
            <div className="text-[26px] font-bold font-display text-foreground">{fmtUSD(faceLBP)}</div>
            <div className="text-[11.5px] text-muted-foreground mt-1">What your bank statement shows</div>
          </div>
          <div className="rounded-xl border border-decision-promote/30 bg-decision-promote-bg p-5">
            <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">Real Value (recoverable)</div>
            <div className="text-[26px] font-bold font-display text-decision-promote">{fmtUSD(realUSD)}</div>
            <div className="text-[11.5px] text-muted-foreground mt-1">At ~15¢/$1 actual exchange rate</div>
          </div>
          <div className="rounded-xl border border-decision-clear/30 bg-decision-clear-bg p-5">
            <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">Lost Value (haircut)</div>
            <div className="text-[26px] font-bold font-display text-decision-clear">{fmtUSD(lostUSD)}</div>
            <div className="text-[11.5px] text-muted-foreground mt-1">{haircut.toFixed(0)}% permanent loss vs face</div>
          </div>
        </div>

        {/* Exposure bar */}
        <Section title="Lollar Exposure vs Total Portfolio">
          <div className="space-y-4">
            {/* Total portfolio bar */}
            <div>
              <div className="flex items-center justify-between text-[12px] mb-2">
                <span className="text-muted-foreground">Lollar as % of total assets</span>
                <span className="font-semibold">{lollarPctOfAssets.toFixed(1)}%</span>
              </div>
              <div className="h-4 w-full rounded-full bg-muted overflow-hidden flex">
                <div
                  className="h-full bg-decision-markdown transition-all"
                  style={{ width: `${lollarPctOfAssets}%` }}
                />
                <div className="h-full bg-decision-promote flex-1" />
              </div>
              <div className="flex items-center gap-4 mt-2 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-decision-markdown inline-block" /> Lollar</span>
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-decision-promote inline-block" /> Other assets</span>
              </div>
            </div>

            {/* Revenue exposure */}
            <div>
              <div className="flex items-center justify-between text-[12px] mb-2">
                <span className="text-muted-foreground">Lollar as % of revenue receivables</span>
                <span className={cn('font-semibold', lollarExposurePct < 10 ? 'text-decision-promote' : 'text-decision-markdown')}>
                  {fmtPct(lollarExposurePct)}
                </span>
              </div>
              <div className="h-4 w-full rounded-full bg-muted overflow-hidden">
                <div
                  className={cn('h-full transition-all', lollarExposurePct < 10 ? 'bg-decision-promote' : 'bg-decision-markdown')}
                  style={{ width: `${lollarExposurePct}%` }}
                />
              </div>
            </div>
          </div>
        </Section>

        {/* Risk assessment */}
        <Section title="Risk Assessment">
          <div className="space-y-3 text-[13.5px]">
            {[
              {
                label: 'Exposure risk',
                val: lollarExposurePct < 10 ? 'Low' : lollarExposurePct < 25 ? 'Moderate' : 'High',
                ok: lollarExposurePct < 10 ? 'ok' as const : lollarExposurePct < 25 ? 'warn' as const : 'bad' as const,
                detail: `${fmtPct(lollarExposurePct)} of receivables in lollar (threshold: <10% low, 10–25% moderate, >25% high)`,
              },
              {
                label: 'Asset concentration',
                val: lollarPctOfAssets < 5 ? 'Minimal' : lollarPctOfAssets < 15 ? 'Manageable' : 'Elevated',
                ok: lollarPctOfAssets < 5 ? 'ok' as const : lollarPctOfAssets < 15 ? 'warn' as const : 'bad' as const,
                detail: `${lollarPctOfAssets.toFixed(1)}% of your total assets are in the lollar system`,
              },
              {
                label: 'Recovery probability',
                val: 'Low',
                ok: 'bad' as const,
                detail: 'Lebanese banking crisis is unresolved — treat lollar as functionally inaccessible at face value',
              },
            ].map(r => {
              const colors = { ok: 'text-decision-promote', warn: 'text-decision-markdown', bad: 'text-decision-clear' };
              return (
                <div key={r.label} className="flex items-start gap-3 py-3 border-b border-border last:border-0">
                  <div className="w-36 shrink-0 text-muted-foreground">{r.label}</div>
                  <div>
                    <span className={cn('font-semibold', colors[r.ok])}>{r.val}</span>
                    <p className="text-[12px] text-muted-foreground mt-0.5">{r.detail}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </Section>

        {/* Action recommendations */}
        <Section title="Recommended Actions">
          <ul className="space-y-2 text-[13px]">
            {[
              'Accept lollar only at real-value rate (15¢/$1), not face value, in your financial planning',
              'Prioritize fresh USD collections from customers — avoid accumulating new lollar receivables',
              'Keep lollar holdings stable or reduce — do not increase concentration',
              'Use lollar for local LBP-denominated expenses (rent, utilities) where possible to extract value',
            ].map((a, i) => (
              <li key={i} className="flex items-start gap-2 text-muted-foreground">
                <span className="text-primary font-bold mt-0.5 shrink-0">{i + 1}.</span>
                {a}
              </li>
            ))}
          </ul>
        </Section>
      </main>
    </>
  );
}
