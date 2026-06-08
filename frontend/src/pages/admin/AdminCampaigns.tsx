import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';
import { ChevronRight, Loader2, Megaphone, RefreshCw } from 'lucide-react';
import { AdminHeader } from './AdminDashboard';
import { fetchAdminCampaignsOverview, impersonateShop } from '@/lib/adapter';
import { useAuth } from '@/store/auth';
import type { AdminCampaignsOverview } from '@/types/domain';
import { cn } from '@/lib/utils';

const CHANNEL_COLORS: Record<string, string> = {
  instagram: 'hsl(292 70% 60%)',
  facebook: 'hsl(220 80% 60%)',
  whatsapp: 'hsl(120 60% 45%)',
  other: 'hsl(32 12% 62%)',
};

const DECISION_COLORS: Record<string, string> = {
  PROMOTE: 'hsl(152 60% 48%)',
  MARKDOWN: 'hsl(28 96% 56%)',
  CLEAR: 'hsl(358 80% 58%)',
  UNKNOWN: 'hsl(32 12% 62%)',
};

export default function AdminCampaigns() {
  const [data, setData] = useState<AdminCampaignsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const startImpersonation = useAuth((s) => s.startImpersonation);

  const load = () => {
    setLoading(true);
    fetchAdminCampaignsOverview()
      .then(setData)
      .catch((e) => toast.error(e?.message || 'Failed to load campaigns overview'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  async function handleViewShop(tenantId: string) {
    try {
      const resp = await impersonateShop(tenantId);
      startImpersonation(resp.access_token, resp.user);
      window.location.href = '/promotions';
    } catch (e: any) {
      toast.error(e?.message || 'Could not impersonate shop');
    }
  }

  const channelPieData = data
    ? Object.entries(data.by_channel).map(([channel, count]) => ({
        name: channel.charAt(0).toUpperCase() + channel.slice(1),
        value: count,
        color: CHANNEL_COLORS[channel.toLowerCase()] ?? CHANNEL_COLORS.other,
      }))
    : [];

  const decisionBarData = data
    ? Object.entries(data.by_decision_type).map(([type, count]) => ({ type, count }))
    : [];

  return (
    <>
      <AdminHeader title="Content Operations" subtitle="Campaign activity, channel adoption, and AI generation health across all shops" />
      <main className="relative px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(760px_400px_at_10%_0%,hsl(292_70%_60%/.08),transparent),radial-gradient(640px_360px_at_90%_20%,hsl(28_96%_56%/.08),transparent)]" />

        {/* Hero */}
        <section className="relative overflow-hidden rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/20 via-decision-promote/5 to-transparent p-6 shadow-lg-soft">
          <div className="absolute inset-0 bg-[radial-gradient(620px_260px_at_8%_30%,hsl(28_96%_56%/.20),transparent)]" />
          <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-[11px] font-mono uppercase tracking-[0.16em] text-primary-glow">
                <Megaphone className="h-3.5 w-3.5" /> Content Operations
              </div>
              <h2 className="mt-4 font-display text-3xl font-bold tracking-tight">
                Are shops using the AI campaign engine?
              </h2>
              <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
                Monitor campaign volume, channel adoption, and IE3 generation quality across the platform.
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
            <Loader2 className="h-5 w-5 animate-spin" /> Loading campaigns data…
          </div>
        ) : data ? (
          <>
            {/* KPI strip */}
            <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
              <KpiCard label="Total Campaigns" value={String(data.total_campaigns)} tone="warm" />
              <KpiCard label="Last 30 Days" value={String(data.last_30_days)} tone="green" />
              <KpiCard label="Channels Live" value={String(data.channels_live)} tone="amber" />
              <KpiCard
                label="IE3 Fallback Rate"
                value={`${data.fallback_rate_pct.toFixed(1)}%`}
                tone={data.fallback_rate_pct > 20 ? 'red' : 'green'}
              />
            </div>

            <div className="grid xl:grid-cols-2 gap-6">
              {/* Channel donut */}
              <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
                <h3 className="font-semibold text-[14px] mb-1">Campaigns by Channel</h3>
                <p className="text-[12px] text-muted-foreground mb-2">Distribution of generated campaigns per platform</p>
                {channelPieData.length > 0 ? (
                  <>
                    <ResponsiveContainer width="100%" height={180}>
                      <PieChart>
                        <Pie
                          data={channelPieData}
                          cx="50%"
                          cy="50%"
                          innerRadius={48}
                          outerRadius={72}
                          dataKey="value"
                          paddingAngle={3}
                        >
                          {channelPieData.map((entry, idx) => (
                            <Cell key={idx} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip
                          formatter={(v: number) => [v, 'Campaigns']}
                          contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="flex flex-wrap justify-center gap-3 mt-1">
                      {channelPieData.map((d) => (
                        <div key={d.name} className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
                          <span className="h-2 w-2 rounded-full" style={{ background: d.color }} />
                          {d.name} ({d.value})
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="py-12 text-center text-[13px] text-muted-foreground">No campaign data yet</div>
                )}
              </div>

              {/* Decision type bar */}
              <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
                <h3 className="font-semibold text-[14px] mb-1">Campaigns by Decision Type</h3>
                <p className="text-[12px] text-muted-foreground mb-4">Which decisions generate the most content</p>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={decisionBarData} barCategoryGap="32%">
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis dataKey="type" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip
                      formatter={(v: number) => [v, 'Campaigns']}
                      contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {decisionBarData.map((d, i) => (
                        <Cell key={i} fill={DECISION_COLORS[d.type] ?? DECISION_COLORS.UNKNOWN} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Fallback rate trend */}
            {data.fallback_trend.length > 0 && (
              <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
                <h3 className="font-semibold text-[14px] mb-1">IE3 Fallback Rate — 30 Days</h3>
                <p className="text-[12px] text-muted-foreground mb-4">% of campaigns using template fallback copy — spike indicates generation service issues</p>
                <ResponsiveContainer width="100%" height={130}>
                  <LineChart data={data.fallback_trend} margin={{ top: 4, right: 12, bottom: 4, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(5)} />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
                    <Tooltip
                      formatter={(v: number) => [`${v.toFixed(1)}%`, 'Fallback Rate']}
                      contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                    />
                    <Line type="monotone" dataKey="fallback_rate_pct" stroke="hsl(358 80% 58%)" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Per-tenant activity */}
            <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
              <h3 className="font-semibold text-[14px] mb-1">Per-Shop Campaign Activity</h3>
              <p className="text-[12px] text-muted-foreground mb-4">Campaign volume and channel usage per tenant</p>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="border-b border-border">
                      {['Shop', 'Total', 'Last 30d', 'Top Channel', 'Last Campaign', ''].map((h) => (
                        <th key={h} className="text-left pb-2 font-semibold text-[11px] uppercase tracking-wide text-muted-foreground pr-4">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/50">
                    {data.per_tenant.map((row) => (
                      <tr key={row.tenant_id} className="hover:bg-muted/20 transition">
                        <td className="py-2.5 pr-4 font-medium">{row.tenant_name}</td>
                        <td className="py-2.5 pr-4 text-muted-foreground">{row.total}</td>
                        <td className="py-2.5 pr-4">
                          <span className={row.last_30d > 0 ? 'text-decision-promote font-medium' : 'text-muted-foreground'}>{row.last_30d}</span>
                        </td>
                        <td className="py-2.5 pr-4 text-muted-foreground capitalize">{row.most_used_channel ?? '—'}</td>
                        <td className="py-2.5 pr-4 text-muted-foreground text-[12px]">
                          {row.last_campaign_at ? new Date(row.last_campaign_at).toLocaleDateString() : '—'}
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

            {/* Recent campaigns feed */}
            {data.recent.length > 0 && (
              <div className="rounded-xl border border-border bg-card/80 p-5 shadow-sm-soft">
                <h3 className="font-semibold text-[14px] mb-4">Recent Campaigns</h3>
                <div className="space-y-2">
                  {data.recent.map((c, i) => (
                    <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-muted/20 hover:bg-muted/30 transition">
                      <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                        <Megaphone className="h-4 w-4 text-primary" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-[13px] truncate">{c.product_name}</span>
                          <span className="text-[11px] text-muted-foreground">· {c.tenant_name}</span>
                          <ChannelBadge channel={c.channel} />
                          {c.fallback_used && (
                            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded border border-decision-clear/30 bg-decision-clear/10 text-decision-clear">Fallback</span>
                          )}
                        </div>
                        <div className="text-[12px] text-muted-foreground mt-0.5 truncate">{c.headline}</div>
                      </div>
                      <div className="text-[11px] text-muted-foreground shrink-0 text-right">
                        <div>{c.confidence_pct.toFixed(0)}% confidence</div>
                        <div className="mt-0.5">{new Date(c.created_at).toLocaleDateString()}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
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

function ChannelBadge({ channel }: { channel: string }) {
  const ch = channel?.toLowerCase() ?? 'other';
  const color = CHANNEL_COLORS[ch] ?? CHANNEL_COLORS.other;
  return (
    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: `${color}22`, color }}>
      {channel}
    </span>
  );
}
