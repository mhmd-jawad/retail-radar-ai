import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';
import {
  AlertTriangle, ChevronRight, Loader2, RefreshCw, Wallet,
} from 'lucide-react';
import { AdminHeader } from './AdminDashboard';
import { fetchAdminFinancialOverview, impersonateShop } from '@/lib/adapter';
import { useAuth } from '@/store/auth';
import { fmtPct } from '@/lib/format';
import type { AdminFinancialOverview, AdminFinancialTenantScore } from '@/types/domain';
import { cn } from '@/lib/utils';

const MONTHS_BACK = ['3mo ago', '2mo ago', 'Last month'];

export default function AdminFinancial() {
  const [data, setData] = useState<AdminFinancialOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const startImpersonation = useAuth((s) => s.startImpersonation);

  const load = () => {
    setLoading(true);
    fetchAdminFinancialOverview()
      .then(setData)
      .catch((e) => toast.error(e?.message || 'Failed to load financial overview'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  async function handleViewShop(tenantId: string) {
    try {
      const resp = await impersonateShop(tenantId);
      startImpersonation(resp.access_token, resp.user);
      window.location.href = '/financial';
    } catch (e: any) {
      toast.error(e?.message || 'Could not impersonate shop');
    }
  }

  const hasRisk = data && data.shops_at_risk > 0;

  return (
    <>
      <AdminHeader title="Client Financial Health" subtitle="Aggregate financial health signals across all shops — health indicators only" />
      <main className="relative px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(760px_400px_at_10%_0%,hsl(28_96%_56%/.10),transparent),radial-gradient(640px_360px_at_90%_20%,hsl(152_60%_48%/.08),transparent)]" />

        {/* Risk alert banner */}
        {hasRisk && (
          <div className="relative overflow-hidden rounded-xl border border-decision-clear/40 bg-decision-clear/10 px-5 py-4 flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-decision-clear shrink-0" />
            <div>
              <span className="font-semibold text-[14px] text-decision-clear">
                {data!.shops_at_risk} {data!.shops_at_risk === 1 ? 'shop' : 'shops'} at financial risk
              </span>
              <span className="text-[13px] text-muted-foreground ml-2">Cash runway below 2 months — review below</span>
            </div>
          </div>
        )}

        {/* Hero */}
        <section className="relative overflow-hidden rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/20 via-primary/5 to-transparent p-6 shadow-lg-soft">
          <div className="absolute inset-0 bg-[radial-gradient(620px_260px_at_8%_30%,hsl(28_96%_56%/.20),transparent)]" />
          <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-[11px] font-mono uppercase tracking-[0.16em] text-primary-glow">
                <Wallet className="h-3.5 w-3.5" /> Client Financial Health
              </div>
              <h2 className="mt-4 font-display text-3xl font-bold tracking-tight">
                Monitor client financial health at a glance.
              </h2>
              <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
                Derived health scores from runway, liquidity ratio, and margin — no individual P&amp;L data exposed.
              </p>
            </div>
            <button
              onClick={load}
              disabled={loading}
              className="self-start flex items-center gap-2 h-9 px-4 rounded-md border border-border text-[13px] font-medium hover:bg-primary/10 transition disabled:opacity-50"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
              Refresh
            </button>
          </div>
        </section>

        {loading && !data ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground gap-2">
            <Loader2 className="h-5 w-5 animate-spin" /> Loading financial overview…
          </div>
        ) : data ? (
          <>
            {/* KPI strip */}
            <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
              <KpiCard label="Active Shops" value={String(data.active_shops)} tone="warm" />
              <KpiCard label="Shops at Risk" value={String(data.shops_at_risk)} tone={data.shops_at_risk > 0 ? 'red' : 'green'} />
              <KpiCard label="Avg Platform Margin" value={fmtPct(data.avg_margin_pct)} tone="green" />
              <KpiCard label="Missing Snapshots" value={String(data.missing_snapshots_this_month)} tone={data.missing_snapshots_this_month > 0 ? 'amber' : 'green'} />
            </div>

            {/* At-risk shops */}
            {data.at_risk_shops.length > 0 && (
              <div className="space-y-3">
                <h3 className="font-semibold text-[14px]">At-Risk Shops</h3>
                <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">
                  {data.at_risk_shops.map((shop) => (
                    <AtRiskCard key={shop.tenant_id} shop={shop} onView={() => handleViewShop(shop.tenant_id)} />
                  ))}
                </div>
              </div>
            )}

            {/* Platform margin trend */}
            <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
              <h3 className="font-semibold text-[14px] mb-1">Platform Margin Trend</h3>
              <p className="text-[12px] text-muted-foreground mb-4">6-month rolling average blended margin across all active shops</p>
              <ResponsiveContainer width="100%" height={140}>
                <LineChart data={data.margin_trend} margin={{ top: 4, right: 12, bottom: 4, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="month" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(0, 7)} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
                  <Tooltip
                    formatter={(v: number) => [`${v.toFixed(1)}%`, 'Avg Margin']}
                    contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                  />
                  <Line type="monotone" dataKey="avg_margin_pct" stroke="hsl(28 96% 56%)" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Health scorecard */}
            <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="font-semibold text-[14px]">Financial Health Scorecard</h3>
                  <p className="text-[12px] text-muted-foreground">Derived score 0–100 from runway (40%), liquidity ratio (30%), margin (30%)</p>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="border-b border-border">
                      {['Shop', 'Score', 'Status', 'Runway', 'Liquidity Ratio', 'Margin', 'Last Snapshot', ''].map((h) => (
                        <th key={h} className="text-left pb-2 font-semibold text-[11px] uppercase tracking-wide text-muted-foreground pr-4">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/50">
                    {data.health_scores.map((row) => (
                      <tr key={row.tenant_id} className="hover:bg-muted/20 transition">
                        <td className="py-2.5 pr-4 font-medium">{row.tenant_name}</td>
                        <td className="py-2.5 pr-4">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-16 rounded-full bg-muted/60 overflow-hidden">
                              <div
                                className={cn('h-full rounded-full', row.status === 'healthy' ? 'bg-decision-promote' : row.status === 'watch' ? 'bg-decision-markdown' : 'bg-decision-clear')}
                                style={{ width: `${row.score}%` }}
                              />
                            </div>
                            <span className="font-semibold">{row.score}</span>
                          </div>
                        </td>
                        <td className="py-2.5 pr-4">
                          <StatusBadge status={row.status} />
                        </td>
                        <td className="py-2.5 pr-4 text-muted-foreground">{row.cash_runway_months.toFixed(1)} mo</td>
                        <td className="py-2.5 pr-4 text-muted-foreground">{row.current_ratio.toFixed(2)}x</td>
                        <td className="py-2.5 pr-4 text-muted-foreground">{fmtPct(row.margin_pct)}</td>
                        <td className="py-2.5 pr-4 text-muted-foreground text-[12px]">
                          {row.last_snapshot ? row.last_snapshot.slice(0, 7) : <span className="text-decision-clear">None</span>}
                        </td>
                        <td className="py-2.5">
                          <button
                            onClick={() => handleViewShop(row.tenant_id)}
                            className="inline-flex items-center gap-1 text-[12px] text-primary hover:underline"
                          >
                            View <ChevronRight className="h-3 w-3" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Snapshot coverage */}
            <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
              <h3 className="font-semibold text-[14px] mb-1">Snapshot Coverage — Last 3 Months</h3>
              <p className="text-[12px] text-muted-foreground mb-4">Green = snapshot submitted, grey = missing</p>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left pb-2 font-semibold text-[11px] uppercase tracking-wide text-muted-foreground pr-4">Shop</th>
                      {MONTHS_BACK.map((m) => (
                        <th key={m} className="pb-2 font-semibold text-[11px] uppercase tracking-wide text-muted-foreground pr-4 text-center">{m}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/50">
                    {data.snapshot_coverage.map((row) => {
                      const submitted = new Set(row.submitted_months.map((m) => m.slice(0, 7)));
                      const threeMonths = Array.from({ length: 3 }, (_, i) => {
                        const d = new Date();
                        d.setMonth(d.getMonth() - (2 - i));
                        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
                      });
                      return (
                        <tr key={row.tenant_id} className="hover:bg-muted/20 transition">
                          <td className="py-2.5 pr-4 font-medium">{row.tenant_name}</td>
                          {threeMonths.map((m) => (
                            <td key={m} className="py-2.5 pr-4 text-center">
                              <span className={cn(
                                'inline-block h-5 w-5 rounded',
                                submitted.has(m) ? 'bg-decision-promote/30 text-decision-promote text-[10px] leading-5' : 'bg-muted/40'
                              )}>
                                {submitted.has(m) ? '✓' : ''}
                              </span>
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        ) : null}
      </main>
    </>
  );
}

function KpiCard({ label, value, tone }: { label: string; value: string; tone: 'warm' | 'green' | 'amber' | 'red' }) {
  const tones = {
    warm: 'from-primary/28 via-primary/10 to-primary-glow/12 border-primary/35',
    green: 'from-decision-promote/24 via-decision-promote/10 to-decision-promote/5 border-decision-promote/35',
    amber: 'from-decision-markdown/26 via-decision-markdown/10 to-decision-markdown/5 border-decision-markdown/35',
    red: 'from-decision-clear/24 via-decision-clear/10 to-decision-clear/5 border-decision-clear/35',
  };
  return (
    <div className={`relative overflow-hidden rounded-xl border bg-gradient-to-br ${tones[tone]} bg-card p-5 shadow-sm-soft`}>
      <div className="absolute inset-x-0 top-0 h-1 bg-current/30" />
      <div className="text-[12px] uppercase tracking-wider text-muted-foreground mb-2">{label}</div>
      <div className="text-data text-[28px] font-bold leading-none">{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: 'healthy' | 'watch' | 'at_risk' }) {
  const styles = {
    healthy: 'bg-decision-promote/15 text-decision-promote border-decision-promote/20',
    watch: 'bg-decision-markdown/15 text-decision-markdown border-decision-markdown/20',
    at_risk: 'bg-decision-clear/15 text-decision-clear border-decision-clear/20',
  };
  const labels = { healthy: 'Healthy', watch: 'Watch', at_risk: 'At Risk' };
  return (
    <span className={cn('inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border', styles[status])}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {labels[status]}
    </span>
  );
}

function AtRiskCard({ shop, onView }: { shop: AdminFinancialTenantScore; onView: () => void }) {
  return (
    <div className="rounded-xl border border-decision-clear/30 bg-decision-clear/8 p-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="font-semibold text-[14px]">{shop.tenant_name}</div>
          <StatusBadge status="at_risk" />
        </div>
        <span className="text-data text-[22px] text-decision-clear font-bold">{shop.cash_runway_months.toFixed(1)} mo</span>
      </div>
      <div className="text-[12px] text-muted-foreground mb-1">Cash runway</div>
      <div className="grid grid-cols-2 gap-2 text-[12px] mt-3">
        <div><span className="text-muted-foreground">Liquidity:</span> <span className="font-medium">{shop.current_ratio.toFixed(2)}x</span></div>
        <div><span className="text-muted-foreground">Margin:</span> <span className="font-medium">{fmtPct(shop.margin_pct)}</span></div>
      </div>
      <div className="text-[11px] text-muted-foreground mt-2">Last snapshot: {shop.last_snapshot?.slice(0, 7) ?? 'None'}</div>
      <button onClick={onView} className="mt-3 inline-flex items-center gap-1 text-[12px] text-primary hover:underline">
        View financial workspace <ChevronRight className="h-3 w-3" />
      </button>
    </div>
  );
}
