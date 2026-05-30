import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtUSD, fmtPct } from '@/lib/format';
import { fetchDetailedProfitability } from '@/lib/adapter';
import { cn } from '@/lib/utils';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import type { DetailedProfitability } from '@/types/domain';

// ── waterfall bar ─────────────────────────────────────────────────────────────
interface WaterfallItem { label: string; amount: number; color: string; }

function WaterfallBar({ item }: { item: WaterfallItem }) {
  const isProfit = item.label === 'Net Profit';
  return (
    <div className="flex items-center gap-3">
      <div className="w-32 shrink-0 text-[12px] text-muted-foreground text-right">{item.label}</div>
      <div className="flex-1 h-8 flex items-center">
        <div
          className={cn('h-6 rounded flex items-center px-2 text-[11px] font-bold text-white', item.color)}
          style={{ width: `${Math.max(5, item.amount)}%` }}
        >
          {item.amount > 8 ? `$${item.amount.toFixed(0)}` : ''}
        </div>
        {item.amount <= 8 && (
          <span className="ml-2 text-[11px] font-bold text-foreground">${item.amount.toFixed(0)}</span>
        )}
      </div>
    </div>
  );
}

// ── category margin chart ─────────────────────────────────────────────────────
const MARGIN_COLORS = ['#3B82F6','#8B5CF6','#10B981','#F59E0B','#EF4444','#6366F1','#14B8A6','#F97316'];

// ── page ──────────────────────────────────────────────────────────────────────
export default function FinancialProfitability() {
  const navigate = useNavigate();
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery<DetailedProfitability>({
    queryKey: ['financial-profitability'],
    queryFn: fetchDetailedProfitability,
    staleTime: 60_000,
  });

  const f100 = data?.for_every_100_usd;
  const waterfall: WaterfallItem[] = f100 ? [
    { label: 'Revenue',           amount: 100,           color: 'bg-primary' },
    { label: '− Cost of Goods',   amount: f100.cogs,                  color: 'bg-decision-clear' },
    { label: '− Marketing',       amount: f100.marketing,             color: 'bg-decision-markdown' },
    { label: '− Payment Proc.',   amount: f100.payment_processing,    color: 'bg-decision-markdown/60' },
    { label: '− Logistics',       amount: f100.logistics,             color: 'bg-amber-500' },
    { label: '− Fixed OpEx',      amount: f100.fixed_opex,            color: 'bg-muted-foreground' },
    { label: 'Net Profit',        amount: f100.net_profit,            color: 'bg-decision-promote' },
  ] : [];

  return (
    <>
      <TopBar
        title="Profitability"
        subtitle="Where every dollar of revenue goes"
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
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                { label: 'Blended Margin', value: fmtPct(data.summary.blended_margin_pct), ok: data.summary.blended_margin_pct >= 45 },
                { label: 'Breakeven / mo', value: fmtUSD(data.breakeven.result_usd), ok: null },
                { label: 'OPEX Coverage', value: `${data.summary.opex_coverage_ratio.toFixed(2)}x`, ok: data.summary.opex_coverage_ratio >= 1.2 },
                { label: 'Annual Revenue', value: fmtUSD(data.summary.annual_revenue_projection_usd, { compact: true }), ok: null },
              ].map(k => (
                <div key={k.label} className="rounded-xl border border-border bg-card p-4">
                  <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1">{k.label}</div>
                  <div className={cn(
                    'text-[22px] font-bold font-display',
                    k.ok === true ? 'text-decision-promote' : k.ok === false ? 'text-decision-clear' : 'text-foreground',
                  )}>{k.value}</div>
                </div>
              ))}
            </div>

            {/* For every $100 waterfall */}
            <Section
              title="For Every $100 in Revenue"
              subtitle="Where each dollar goes across your cost structure"
            >
              <div className="space-y-3 py-1">
                {waterfall.map(w => <WaterfallBar key={w.label} item={w} />)}
              </div>
            </Section>

            {/* Breakeven formula */}
            <div className="rounded-xl border border-border bg-card p-6">
              <div className="text-[12px] font-bold uppercase tracking-widest text-muted-foreground mb-4">Breakeven Formula</div>
              <div className="text-[28px] font-bold font-display text-decision-markdown">
                {fmtUSD(data.breakeven.result_usd)}
                <span className="text-[14px] font-normal text-muted-foreground ml-2">per month</span>
              </div>
              <div className="mt-3 font-mono text-[12.5px] text-muted-foreground">
                {fmtUSD(data.breakeven.monthly_fixed_opex_usd)} fixed costs ÷ {fmtPct(data.breakeven.blended_margin_pct)} margin
              </div>
              <p className="mt-3 text-[13px] text-foreground">{data.breakeven.plain_english}</p>
              {data.breakeven.pairs_estimate && (
                <div className="mt-2 text-[12.5px] text-muted-foreground">
                  ≈ <strong>{data.breakeven.pairs_estimate}</strong> pairs of shoes per month to break even
                </div>
              )}
            </div>

            {/* Category margin bars */}
            <Section
              title="Margin by Category"
              subtitle="Gross margin percentage per product category"
            >
              <ResponsiveContainer width="100%" height={data.category_breakdown.length * 50 + 20}>
                <BarChart
                  layout="vertical"
                  data={data.category_breakdown}
                  margin={{ top: 4, right: 60, left: 100, bottom: 4 }}
                >
                  <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`} tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="category" tick={{ fontSize: 12 }} width={96} />
                  <Tooltip
                    formatter={(v: number) => [`${v.toFixed(1)}%`, 'Margin']}
                    contentStyle={{ fontSize: 12 }}
                  />
                  <Bar dataKey="margin_pct" radius={[0, 4, 4, 0]}>
                    {data.category_breakdown.map((_, i) => (
                      <Cell key={i} fill={MARGIN_COLORS[i % MARGIN_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Section>

            {/* Category table */}
            <Section title="Category Detail" bodyClassName="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="border-b border-border bg-muted/30">
                      <th className="text-left px-5 py-3 font-semibold text-muted-foreground">Category</th>
                      <th className="text-right px-5 py-3 font-semibold text-muted-foreground">SKUs</th>
                      <th className="text-right px-5 py-3 font-semibold text-muted-foreground">Revenue</th>
                      <th className="text-right px-5 py-3 font-semibold text-muted-foreground">COGS</th>
                      <th className="text-right px-5 py-3 font-semibold text-muted-foreground">Margin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.category_breakdown.map((c, i) => (
                      <tr key={i} className="border-b border-border last:border-0 hover:bg-muted/20 transition-colors">
                        <td className="px-5 py-3 font-medium">{c.category}</td>
                        <td className="px-5 py-3 text-right text-muted-foreground">{c.sku_count}</td>
                        <td className="px-5 py-3 text-right">{fmtUSD(c.revenue_usd, { compact: true })}</td>
                        <td className="px-5 py-3 text-right text-muted-foreground">{fmtUSD(c.cogs_usd, { compact: true })}</td>
                        <td className={cn(
                          'px-5 py-3 text-right font-semibold',
                          c.margin_pct >= 45 ? 'text-decision-promote' : c.margin_pct >= 35 ? 'text-decision-markdown' : 'text-decision-clear',
                        )}>
                          {fmtPct(c.margin_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          </>
        )}
      </main>
    </>
  );
}
