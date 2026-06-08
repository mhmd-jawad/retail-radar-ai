import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  BarChart, Bar, ScatterChart, Scatter, LineChart, Line,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine,
} from 'recharts';
import {
  Activity, CheckCircle2, ChevronRight, Clock, DollarSign,
  Loader2, RefreshCw, Target,
} from 'lucide-react';
import { AdminHeader } from './AdminDashboard';
import { fetchAdminOutcomes, triggerAdminMeasurement, impersonateShop } from '@/lib/adapter';
import { useAuth } from '@/store/auth';
import { fmtUSD } from '@/lib/format';
import type { AdminOutcomesAggregate } from '@/types/domain';
import { cn } from '@/lib/utils';

const DECISION_COLORS: Record<string, string> = {
  PROMOTE: 'hsl(152 60% 48%)',
  MARKDOWN: 'hsl(28 96% 56%)',
  CLEAR: 'hsl(358 80% 58%)',
  HOLD: 'hsl(32 12% 62%)',
};

export default function AdminOutcomes() {
  const [data, setData] = useState<AdminOutcomesAggregate | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState<number | null>(null);
  const startImpersonation = useAuth((s) => s.startImpersonation);

  const load = () => {
    setLoading(true);
    fetchAdminOutcomes()
      .then(setData)
      .catch((e) => toast.error(e?.message || 'Failed to load outcome data'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  async function handleTrigger(snapshotId: number, windowDays: 7 | 14) {
    setTriggering(snapshotId);
    try {
      await triggerAdminMeasurement(snapshotId, windowDays);
      toast.success(`${windowDays}d measurement triggered`);
      load();
    } catch (e: any) {
      toast.error(e?.message || 'Failed to trigger measurement');
    } finally {
      setTriggering(null);
    }
  }

  async function handleViewShop(tenantId: string) {
    try {
      const resp = await impersonateShop(tenantId);
      startImpersonation(resp.access_token, resp.user);
      window.location.href = '/overview';
    } catch (e: any) {
      toast.error(e?.message || 'Could not impersonate shop');
    }
  }

  const byTypeData = data
    ? Object.entries(data.by_decision_type).map(([type, v]) => ({
        type,
        accuracy: v.avg_accuracy,
        count: v.count,
        fill: DECISION_COLORS[type] ?? 'hsl(28 96% 56%)',
      }))
    : [];

  return (
    <>
      <AdminHeader title="Model Intelligence" subtitle="Recommendation accuracy and closed-loop outcome tracking across all shops" />
      <main className="relative px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(760px_400px_at_10%_0%,hsl(152_60%_48%/.10),transparent),radial-gradient(640px_360px_at_90%_20%,hsl(28_96%_56%/.08),transparent)]" />

        {/* Hero banner */}
        <section className="relative overflow-hidden rounded-2xl border border-decision-promote/25 bg-gradient-to-br from-decision-promote/20 via-decision-promote/5 to-transparent p-6 shadow-lg-soft">
          <div className="absolute inset-0 bg-[radial-gradient(620px_260px_at_8%_30%,hsl(152_60%_48%/.25),transparent)]" />
          <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-decision-promote/30 bg-decision-promote/10 px-3 py-1 text-[11px] font-mono uppercase tracking-[0.16em] text-decision-promote">
                <Target className="h-3.5 w-3.5" /> Model Intelligence
              </div>
              <h2 className="mt-4 font-display text-3xl font-bold tracking-tight">
                Is the AI actually moving the needle?
              </h2>
              <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
                Track recommendation accuracy, confidence calibration, and real revenue impact across every shop on the platform.
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
            <Loader2 className="h-5 w-5 animate-spin" /> Loading platform outcomes…
          </div>
        ) : data ? (
          <>
            {/* KPI strip */}
            <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
              <KpiCard icon={Activity} label="Total Decisions" value={String(data.total_decisions)} tone="warm" />
              <KpiCard icon={Target} label="Platform Accuracy" value={`${data.avg_accuracy_pct.toFixed(1)}%`} tone="green" />
              <KpiCard icon={Clock} label="Pending Measurements" value={String(data.pending_measurements)} tone="amber" />
              <KpiCard icon={DollarSign} label="Revenue Impact (14d)" value={fmtUSD(data.total_revenue_impact_usd, { compact: true })} tone="green" />
            </div>

            <div className="grid xl:grid-cols-2 gap-6">
              {/* Accuracy by decision type */}
              <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
                <h3 className="font-semibold text-[14px] mb-1">Accuracy by Decision Type</h3>
                <p className="text-[12px] text-muted-foreground mb-4">Avg accuracy % per recommendation category</p>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={byTypeData} layout="vertical" barCategoryGap="28%">
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" horizontal={false} />
                    <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
                    <YAxis type="category" dataKey="type" tick={{ fontSize: 12 }} width={68} />
                    <Tooltip
                      formatter={(v: number) => [`${v.toFixed(1)}%`, 'Avg Accuracy']}
                      contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                    />
                    <Bar dataKey="accuracy" fill="hsl(28 96% 56%)" radius={[0, 4, 4, 0]}
                      label={{ position: 'right', fontSize: 11, formatter: (v: number) => `${v.toFixed(0)}%` }}
                    />
                  </BarChart>
                </ResponsiveContainer>
                <div className="mt-3 flex flex-wrap gap-3">
                  {byTypeData.map((d) => (
                    <span key={d.type} className="text-[11px] text-muted-foreground">
                      <span className="font-semibold text-foreground">{d.type}</span> — {d.count} decisions
                    </span>
                  ))}
                </div>
              </div>

              {/* Confidence calibration scatter */}
              <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
                <h3 className="font-semibold text-[14px] mb-1">Confidence Calibration</h3>
                <p className="text-[12px] text-muted-foreground mb-4">IE2 confidence (X) vs actual accuracy (Y) — diagonal = perfect calibration</p>
                <ResponsiveContainer width="100%" height={200}>
                  <ScatterChart margin={{ top: 4, right: 12, bottom: 4, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis dataKey="confidence" type="number" domain={[0, 1]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} name="Confidence" />
                    <YAxis dataKey="accuracy" type="number" domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} name="Accuracy" />
                    <ReferenceLine stroke="hsl(var(--muted-foreground))" strokeDasharray="4 4"
                      segment={[{ x: 0, y: 0 }, { x: 1, y: 100 }]}
                    />
                    <Tooltip
                      cursor={{ strokeDasharray: '3 3' }}
                      formatter={(v: number, name: string) => [name === 'confidence' ? `${(v * 100).toFixed(0)}%` : `${v.toFixed(1)}%`, name]}
                      contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                    />
                    <Scatter data={data.calibration} fill="hsl(28 96% 56%)" fillOpacity={0.6} />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* 30-day accuracy trend */}
            <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
              <h3 className="font-semibold text-[14px] mb-1">30-Day Accuracy Trend</h3>
              <p className="text-[12px] text-muted-foreground mb-4">Rolling daily average accuracy across all tenants</p>
              <ResponsiveContainer width="100%" height={140}>
                <LineChart data={data.accuracy_trend} margin={{ top: 4, right: 12, bottom: 4, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(5)} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
                  <Tooltip
                    formatter={(v: number) => [`${v.toFixed(1)}%`, 'Avg Accuracy']}
                    contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                  />
                  <Line type="monotone" dataKey="avg_accuracy" stroke="hsl(152 60% 48%)" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Pending measurements */}
            {data.pending.length > 0 && (
              <div className="rounded-xl border border-decision-markdown/30 bg-decision-markdown-bg/40 p-5 shadow-sm-soft">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="font-semibold text-[14px]">Pending Measurements</h3>
                    <p className="text-[12px] text-muted-foreground">Snapshots due for 7d or 14d outcome check</p>
                  </div>
                  <span className="h-6 px-2.5 rounded-full bg-decision-markdown/20 text-decision-markdown text-[11px] font-semibold flex items-center">
                    {data.pending.length} due
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]">
                    <thead>
                      <tr className="border-b border-border">
                        {['Shop', 'Product', 'Decision', 'Window', 'Due', 'Action'].map((h) => (
                          <th key={h} className="text-left pb-2 font-semibold text-[11px] uppercase tracking-wide text-muted-foreground pr-4">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/50">
                      {data.pending.map((row) => (
                        <tr key={row.snapshot_id} className="hover:bg-muted/20 transition">
                          <td className="py-2.5 pr-4 font-medium">{row.tenant_name}</td>
                          <td className="py-2.5 pr-4 text-muted-foreground">{row.product_name}</td>
                          <td className="py-2.5 pr-4">
                            <span style={{ color: DECISION_COLORS[row.decision_type] }} className="font-semibold text-[11px]">{row.decision_type}</span>
                          </td>
                          <td className="py-2.5 pr-4 text-muted-foreground">{row.window_days}d</td>
                          <td className="py-2.5 pr-4 text-muted-foreground text-[12px]">{new Date(row.check_due_at).toLocaleDateString()}</td>
                          <td className="py-2.5">
                            <button
                              onClick={() => handleTrigger(row.snapshot_id, row.window_days as 7 | 14)}
                              disabled={triggering === row.snapshot_id}
                              className="inline-flex items-center gap-1 h-7 px-3 rounded-md bg-primary/15 text-primary text-[12px] font-semibold hover:bg-primary/25 transition disabled:opacity-50"
                            >
                              {triggering === row.snapshot_id ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                              Trigger
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Per-tenant performance */}
            <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
              <h3 className="font-semibold text-[14px] mb-1">Client Performance</h3>
              <p className="text-[12px] text-muted-foreground mb-4">Recommendation accuracy and revenue impact per shop</p>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="border-b border-border">
                      {['Shop', 'Decisions', 'Avg Accuracy', 'Revenue Impact', 'Last Decision', ''].map((h) => (
                        <th key={h} className="text-left pb-2 font-semibold text-[11px] uppercase tracking-wide text-muted-foreground pr-4">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/50">
                    {data.per_tenant.map((row) => (
                      <tr key={row.tenant_id} className="hover:bg-muted/20 transition">
                        <td className="py-2.5 pr-4 font-medium">{row.tenant_name}</td>
                        <td className="py-2.5 pr-4 text-muted-foreground">{row.decisions}</td>
                        <td className="py-2.5 pr-4">
                          <AccuracyBadge value={row.avg_accuracy} />
                        </td>
                        <td className="py-2.5 pr-4">
                          <span className={row.revenue_delta_usd >= 0 ? 'text-decision-promote' : 'text-decision-clear'}>
                            {row.revenue_delta_usd >= 0 ? '+' : ''}{fmtUSD(row.revenue_delta_usd, { compact: true })}
                          </span>
                        </td>
                        <td className="py-2.5 pr-4 text-muted-foreground text-[12px]">
                          {row.last_decision_at ? new Date(row.last_decision_at).toLocaleDateString() : '—'}
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
                    {data.per_tenant.length === 0 && (
                      <tr><td colSpan={6} className="py-8 text-center text-muted-foreground text-[13px]">No outcome data yet — decisions will appear here after shops approve recommendations.</td></tr>
                    )}
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

function KpiCard({ icon: Icon, label, value, tone }: { icon: any; label: string; value: string; tone: 'warm' | 'green' | 'amber' | 'red' }) {
  const tones = {
    warm: 'from-primary/28 via-primary/10 to-primary-glow/12 border-primary/35 text-primary',
    green: 'from-decision-promote/24 via-decision-promote/10 to-decision-promote/5 border-decision-promote/35 text-decision-promote',
    amber: 'from-decision-markdown/26 via-decision-markdown/10 to-decision-markdown/5 border-decision-markdown/35 text-decision-markdown',
    red: 'from-decision-clear/24 via-decision-clear/10 to-decision-clear/5 border-decision-clear/35 text-decision-clear',
  };
  return (
    <div className={`relative overflow-hidden rounded-xl border bg-gradient-to-br ${tones[tone]} bg-card p-5 shadow-sm-soft`}>
      <div className="absolute inset-x-0 top-0 h-1 bg-current/60" />
      <div className="flex items-center justify-between mb-3">
        <div className="text-[12px] uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="rounded-lg bg-background/45 p-2"><Icon className="h-4 w-4 text-current" /></div>
      </div>
      <div className="text-data text-[28px] font-bold leading-none">{value}</div>
    </div>
  );
}

function AccuracyBadge({ value }: { value: number }) {
  const color = value >= 75 ? 'text-decision-promote' : value >= 50 ? 'text-decision-markdown' : 'text-decision-clear';
  return <span className={cn('font-semibold', color)}>{value.toFixed(1)}%</span>;
}
