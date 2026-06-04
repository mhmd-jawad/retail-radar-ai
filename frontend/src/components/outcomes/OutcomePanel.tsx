import type { OutcomeSnapshot } from '@/types/domain';
import { cn } from '@/lib/utils';

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

export default function OutcomePanel({ snapshot }: { snapshot: OutcomeSnapshot }) {
  const measurements = snapshot.measurements ?? [];
  const latest = measurements[measurements.length - 1] ?? null;

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
        <OutcomeChip snapshot={snapshot} />
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <OutcomeMetric label="Predicted lift" value={pct(snapshot.predicted_lift_pct)} />
        <OutcomeMetric label="Baseline velocity" value={num(snapshot.baseline_velocity_daily)} />
        <OutcomeMetric label="Latest lift" value={pct(latest?.velocity_lift_pct ?? null)} />
        <OutcomeMetric label="Accuracy" value={accuracyPct(latest?.accuracy_score)} />
      </div>

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
