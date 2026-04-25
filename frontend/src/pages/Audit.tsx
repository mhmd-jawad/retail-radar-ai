import { useState, useMemo } from 'react';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { MOCK_AUDIT } from '@/data/mockReport';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import { fmtUSD, statusStyles, relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';

export default function Audit() {
  const [filter, setFilter] = useState<string>('ALL');
  const filtered = useMemo(() => filter === 'ALL' ? MOCK_AUDIT : MOCK_AUDIT.filter(a => a.status === filter), [filter]);

  return (
    <>
      <TopBar title="Audit Trail" subtitle="Every approved, edited, rejected, and snoozed recommendation" />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <Section title={`${filtered.length} entries`}
          action={
            <select value={filter} onChange={(e) => setFilter(e.target.value)} className="h-9 px-3 rounded-md border border-border bg-card text-[12.5px]">
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
              </tr>
            </thead>
            <tbody>
              {filtered.map(a => (
                <tr key={a.id} className="border-t border-border hover:bg-accent/40">
                  <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground">{relativeTime(a.timestamp)}</td>
                  <td className="px-4 py-2.5 font-mono">{a.actor}</td>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground">{a.sku_id}</td>
                  <td className="px-4 py-2.5 font-medium">{a.product_name}</td>
                  <td className="px-4 py-2.5"><DecisionBadge decision={a.decision} size="sm" /></td>
                  <td className="px-4 py-2.5"><span className={cn('px-2 py-0.5 rounded text-[10.5px] font-mono uppercase', statusStyles[a.status])}>{a.status}</span></td>
                  <td className="px-4 py-2.5 font-mono text-[12px]">
                    {a.before && a.after ? `${fmtUSD(a.before.price_usd)} → ${fmtUSD(a.after.price_usd)}${a.after.discount_pct ? ` (-${a.after.discount_pct}%)` : ''}` : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-[12px] text-muted-foreground italic">{a.notes || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </main>
    </>
  );
}
