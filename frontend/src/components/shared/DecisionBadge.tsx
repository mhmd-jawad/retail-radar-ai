import { cn } from '@/lib/utils';
import type { Decision } from '@/types/domain';
import { decisionStyles } from '@/lib/format';

export function DecisionBadge({ decision, size = 'md' }: { decision: Decision; size?: 'sm' | 'md' | 'lg' }) {
  const s = decisionStyles[decision];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border font-mono font-semibold uppercase tracking-wider',
        s.chip,
        size === 'sm' && 'text-[10px] px-1.5 py-0.5',
        size === 'md' && 'text-[10.5px] px-2 py-0.5',
        size === 'lg' && 'text-[11.5px] px-2.5 py-1'
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full', s.dot)} />
      {s.label}
    </span>
  );
}
