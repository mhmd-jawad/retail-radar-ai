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
