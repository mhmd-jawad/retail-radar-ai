import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell,
  AreaChart, Area, ReferenceLine,
  ScatterChart, Scatter, ZAxis,
} from 'recharts';
import {
  Target, RefreshCw, ChevronDown, ChevronRight, Loader2,
  TrendingUp, CheckCircle2, AlertTriangle, BarChart2,
} from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { cn } from '@/lib/utils';
import {
  fetchAllOutcomes,
  measureAllDue,
  fetchPortfolioAccuracy,
  fetchDailySeries,
} from '@/lib/adapter';
import { toast } from 'sonner';
import type { OutcomeRow, OutcomeMeasurement, Decision } from '@/types/domain';

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(v: number | null | undefined, sign = true) {
  if (v == null) return '—';
  return `${sign && v >= 0 ? '+' : ''}${Math.round(v)}%`;
}
function money(v: number | null | undefined) {
  if (v == null) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}$${Math.abs(Math.round(v)).toLocaleString()}`;
}
function acc(v: number | null | undefined) {
  if (v == null) return '—';
  return `${Math.round(v * 100)}%`;
}
function relDate(iso: string) {
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 86400000;
  if (diff < 1) return 'Today';
  if (diff < 2) return 'Yesterday';
  if (diff < 30) return `${Math.round(diff)}d ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
function isDue(row: OutcomeRow) {
  const now = Date.now();
  if (row.status === 'tracking') return new Date(row.check_7d_at).getTime() <= now;
  if (row.status === 'measured_7d') return new Date(row.check_14d_at).getTime() <= now;
  return false;
}
function measurementAt(row: OutcomeRow, window: 7 | 14): OutcomeMeasurement | null {
  return row.measurements?.find((m) => m.window_days === window) ?? null;
}
function verdict(lift: number | null | undefined) {
  if (lift == null) return null;
  if (lift > 5) return { icon: '✅', label: 'Good call', color: 'text-decision-promote' };
  if (lift < -5) return { icon: '⚠️', label: 'Below target', color: 'text-decision-markdown' };
  return { icon: '➡️', label: 'Neutral', color: 'text-muted-foreground' };
}

const DECISION_COLORS: Record<string, string> = {
  PROMOTE: 'hsl(var(--decision-promote))',
  MARKDOWN: 'hsl(var(--decision-markdown))',
  CLEAR: 'hsl(var(--decision-clear))',
  HOLD: 'hsl(var(--decision-hold, 200 60% 60%))',
};
const DECISION_BG: Record<string, string> = {
  PROMOTE: 'bg-decision-promote-bg text-decision-promote border-decision-promote/30',
  MARKDOWN: 'bg-decision-markdown-bg text-decision-markdown border-decision-markdown/30',
  CLEAR: 'bg-decision-clear-bg text-decision-clear border-decision-clear/30',
  HOLD: 'bg-blue-500/10 text-blue-300 border-blue-500/30',
};

// ── KPI Card ──────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, icon: Icon, warn,
}: { label: string; value: string; sub?: string; icon: React.ElementType; warn?: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-card/80 p-4">
      <div className="flex items-start justify-between mb-3">
        <div className="h-8 w-8 rounded-lg bg-muted/60 flex items-center justify-center border border-border">
          <Icon className="h-4 w-4 text-muted-foreground" />
        </div>
      </div>
      <div className={cn('text-[26px] font-bold font-display leading-none', warn && 'text-decision-markdown')}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-muted-foreground mt-1">{sub}</div>}
      <div className="text-[11px] text-muted-foreground uppercase tracking-wide mt-2">{label}</div>
    </div>
  );
}

// ── Daily series expansion ─────────────────────────────────────────────────────

function DailySeriesChart({ snapshotId, approvedAt }: { snapshotId: number; approvedAt: string }) {
  const { data = [], isLoading } = useQuery({
    queryKey: ['daily-series', snapshotId],
    queryFn: () => fetchDailySeries(snapshotId),
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-muted-foreground py-4 pl-4">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading sales data…
      </div>
    );
  }
  if (!data.length) {
    return (
      <p className="text-[12px] text-muted-foreground py-4 pl-4">
        No daily sales data available for this snapshot.
      </p>
    );
  }

  const decisionDate = new Date(approvedAt).toISOString().slice(0, 10);

  return (
    <div className="px-4 pb-4 pt-2">
      <div className="text-[10.5px] font-mono uppercase tracking-wider text-muted-foreground mb-2">
        Daily velocity · 7d before → 14d after decision
      </div>
      <ResponsiveContainer width="100%" height={140}>
        <AreaChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <defs>
            <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.25} />
              <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border)/0.5)" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }}
            tickFormatter={(d: string) => d.slice(5)}
            interval="preserveStartEnd"
          />
          <YAxis tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }} />
          <Tooltip
            contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', fontSize: 11 }}
            labelStyle={{ color: 'hsl(var(--foreground))' }}
          />
          <ReferenceLine
            x={decisionDate}
            stroke="hsl(var(--primary))"
            strokeDasharray="4 2"
            label={{ value: 'Decision', position: 'top', fontSize: 9, fill: 'hsl(var(--primary))' }}
          />
          <Area
            type="monotone"
            dataKey="units_sold"
            name="Units sold"
            stroke="hsl(var(--primary))"
            fill="url(#areaGrad)"
            strokeWidth={1.5}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Timeline row ──────────────────────────────────────────────────────────────

function TimelineRow({ row }: { row: OutcomeRow }) {
  const [expanded, setExpanded] = useState(false);
  const m7 = measurementAt(row, 7);
  const m14 = measurementAt(row, 14);
  const latest = m14 ?? m7;
  const v = verdict(latest?.velocity_lift_pct);
  const due = isDue(row);

  const statusPill = {
    tracking: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
    measured_7d: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    completed: 'bg-emerald-600/15 text-emerald-200 border-emerald-600/30',
    insufficient_data: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  }[row.status];
  const statusLabel = {
    tracking: 'Tracking',
    measured_7d: '7d done',
    completed: 'Completed',
    insufficient_data: 'No data',
  }[row.status];

  const accScore = latest?.accuracy_score ?? null;
  const accColor = accScore == null ? '' : accScore >= 0.7 ? 'text-decision-promote' : accScore >= 0.5 ? 'text-decision-markdown' : 'text-decision-clear';

  return (
    <>
      <tr
        className={cn(
          'border-t border-border/60 cursor-pointer transition-colors',
          expanded ? 'bg-primary/5' : 'hover:bg-muted/30',
        )}
        onClick={() => setExpanded((e) => !e)}
      >
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-primary" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" />
            )}
            <div>
              <div className="text-[12.5px] font-medium">{row.product_name}</div>
              {row.brand && <div className="text-[10.5px] text-muted-foreground">{row.brand} · {row.sku_id}</div>}
            </div>
          </div>
        </td>
        <td className="px-3 py-3">
          <span className={cn('inline-flex items-center text-[10px] font-semibold px-1.5 py-0.5 rounded border', DECISION_BG[row.decision_type] ?? 'bg-muted text-muted-foreground border-border')}>
            {row.decision_type}
          </span>
        </td>
        <td className="px-3 py-3 text-[12px] text-muted-foreground">{relDate(row.approved_at)}</td>
        <td className="px-3 py-3">
          <span className={cn('inline-flex items-center text-[10px] font-mono px-1.5 py-0.5 rounded border', statusPill)}>
            {statusLabel}
            {due && <span className="ml-1 h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse inline-block" />}
          </span>
        </td>
        <td className="px-3 py-3 text-[12px] font-mono text-muted-foreground">{pct(row.predicted_lift_pct)}</td>
        <td className="px-3 py-3 text-[12px] font-mono">{pct(m7?.velocity_lift_pct)}</td>
        <td className="px-3 py-3 text-[12px] font-mono">{pct(m14?.velocity_lift_pct)}</td>
        <td className={cn('px-3 py-3 text-[12px] font-mono font-semibold', accColor)}>{acc(latest?.accuracy_score)}</td>
        <td className="px-3 py-3 text-[11.5px]">
          {v ? <span className={v.color}>{v.icon} {v.label}</span> : <span className="text-muted-foreground/40">—</span>}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-primary/3 border-t border-primary/15">
          <td colSpan={9} className="p-0">
            <DailySeriesChart snapshotId={row.id} approvedAt={row.approved_at} />
            {latest?.narrative && (
              <div className="px-4 pb-4">
                <p className="text-[12px] text-muted-foreground leading-relaxed italic border-l-2 border-primary/30 pl-3">
                  {latest.narrative}
                </p>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type FilterDecision = 'ALL' | Decision;
type FilterStatus = 'ALL' | 'tracking' | 'measured_7d' | 'completed' | 'insufficient_data';

export default function FinancialOutcomes() {
  const qc = useQueryClient();
  const [filterDecision, setFilterDecision] = useState<FilterDecision>('ALL');
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('ALL');

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['outcomes-all'],
    queryFn: () => fetchAllOutcomes(100),
  });
  const { data: accuracy } = useQuery({
    queryKey: ['portfolio-accuracy'],
    queryFn: () => fetchPortfolioAccuracy(),
  });

  const measureMutation = useMutation({
    mutationFn: measureAllDue,
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['outcomes-all'] });
      qc.invalidateQueries({ queryKey: ['portfolio-accuracy'] });
      toast.success(
        `Measurements complete`,
        { description: `${result.measured} measured · ${result.skipped} skipped · ${result.errors} errors` },
      );
    },
    onError: (err) => {
      toast.error('Measurement failed', { description: err instanceof Error ? err.message : 'Unknown error' });
    },
  });

  // KPI derivations
  const dueCount = rows.filter(isDue).length;
  const totalRevDelta = rows
    .flatMap((r) => r.measurements ?? [])
    .filter((m) => m.window_days === 14 && m.data_available)
    .reduce((s, m) => s + (m.revenue_delta_usd ?? 0), 0);

  // Accuracy bar chart data
  const accuracyChartData = Object.entries(accuracy?.by_type ?? {}).map(([type, value]) => ({
    type,
    accuracy: value ?? 0,
    fill: DECISION_COLORS[type] ?? 'hsl(var(--primary))',
  }));

  // Calibration scatter data
  const scatterData = rows
    .filter((r) => r.ie2_confidence != null)
    .flatMap((r) =>
      (r.measurements ?? [])
        .filter((m) => m.accuracy_score != null && m.data_available)
        .map((m) => ({
          confidence: Math.round((r.ie2_confidence ?? 0) * 100),
          accuracy: Math.round((m.accuracy_score ?? 0) * 100),
          type: r.decision_type,
          name: r.product_name,
        })),
    );

  // Filtered rows
  const filtered = rows.filter((r) => {
    if (filterDecision !== 'ALL' && r.decision_type !== filterDecision) return false;
    if (filterStatus !== 'ALL' && r.status !== filterStatus) return false;
    return true;
  });

  // Accuracy warning logic
  const weakTypes = Object.entries(accuracy?.by_type ?? {}).filter(([, v]) => (v ?? 0) < 55);
  const dangerTypes = Object.entries(accuracy?.by_type ?? {}).filter(([, v]) => (v ?? 0) < 35);

  return (
    <>
      <TopBar
        title="Decision Outcomes"
        subtitle="Closed-loop tracking — 7d and 14d results"
        actions={
          <button
            onClick={() => measureMutation.mutate()}
            disabled={measureMutation.isPending || dueCount === 0}
            className={cn(
              'inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-[12.5px] font-semibold shadow-sm transition-all',
              measureMutation.isPending || dueCount === 0
                ? 'bg-muted text-muted-foreground cursor-not-allowed'
                : 'bg-primary-glow text-primary-foreground hover:opacity-90 shadow-glow-sm',
            )}
          >
            {measureMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            {dueCount > 0 ? `Run ${dueCount} due check${dueCount > 1 ? 's' : ''}` : 'No checks due'}
          </button>
        }
      />

      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">

        {/* ── KPI Cards ── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard
            icon={Target}
            label="Total decisions tracked"
            value={isLoading ? '…' : String(rows.length)}
            sub={`${rows.filter((r) => r.status === 'completed').length} completed`}
          />
          <KpiCard
            icon={CheckCircle2}
            label="Average model accuracy"
            value={accuracy?.avg_accuracy != null ? `${accuracy.avg_accuracy}%` : '—'}
            sub={accuracy?.decision_count ? `${accuracy.decision_count} measured` : undefined}
          />
          <KpiCard
            icon={AlertTriangle}
            label="Due for check"
            value={isLoading ? '…' : String(dueCount)}
            sub={dueCount > 0 ? 'Click "Run due checks"' : 'All up to date'}
            warn={dueCount > 0}
          />
          <KpiCard
            icon={TrendingUp}
            label="Revenue impact (14d)"
            value={totalRevDelta !== 0 ? money(totalRevDelta) : '—'}
            sub="Sum across completed decisions"
          />
        </div>

        {/* ── Accuracy by Decision Type ── */}
        {accuracyChartData.length > 0 && (
          <div className="rounded-xl border border-border bg-card/80 p-5">
            <div className="flex items-start justify-between mb-4">
              <div>
                <div className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground">Model accuracy by type</div>
                <div className="text-[14px] font-semibold mt-0.5">Which decisions are most accurate?</div>
              </div>
              <BarChart2 className="h-4 w-4 text-muted-foreground/40 mt-0.5" />
            </div>
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={accuracyChartData} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border)/0.4)" vertical={false} />
                <XAxis dataKey="type" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} unit="%" />
                <Tooltip
                  formatter={(v: number) => [`${v}%`, 'Accuracy']}
                  contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', fontSize: 11 }}
                />
                <Bar dataKey="accuracy" radius={[3, 3, 0, 0]}>
                  {accuracyChartData.map((entry) => (
                    <Cell key={entry.type} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>

            {/* Learning signal */}
            {(dangerTypes.length > 0 || weakTypes.length > 0) && (
              <div className={cn(
                'mt-3 rounded-lg border px-3 py-2 text-[12px]',
                dangerTypes.length > 0
                  ? 'border-decision-clear/30 bg-decision-clear-bg text-decision-clear'
                  : 'border-decision-markdown/30 bg-decision-markdown-bg text-decision-markdown',
              )}>
                {dangerTypes.length > 0
                  ? `⚠️ ${dangerTypes.map(([t]) => t).join(', ')} decisions are below 35% accuracy — review approval criteria before approving more.`
                  : `⚠️ ${weakTypes.map(([t]) => t).join(', ')} accuracy is below 55% — consider tightening conditions before approving these.`}
              </div>
            )}
          </div>
        )}

        {/* ── Calibration Scatter ── */}
        {scatterData.length > 1 && (
          <div className="rounded-xl border border-border bg-card/80 p-5">
            <div className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground mb-1">
              Confidence calibration
            </div>
            <div className="text-[13px] font-semibold mb-4">
              Does IE2 confidence predict actual accuracy?
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <ScatterChart margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border)/0.4)" />
                <XAxis
                  type="number" dataKey="confidence" name="Confidence"
                  domain={[0, 100]} unit="%" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                  label={{ value: 'IE2 confidence', position: 'insideBottom', offset: -4, fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                />
                <YAxis
                  type="number" dataKey="accuracy" name="Accuracy"
                  domain={[0, 100]} unit="%" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                />
                <ZAxis range={[30, 60]} />
                <Tooltip
                  cursor={{ strokeDasharray: '3 3' }}
                  contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', fontSize: 11 }}
                  formatter={(v: number, name: string) => [`${v}%`, name]}
                />
                <Scatter
                  data={scatterData}
                  fill="hsl(var(--primary))"
                  fillOpacity={0.65}
                />
                {/* Perfect calibration line — represented as a note */}
              </ScatterChart>
            </ResponsiveContainer>
            <p className="text-[10.5px] text-muted-foreground mt-2">
              Dots near the diagonal = well-calibrated. Above diagonal = model was conservative. Below = overconfident.
            </p>
          </div>
        )}

        {/* ── Timeline Table ── */}
        <div className="rounded-xl border border-border bg-card/80 overflow-hidden">
          <div className="px-5 py-4 border-b border-border flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="flex-1">
              <div className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground">Outcome timeline</div>
              <div className="text-[13px] font-semibold mt-0.5">{filtered.length} decision{filtered.length !== 1 ? 's' : ''}</div>
            </div>
            {/* Filters */}
            <div className="flex items-center gap-2">
              <select
                value={filterDecision}
                onChange={(e) => setFilterDecision(e.target.value as FilterDecision)}
                className="h-7 rounded-md border border-border bg-muted/50 px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
              >
                <option value="ALL">All types</option>
                {(['PROMOTE', 'MARKDOWN', 'CLEAR', 'HOLD'] as const).map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value as FilterStatus)}
                className="h-7 rounded-md border border-border bg-muted/50 px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
              >
                <option value="ALL">All statuses</option>
                <option value="tracking">Tracking</option>
                <option value="measured_7d">7d done</option>
                <option value="completed">Completed</option>
                <option value="insufficient_data">No data</option>
              </select>
            </div>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground text-[13px] gap-2">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          ) : filtered.length === 0 ? (
            <div className="py-12 text-center">
              <Target className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
              <p className="text-[13px] text-muted-foreground">No decisions tracked yet.</p>
              <p className="text-[11.5px] text-muted-foreground/60 mt-1">
                Approve a recommendation from the Queue to start tracking outcomes.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12.5px]">
                <thead className="bg-muted/30 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 text-left">Product</th>
                    <th className="px-3 py-2.5 text-left">Type</th>
                    <th className="px-3 py-2.5 text-left">Approved</th>
                    <th className="px-3 py-2.5 text-left">Status</th>
                    <th className="px-3 py-2.5 text-left">Predicted</th>
                    <th className="px-3 py-2.5 text-left">7d lift</th>
                    <th className="px-3 py-2.5 text-left">14d lift</th>
                    <th className="px-3 py-2.5 text-left">Accuracy</th>
                    <th className="px-3 py-2.5 text-left">Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => (
                    <TimelineRow key={row.id} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </>
  );
}
