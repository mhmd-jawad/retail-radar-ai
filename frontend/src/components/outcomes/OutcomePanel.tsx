import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, RefreshCw } from 'lucide-react';
import type { OutcomeSnapshot } from '@/types/domain';
import { triggerMeasurement } from '@/lib/adapter';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';

// ── Helpers ───────────────────────────────────────────────────────────────────

function isDue(snapshot: OutcomeSnapshot): { due: boolean; windowDays: 7 | 14 } {
  const now = Date.now();
  if (snapshot.status === 'tracking' && new Date(snapshot.check_7d_at).getTime() <= now) {
    return { due: true, windowDays: 7 };
  }
  if (snapshot.status === 'measured_7d' && new Date(snapshot.check_14d_at).getTime() <= now) {
    return { due: true, windowDays: 14 };
  }
  return { due: false, windowDays: 7 };
}

function pct(value: number | null | undefined) {
  if (value == null) return '-';
  return `${value >= 0 ? '+' : ''}${Math.round(value)}%`;
}

function accuracyPct(value: number | null | undefined) {
  if (value == null) return '-';
  return `${Math.round(value * 100)}%`;
}

function num(value: number | null | undefined) {
  if (value == null) return '-';
  return value.toLocaleString();
}

function money(value: number | null | undefined) {
  if (value == null) return '-';
  return `$${Math.round(value).toLocaleString()}`;
}

// ── Status chip metadata ──────────────────────────────────────────────────────

const statusLabel: Record<OutcomeSnapshot['status'], string> = {
  tracking: 'Tracking',
  measured_7d: '7d measured',
  completed: 'Completed',
  insufficient_data: 'Insufficient data',
};

const statusClass: Record<OutcomeSnapshot['status'], string> = {
  tracking: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  measured_7d: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  completed: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  insufficient_data: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
};

// ── OutcomeChip ───────────────────────────────────────────────────────────────

export function OutcomeChip({ snapshot }: { snapshot: OutcomeSnapshot | null }) {
  if (!snapshot) return null;

  const latest = snapshot.measurements?.[snapshot.measurements.length - 1] ?? null;
  const lift = latest?.velocity_lift_pct ?? null;
  const accuracy = latest?.accuracy_score ?? null;
  const liftText = lift === null ? null : pct(lift);
  const accuracyText = accuracy === null ? null : accuracyPct(accuracy);

  return (
    <span
      className={cn(
        'inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-mono uppercase',
        statusClass[snapshot.status],
      )}
      title={snapshot.ie2_explanation ?? undefined}
    >
      <span>{liftText ? `${liftText} lift` : statusLabel[snapshot.status]}</span>
      {accuracyText && <span className="text-current/70">- {accuracyText} accuracy</span>}
    </span>
  );
}

// ── 7d / 14d comparison bar ───────────────────────────────────────────────────

function LiftComparisonBar({ snapshot }: { snapshot: OutcomeSnapshot }) {
  const m7 = snapshot.measurements?.find((m) => m.window_days === 7);
  const m14 = snapshot.measurements?.find((m) => m.window_days === 14);
  if (!m7 && !m14) return null;

  const lift7 = m7?.velocity_lift_pct ?? null;
  const lift14 = m14?.velocity_lift_pct ?? null;
  if (lift7 == null && lift14 == null) return null;

  const max = Math.max(Math.abs(lift7 ?? 0), Math.abs(lift14 ?? 0), 10);

  function barWidth(v: number | null) {
    if (v == null) return 0;
    return Math.min(100, Math.abs(v) / max * 100);
  }
  function barColor(v: number | null) {
    if (v == null) return 'bg-muted';
    if (v > 5) return 'bg-decision-promote';
    if (v < -5) return 'bg-decision-clear';
    return 'bg-muted-foreground';
  }

  return (
    <div className="mt-4 rounded-lg border border-border/70 bg-background/45 p-3 space-y-2">
      <div className="text-[10.5px] uppercase tracking-wider text-muted-foreground mb-2">Velocity lift comparison</div>
      {lift7 != null && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-muted-foreground w-6">7d</span>
          <div className="flex-1 bg-border/40 rounded-full h-2 overflow-hidden">
            <div
              className={cn('h-2 rounded-full transition-all', barColor(lift7))}
              style={{ width: `${barWidth(lift7)}%` }}
            />
          </div>
          <span className="text-[11px] font-mono font-semibold w-10 text-right">{pct(lift7)}</span>
        </div>
      )}
      {lift14 != null && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-muted-foreground w-6">14d</span>
          <div className="flex-1 bg-border/40 rounded-full h-2 overflow-hidden">
            <div
              className={cn('h-2 rounded-full transition-all', barColor(lift14))}
              style={{ width: `${barWidth(lift14)}%` }}
            />
          </div>
          <span className="text-[11px] font-mono font-semibold w-10 text-right">{pct(lift14)}</span>
        </div>
      )}
    </div>
  );
}

// ── Verdict + next action ─────────────────────────────────────────────────────

function VerdictLine({ snapshot }: { snapshot: OutcomeSnapshot }) {
  const latest = snapshot.measurements?.[snapshot.measurements.length - 1] ?? null;
  if (!latest?.data_available) return null;

  const lift = latest.velocity_lift_pct;
  if (lift == null) return null;

  let icon: string;
  let label: string;
  let cls: string;
  let hint: string;

  if (lift > 5) {
    icon = '✅'; label = 'Good call'; cls = 'text-decision-promote border-decision-promote/20 bg-decision-promote-bg';
    hint = `This decision beat the baseline. Similar SKUs in the same category are candidates for the same approach.`;
  } else if (lift < -5) {
    icon = '⚠️'; label = 'Below target'; cls = 'text-decision-markdown border-decision-markdown/20 bg-decision-markdown-bg';
    hint = `Velocity dropped after the decision. Review discount depth or campaign timing before approving similar decisions.`;
  } else {
    icon = '➡️'; label = 'Neutral'; cls = 'text-muted-foreground border-border bg-muted/30';
    hint = `No significant velocity change detected. Baseline may need more data to show a meaningful signal.`;
  }

  return (
    <div className={cn('mt-4 rounded-lg border px-3 py-2.5 text-[12px]', cls)}>
      <span className="font-semibold">{icon} {label}</span>
      <span className="ml-2 opacity-80">{hint}</span>
    </div>
  );
}

// ── OutcomePanel ──────────────────────────────────────────────────────────────

export default function OutcomePanel({ snapshot, queryKey }: {
  snapshot: OutcomeSnapshot | null;
  queryKey?: readonly unknown[];
}) {
  const qc = useQueryClient();
  const [justMeasured, setJustMeasured] = useState(false);

  const measureMutation = useMutation({
    mutationFn: ({ id, window }: { id: number; window: 7 | 14 }) =>
      triggerMeasurement(id, window),
    onSuccess: () => {
      setJustMeasured(true);
      if (queryKey) qc.invalidateQueries({ queryKey: [...queryKey] as unknown[] });
      toast.success('Measurement complete', { description: 'Outcome data has been updated.' });
    },
    onError: (err) => {
      toast.error('Measurement failed', {
        description: err instanceof Error ? err.message : 'Unknown error',
      });
    },
  });

  if (!snapshot) return null;

  const measurements = snapshot.measurements ?? [];
  const latest = measurements[measurements.length - 1] ?? null;
  const { due, windowDays } = isDue(snapshot);
  const canMeasure = due && !justMeasured;

  return (
    <div className="rounded-xl border border-primary/15 bg-gradient-to-br from-primary/10 to-decision-promote/5 p-4 shadow-sm-soft">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground">Closed-loop outcome</div>
          <div className="mt-1 text-sm font-semibold">{snapshot.decision_type} decision tracking</div>
          {snapshot.ie2_explanation && (
            <p className="mt-1 max-w-3xl text-[12.5px] leading-5 text-muted-foreground">{snapshot.ie2_explanation}</p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <OutcomeChip snapshot={snapshot} />
          {canMeasure && (
            <button
              onClick={() => measureMutation.mutate({ id: snapshot.id, window: windowDays })}
              disabled={measureMutation.isPending}
              className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-semibold bg-primary-glow text-primary-foreground hover:opacity-90 disabled:opacity-60 shadow-glow-sm transition"
            >
              {measureMutation.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              Measure {windowDays}d now
            </button>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <OutcomeMetric label="Predicted lift" value={pct(snapshot.predicted_lift_pct)} />
        <OutcomeMetric label="Baseline velocity" value={num(snapshot.baseline_velocity_daily)} />
        <OutcomeMetric label="Latest lift" value={pct(latest?.velocity_lift_pct ?? null)} />
        <OutcomeMetric label="Accuracy" value={accuracyPct(latest?.accuracy_score)} />
      </div>

      {/* 7d / 14d lift comparison bar */}
      <LiftComparisonBar snapshot={snapshot} />

      {/* Verdict + next action */}
      <VerdictLine snapshot={snapshot} />

      {latest?.narrative && (
        <div className="mt-4 rounded-lg border border-border/70 bg-background/45 p-3 text-[12.5px] leading-5 text-muted-foreground">
          {latest.narrative}
        </div>
      )}

      {measurements.length > 0 && (
        <div className="mt-4 overflow-hidden rounded-lg border border-border/70">
          <table className="w-full text-[12px]">
            <thead className="bg-background/50 text-[10.5px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">Window</th>
                <th className="px-3 py-2 text-left">Qty sold</th>
                <th className="px-3 py-2 text-left">Revenue</th>
                <th className="px-3 py-2 text-left">Velocity lift</th>
                <th className="px-3 py-2 text-left">Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {measurements.map((measurement) => (
                <tr key={`${measurement.window_days}-${measurement.measured_at}`} className="border-t border-border/70">
                  <td className="px-3 py-2 font-mono">{measurement.window_days}d</td>
                  <td className="px-3 py-2">{num(measurement.actual_qty_sold)}</td>
                  <td className="px-3 py-2">{money(measurement.actual_revenue_total)}</td>
                  <td className="px-3 py-2">{pct(measurement.velocity_lift_pct)}</td>
                  <td className="px-3 py-2">{accuracyPct(measurement.accuracy_score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function OutcomeMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/70 bg-background/45 p-3">
      <div className="text-[10.5px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-sm font-semibold">{value}</div>
    </div>
  );
}
