import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { MOCK_AUDIT } from '@/data/mockReport';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import { fmtUSD, statusStyles, relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import { fetchOutcomesBySku, fetchPortfolioAccuracy } from '@/lib/adapter';
import { useSettings } from '@/store/settings';
import OutcomePanel, { OutcomeChip } from '@/components/outcomes/OutcomePanel';
import type { OutcomeSnapshot } from '@/types/domain';
import { ChevronDown, ChevronUp, Target } from 'lucide-react';

// ─── Expandable audit row with lazy outcome loading ───────────────────────────

function AuditRow({ entry }: { entry: typeof MOCK_AUDIT[0] }) {
  const [expanded, setExpanded] = useState(false);
  const mode = useSettings(s => s.mode);
  const isLive = mode === 'eep-live';

  const { data: outcomes = [] } = useQuery<OutcomeSnapshot[]>({
    queryKey: ['outcomes-by-sku', entry.sku_id],
    queryFn: () => fetchOutcomesBySku(entry.sku_id),
    enabled: isLive && entry.status === 'approved' && expanded,
    staleTime: 2 * 60_000,
  });

  const latestOutcome = outcomes[0] ?? null;

  return (
    <>
      <tr
        className={cn(
          'border-t border-border hover:bg-accent/40 cursor-pointer',
          expanded && 'bg-accent/20',
        )}
        onClick={() => setExpanded(v => !v)}
      >
        <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground">{relativeTime(entry.timestamp)}</td>
        <td className="px-4 py-2.5 font-mono">{entry.actor}</td>
        <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground">{entry.sku_id}</td>
        <td className="px-4 py-2.5 font-medium">{entry.product_name}</td>
        <td className="px-4 py-2.5"><DecisionBadge decision={entry.decision} size="sm" /></td>
        <td className="px-4 py-2.5">
          <span className={cn('px-2 py-0.5 rounded text-[10.5px] font-mono uppercase', statusStyles[entry.status])}>
            {entry.status}
          </span>
        </td>
        <td className="px-4 py-2.5 font-mono text-[12px]">
          {entry.before && entry.after
            ? `${fmtUSD(entry.before.price_usd)} → ${fmtUSD(entry.after.price_usd)}${entry.after.discount_pct ? ` (-${entry.after.discount_pct}%)` : ''}`
            : '—'}
        </td>
        <td className="px-4 py-2.5 text-[12px] text-muted-foreground italic">{entry.notes || '—'}</td>

        {/* Outcome column */}
        <td className="px-4 py-2.5">
          {isLive && entry.status === 'approved'
            ? latestOutcome
              ? <OutcomeChip snapshot={latestOutcome} />
              : <span className="text-[10.5px] text-muted-foreground italic">loading…</span>
            : <span className="text-[10.5px] text-muted-foreground">—</span>
          }
        </td>

        <td className="px-3 py-2.5 text-muted-foreground">
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </td>
      </tr>

      {/* Expanded outcome panel */}
      {expanded && isLive && entry.status === 'approved' && (
        <tr className="border-t border-border bg-surface-sunken">
          <td colSpan={10} className="px-6 py-4">
            {latestOutcome ? (
              <OutcomePanel snapshot={latestOutcome} />
            ) : (
              <p className="text-[12.5px] text-muted-foreground italic">
                No outcome snapshot yet for this decision. Outcome tracking starts automatically after approval when connected to live DB.
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Audit() {
  const [filter, setFilter] = useState<string>('ALL');
  const mode = useSettings(s => s.mode);
  const isLive = mode === 'eep-live';

  const filtered = useMemo(
    () => filter === 'ALL' ? MOCK_AUDIT : MOCK_AUDIT.filter(a => a.status === filter),
    [filter],
  );

  // Portfolio accuracy header (live mode only)
  const { data: accuracy } = useQuery({
    queryKey: ['portfolio-accuracy'],
    queryFn: () => fetchPortfolioAccuracy(),
    enabled: isLive,
    staleTime: 5 * 60_000,
  });

  return (
    <>
      <TopBar title="Audit Trail" subtitle="Every approved, edited, rejected, and snoozed recommendation" />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">

        {/* Accuracy summary banner (live mode) */}
        {isLive && accuracy && accuracy.decision_count >= 3 && (
          <div className="flex items-center gap-3 px-4 py-3 rounded-lg border border-indigo-500/20 bg-indigo-500/5 text-[12.5px]">
            <Target className="h-4 w-4 text-indigo-400 shrink-0" />
            <span className="text-muted-foreground">
              AI outcome accuracy this session:
            </span>
            <span className="font-semibold text-indigo-400">
              {accuracy.avg_accuracy != null ? `${accuracy.avg_accuracy}%` : '—'}
            </span>
            <span className="text-muted-foreground">
              across {accuracy.decision_count} tracked decisions
            </span>
            {Object.entries(accuracy.by_type).length > 0 && (
              <span className="text-muted-foreground ml-2">
                ({Object.entries(accuracy.by_type).map(([k, v]) => `${k}: ${v}%`).join(' · ')})
              </span>
            )}
          </div>
        )}

        <Section
          title={`${filtered.length} entries`}
          action={
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="h-9 px-3 rounded-md border border-border bg-card text-[12.5px]"
            >
              <option value="ALL">All statuses</option>
              <option value="approved">Approved</option>
              <option value="edited">Edited</option>
              <option value="rejected">Rejected</option>
              <option value="snoozed">Snoozed</option>
            </select>
          }
          bodyClassName="p-0"
        >
          <table className="w-full text-[13px]">
            <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-left">When</th>
                <th className="px-4 py-3 text-left">Actor</th>
                <th className="px-4 py-3 text-left">SKU</th>
                <th className="px-4 py-3 text-left">Product</th>
                <th className="px-4 py-3 text-left">Decision</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Before → After</th>
                <th className="px-4 py-3 text-left">Notes</th>
                <th className="px-4 py-3 text-left">Outcome</th>
                <th className="px-4 py-3 w-8" />
              </tr>
            </thead>
            <tbody>
              {filtered.map(a => <AuditRow key={a.id} entry={a} />)}
            </tbody>
          </table>
        </Section>
      </main>
    </>
  );
}
