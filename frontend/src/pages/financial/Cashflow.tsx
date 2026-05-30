import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtUSD } from '@/lib/format';
import { fetchCashflow } from '@/lib/adapter';
import { useReport } from '@/hooks/useReport';
import { cn } from '@/lib/utils';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts';
import type { CashflowMonth } from '@/lib/adapter';

function MonthBadge({ net }: { net: number }) {
  return (
    <span className={cn(
      'text-[11px] font-semibold px-1.5 py-0.5 rounded',
      net >= 0 ? 'bg-decision-promote-bg text-decision-promote' : 'bg-decision-clear-bg text-decision-clear',
    )}>
      {net >= 0 ? '+' : ''}{fmtUSD(net, { compact: true })}
    </span>
  );
}

export default function FinancialCashflow() {
  const navigate = useNavigate();
  const { data: report } = useReport();
  const { data, isLoading, isFetching, refetch } = useQuery<CashflowMonth[]>({
    queryKey: ['financial-cashflow'],
    queryFn: fetchCashflow,
    staleTime: 60_000,
  });

  const health = report?.financial.cashflow_health;
  const runway = health?.cash_runway_months ?? 0;

  const totalIn  = data?.reduce((s, m) => s + m.in, 0)  ?? 0;
  const totalOut = data?.reduce((s, m) => s + m.out, 0) ?? 0;
  const netTotal = totalIn - totalOut;

  return (
    <>
      <TopBar
        title="Cashflow"
        subtitle="Monthly inflow vs outflow — 6-month view"
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

        {/* Summary KPIs */}
        {health && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: 'Cash Runway',   value: `${runway.toFixed(1)} mo`,                ok: runway >= 4 },
              { label: 'Cash on Hand',  value: fmtUSD(health.cash_on_hand_usd, { compact: true }), ok: null },
              { label: 'Monthly Burn',  value: fmtUSD(health.monthly_burn_usd, { compact: true }), ok: null },
              { label: 'Monthly In',    value: fmtUSD(health.monthly_cash_in_usd, { compact: true }), ok: health.monthly_cash_in_usd >= health.monthly_burn_usd },
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
        )}

        {data && (
          <>
            {/* Runway alert */}
            {runway < 4 && (
              <div className="rounded-lg border border-decision-markdown/40 bg-decision-markdown-bg px-4 py-3 text-[13px] text-decision-markdown">
                <strong>⚠ Cash runway below 4-month threshold.</strong> At current burn rate of {fmtUSD(health?.monthly_burn_usd ?? 0)}/mo,
                you have approximately {runway.toFixed(1)} months of runway. Increase inflows or cut burn.
              </div>
            )}

            {/* Cashflow chart */}
            <Section
              title="6-Month Cashflow"
              subtitle={`Total in: ${fmtUSD(totalIn, { compact: true })} · Total out: ${fmtUSD(totalOut, { compact: true })} · Net: ${netTotal >= 0 ? '+' : ''}${fmtUSD(netTotal, { compact: true })}`}
            >
              <ResponsiveContainer width="100%" height={280}>
                <ComposedChart data={data} margin={{ top: 8, right: 24, left: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v: number, name: string) => [fmtUSD(v), name === 'in' ? 'Cash In' : name === 'out' ? 'Cash Out' : 'Net']}
                    contentStyle={{ fontSize: 12 }}
                  />
                  <Legend formatter={v => v === 'in' ? 'Cash In' : v === 'out' ? 'Cash Out' : 'Net'} />
                  <ReferenceLine y={0} stroke="hsl(var(--border))" strokeWidth={1} />
                  <Bar dataKey="in"  fill="hsl(var(--decision-promote))" opacity={0.85} radius={[3,3,0,0]} name="in"  maxBarSize={40} />
                  <Bar dataKey="out" fill="hsl(var(--decision-clear))"   opacity={0.75} radius={[3,3,0,0]} name="out" maxBarSize={40} />
                  <Line
                    type="monotone"
                    dataKey="net"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2.5}
                    dot={{ r: 4, fill: 'hsl(var(--primary))' }}
                    name="net"
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </Section>

            {/* Monthly table */}
            <Section title="Monthly Breakdown" bodyClassName="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="border-b border-border bg-muted/30">
                      <th className="text-left px-5 py-3 font-semibold text-muted-foreground">Month</th>
                      <th className="text-right px-5 py-3 font-semibold text-muted-foreground">Cash In</th>
                      <th className="text-right px-5 py-3 font-semibold text-muted-foreground">Cash Out</th>
                      <th className="text-right px-5 py-3 font-semibold text-muted-foreground">Net</th>
                      <th className="text-right px-5 py-3 font-semibold text-muted-foreground">Trend</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.map((m, i) => (
                      <tr key={i} className="border-b border-border last:border-0 hover:bg-muted/20 transition-colors">
                        <td className="px-5 py-3 font-semibold">{m.month}</td>
                        <td className="px-5 py-3 text-right text-decision-promote font-medium">{fmtUSD(m.in)}</td>
                        <td className="px-5 py-3 text-right text-decision-clear font-medium">{fmtUSD(m.out)}</td>
                        <td className="px-5 py-3 text-right"><MonthBadge net={m.net} /></td>
                        <td className="px-5 py-3 text-right text-[15px]">
                          {m.net >= 0 ? '▲' : '▼'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="bg-muted/20 font-semibold">
                      <td className="px-5 py-3 text-[12px] text-muted-foreground uppercase tracking-wide">6-Month Total</td>
                      <td className="px-5 py-3 text-right text-decision-promote">{fmtUSD(totalIn)}</td>
                      <td className="px-5 py-3 text-right text-decision-clear">{fmtUSD(totalOut)}</td>
                      <td className="px-5 py-3 text-right"><MonthBadge net={netTotal} /></td>
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </div>
            </Section>
          </>
        )}
      </main>
    </>
  );
}
