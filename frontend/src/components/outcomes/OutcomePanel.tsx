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
  const liftText = lift === null ? null : `${lift >= 0 ? '+' : ''}${Math.round(lift)}% lift`;
  const accuracyText = accuracy === null ? null : `${Math.round(accuracy * 100)}% accuracy`;

  return (
    <span
      className={cn(
        'inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-mono uppercase',
        statusClass[snapshot.status],
      )}
      title={snapshot.ie2_explanation ?? undefined}
    >
      <span>{liftText ?? statusLabel[snapshot.status]}</span>
      {accuracyText && <span className="text-current/70">- {accuracyText}</span>}
    </span>
  );
}

function fmtNumber(value: number | null | undefined, suffix = '') {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })}${suffix}`;
}

function fmtUsd(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function fmtPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return fmtNumber(value * 100, '%');
}

function fmtDate(value: string | null | undefined) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-card/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-[13px] text-foreground">{value}</div>
    </div>
  );
}

export default function OutcomePanel({ snapshot }: { snapshot: OutcomeSnapshot }) {
  const latest = snapshot.measurements?.[snapshot.measurements.length - 1] ?? null;

  return (
    <div className="space-y-3 rounded-lg border border-border bg-background/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Outcome tracking</div>
          <div className="mt-1 flex items-center gap-2">
            <OutcomeChip snapshot={snapshot} />
            <span className="font-mono text-[11px] text-muted-foreground">
              Approved {fmtDate(snapshot.approved_at)}
            </span>
          </div>
        </div>
        <div className="text-right font-mono text-[11px] text-muted-foreground">
          7d check {fmtDate(snapshot.check_7d_at)} | 14d check {fmtDate(snapshot.check_14d_at)}
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-4">
        <Metric label="Baseline velocity" value={fmtNumber(snapshot.baseline_velocity_daily, '/day')} />
        <Metric label="Baseline revenue 7d" value={fmtUsd(snapshot.baseline_revenue_7d)} />
        <Metric label="Predicted lift" value={fmtNumber(snapshot.predicted_lift_pct, '%')} />
        <Metric label="IE2 confidence" value={fmtPct(snapshot.ie2_confidence)} />
      </div>

      {latest ? (
        <div className="grid gap-2 md:grid-cols-4">
          <Metric label={`Actual velocity ${latest.window_days}d`} value={fmtNumber(latest.actual_velocity_daily, '/day')} />
          <Metric label="Qty sold" value={fmtNumber(latest.actual_qty_sold)} />
          <Metric label="Revenue delta" value={fmtUsd(latest.revenue_delta_usd)} />
          <Metric label="Accuracy" value={fmtPct(latest.accuracy_score)} />
        </div>
      ) : (
        <p className="rounded-md border border-dashed border-border px-3 py-2 text-[12px] text-muted-foreground">
          No measurement has been recorded yet. This decision is still inside its tracking window.
        </p>
      )}

      {(latest?.narrative || snapshot.ie2_explanation) && (
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">
          {latest?.narrative || snapshot.ie2_explanation}
        </p>
      )}
    </div>
  );
}
