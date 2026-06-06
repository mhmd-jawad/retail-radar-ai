import { useMemo, useState } from 'react';
import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import { decisionStyles, fmtPct, fmtUSD, statusStyles } from '@/lib/format';
import { useSettings } from '@/store/settings';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { scopedSkuKey } from '@/lib/tenantScope';
import type { Decision, SkuAnalysis } from '@/types/domain';
import { Search, LayoutGrid, Table as TableIcon, Filter, Check, X, Clock, Pencil } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { RecommendationDrawer } from '@/components/recommendations/RecommendationDrawer';

const decisionOrder: Decision[] = ['CLEAR', 'MARKDOWN', 'PROMOTE', 'HOLD'];

export default function Queue() {
  const { data: report, isLoading } = useReport();
  const { recState, setRecStatus } = useSettings();
  const tenantScope = useTenantScopeKey();
  const [view, setView] = useState<'board' | 'table'>('board');
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<{ brand: string; category: string; decision: Decision | 'ALL' }>({
    brand: 'ALL', category: 'ALL', decision: 'ALL',
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openSku, setOpenSku] = useState<string | null>(null);

  const skus = report?.inventory.sku_analysis || [];
  const brands = useMemo(() => Array.from(new Set(skus.map((s) => s.brand))).sort(), [skus]);
  const categories = useMemo(() => Array.from(new Set(skus.map((s) => s.category))).sort(), [skus]);

  const filtered = useMemo(() => {
    return skus.filter((s) => {
      if (filters.brand !== 'ALL' && s.brand !== filters.brand) return false;
      if (filters.category !== 'ALL' && s.category !== filters.category) return false;
      if (filters.decision !== 'ALL' && s.decision !== filters.decision) return false;
      if (search && !`${s.sku_id} ${s.product_name} ${s.brand}`.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [skus, filters, search]);

  const grouped = useMemo(() => {
    const m: Record<Decision, SkuAnalysis[]> = { HOLD: [], PROMOTE: [], MARKDOWN: [], CLEAR: [] };
    filtered.forEach((s) => m[s.decision].push(s));
    return m;
  }, [filtered]);

  if (isLoading || !report) {
    return (<><TopBar title="Recommendations Queue" /><PageSkeleton /></>);
  }

  const toggleSel = (sku: string) => {
    setSelected((prev) => {
      const n = new Set(prev);
      n.has(sku) ? n.delete(sku) : n.add(sku);
      return n;
    });
  };

  const bulkAction = (status: 'approved' | 'rejected' | 'snoozed') => {
    selected.forEach((sku) => setRecStatus(sku, status));
    toast.success(`${selected.size} SKUs ${status}`, { description: 'Logged to audit trail.' });
    setSelected(new Set());
  };

  return (
    <>
      <TopBar
        title="Recommendations Queue"
        subtitle={`${filtered.length} of ${skus.length} SKUs · human approval required`}
        actions={
          <div className="hidden md:flex items-center gap-1 rounded-md border border-border bg-surface-raised p-1">
            <button onClick={() => setView('board')} className={cn('px-2.5 py-1 rounded text-[12px] inline-flex items-center gap-1.5', view === 'board' ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground')}>
              <LayoutGrid className="h-3.5 w-3.5" /> Board
            </button>
            <button onClick={() => setView('table')} className={cn('px-2.5 py-1 rounded text-[12px] inline-flex items-center gap-1.5', view === 'table' ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground')}>
              <TableIcon className="h-3.5 w-3.5" /> Table
            </button>
          </div>
        }
      />

      <main className="flex-1 px-6 lg:px-8 py-6 space-y-5 animate-fade-in">
        {/* Filters bar */}
        <div className="flex flex-wrap items-center gap-2 p-3 rounded-xl bg-surface-raised border border-border">
          <div className="flex items-center gap-2 min-w-[260px] flex-1 px-3 h-9 rounded-md border border-border bg-card">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="SKU, product, brand…" className="bg-transparent outline-none text-[13px] flex-1" />
          </div>
          <FilterSelect value={filters.brand} onChange={(v) => setFilters({ ...filters, brand: v })} options={['ALL', ...brands]} label="Brand" />
          <FilterSelect value={filters.category} onChange={(v) => setFilters({ ...filters, category: v })} options={['ALL', ...categories]} label="Category" />
          <FilterSelect value={filters.decision} onChange={(v) => setFilters({ ...filters, decision: v as any })} options={['ALL', ...decisionOrder]} label="Decision" />
          <div className="ml-auto flex items-center gap-2">
            {selected.size > 0 && (
              <>
                <span className="text-[12px] font-mono text-muted-foreground">{selected.size} selected</span>
                <button onClick={() => bulkAction('approved')} className="h-9 px-3 rounded-md bg-decision-promote text-white text-[12px] font-semibold inline-flex items-center gap-1.5"><Check className="h-3.5 w-3.5" /> Approve</button>
                <button onClick={() => bulkAction('snoozed')} className="h-9 px-3 rounded-md bg-secondary text-secondary-foreground text-[12px] font-semibold inline-flex items-center gap-1.5"><Clock className="h-3.5 w-3.5" /> Snooze</button>
                <button onClick={() => bulkAction('rejected')} className="h-9 px-3 rounded-md bg-decision-clear text-white text-[12px] font-semibold inline-flex items-center gap-1.5"><X className="h-3.5 w-3.5" /> Reject</button>
              </>
            )}
          </div>
        </div>

        {view === 'board' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {decisionOrder.map((d) => {
              const items = grouped[d];
              const s = decisionStyles[d];
              return (
                <div key={d} className="rounded-xl bg-card border border-border overflow-hidden flex flex-col max-h-[78vh]">
                  <div className={cn('px-4 py-3 border-b border-border bg-gradient-to-br flex items-center justify-between', s.gradient)}>
                    <div className="flex items-center gap-2">
                      <DecisionBadge decision={d} size="lg" />
                      <span className="text-[12px] text-muted-foreground font-mono">{items.length}</span>
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto scrollbar-thin p-2 space-y-2">
                    {items.length === 0 && (
                      <div className="text-center text-[12px] text-muted-foreground py-12">No SKUs in this band</div>
                    )}
                    {items.slice(0, 60).map((sku) => (
                      <SkuCard key={sku.sku_id} sku={sku} onOpen={() => setOpenSku(sku.sku_id)}
                        selected={selected.has(sku.sku_id)} onSelect={() => toggleSel(sku.sku_id)}
                        status={recState[scopedSkuKey(sku.sku_id, tenantScope)]?.status} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <Section bodyClassName="p-0">
            <div className="overflow-x-auto scrollbar-thin">
              <table className="w-full text-[13px]">
                <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground font-semibold">
                  <tr>
                    <th className="px-4 py-3 text-left w-10"></th>
                    <th className="px-4 py-3 text-left">SKU</th>
                    <th className="px-4 py-3 text-left">Product</th>
                    <th className="px-4 py-3 text-left">Brand</th>
                    <th className="px-4 py-3 text-right">Stock</th>
                    <th className="px-4 py-3 text-right">DOS</th>
                    <th className="px-4 py-3 text-right">Margin</th>
                    <th className="px-4 py-3 text-right">Price</th>
                    <th className="px-4 py-3 text-left">Decision</th>
                    <th className="px-4 py-3 text-left">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.slice(0, 200).map((s) => (
                    <tr key={s.sku_id} className="border-t border-border hover:bg-accent/40 cursor-pointer" onClick={() => setOpenSku(s.sku_id)}>
                      <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={selected.has(s.sku_id)} onChange={() => toggleSel(s.sku_id)} />
                      </td>
                      <td className="px-4 py-2.5 font-mono text-[12px] text-muted-foreground">{s.sku_id}</td>
                      <td className="px-4 py-2.5 font-medium">{s.product_name}</td>
                      <td className="px-4 py-2.5 text-muted-foreground">{s.brand}</td>
                      <td className="px-4 py-2.5 text-right font-mono">{s.current_stock}</td>
                      <td className={cn('px-4 py-2.5 text-right font-mono', s.days_of_supply > 90 ? 'text-decision-markdown' : s.days_of_supply <= 21 ? 'text-decision-clear' : 'text-foreground')}>{s.days_of_supply}</td>
                      <td className={cn('px-4 py-2.5 text-right font-mono', s.margin_pct < 35 ? 'text-decision-clear' : s.margin_pct >= 45 ? 'text-decision-promote' : 'text-foreground')}>{fmtPct(s.margin_pct, 0)}</td>
                      <td className="px-4 py-2.5 text-right font-mono">{fmtUSD(s.retail_price_usd)}</td>
                      <td className="px-4 py-2.5"><DecisionBadge decision={s.decision} size="sm" /></td>
                      <td className="px-4 py-2.5">
                        <span className={cn('inline-flex px-2 py-0.5 rounded text-[10.5px] font-mono uppercase tracking-wider', statusStyles[recState[scopedSkuKey(s.sku_id, tenantScope)]?.status || 'pending'])}>
                          {recState[scopedSkuKey(s.sku_id, tenantScope)]?.status || 'pending'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}
      </main>

      <RecommendationDrawer
        sku={openSku ? skus.find((s) => s.sku_id === openSku) || null : null}
        open={!!openSku}
        onClose={() => setOpenSku(null)}
      />
    </>
  );
}

function FilterSelect({ value, onChange, options, label }: { value: string; onChange: (v: string) => void; options: string[]; label: string }) {
  return (
    <label className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md border border-border bg-card text-[12px]">
      <Filter className="h-3 w-3 text-muted-foreground" />
      <span className="text-muted-foreground">{label}:</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="bg-transparent outline-none font-medium pr-1">
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

function SkuCard({ sku, onOpen, selected, onSelect, status }: {
  sku: SkuAnalysis; onOpen: () => void; selected: boolean; onSelect: () => void; status?: string;
}) {
  const s = decisionStyles[sku.decision];
  return (
    <div className={cn('group rounded-lg border bg-card p-3 hover:shadow-md-soft transition cursor-pointer', selected ? 'border-primary ring-1 ring-primary' : 'border-border')} onClick={onOpen}>
      <div className="flex items-start gap-2">
        <input type="checkbox" checked={selected} onClick={(e) => e.stopPropagation()} onChange={onSelect} className="mt-1" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10.5px] text-muted-foreground">{sku.sku_id}</span>
            {status && status !== 'pending' && (
              <span className={cn('text-[9.5px] font-mono uppercase px-1.5 rounded', statusStyles[status as keyof typeof statusStyles])}>
                {status}
              </span>
            )}
          </div>
          <div className="text-[13px] font-semibold leading-snug mt-0.5 truncate">{sku.product_name}</div>
          <div className="text-[11px] text-muted-foreground mt-0.5">{sku.brand} · {sku.category}</div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-border">
        <Stat label="Stock" value={`${sku.current_stock}`} />
        <Stat label="DOS" value={`${sku.days_of_supply}d`} className={sku.days_of_supply > 90 ? 'text-decision-markdown' : sku.days_of_supply <= 21 ? 'text-decision-clear' : ''} />
        <Stat label="Margin" value={fmtPct(sku.margin_pct, 0)} className={sku.margin_pct >= 45 ? 'text-decision-promote' : sku.margin_pct < 35 ? 'text-decision-clear' : ''} />
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[11px] font-mono text-muted-foreground">{fmtUSD(sku.retail_price_usd)}</span>
        <Pencil className="h-3 w-3 text-muted-foreground opacity-0 group-hover:opacity-100" />
      </div>
    </div>
  );
}

function Stat({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <div className="text-[9.5px] uppercase tracking-wider text-muted-foreground font-mono">{label}</div>
      <div className={cn('text-[12.5px] font-semibold font-mono mt-0.5', className)}>{value}</div>
    </div>
  );
}
