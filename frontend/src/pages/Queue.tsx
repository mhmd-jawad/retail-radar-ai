import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import { decisionStyles, dosTextClass, fmtDos, fmtPct, fmtUSD, statusStyles } from '@/lib/format';
import { useSettings } from '@/store/settings';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { scopedSkuKey } from '@/lib/tenantScope';
import { recommend } from '@/lib/adapter';
import type { Decision, IE2Request, IE2Result, SkuAnalysis } from '@/types/domain';
import {
  SYSTEM_DECISION_CACHE_EVENT,
  isDailySystemDecisionDue,
  markDailySystemDecisionRun,
  readSystemDecisionCache,
  writeSystemDecisionEntry,
  type SystemDecisionStatus,
  type SystemDecisionTrigger,
} from '@/lib/systemDecisionCache';
import { Search, LayoutGrid, Table as TableIcon, Filter, Check, X, Clock, Pencil, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { RecommendationDrawer } from '@/components/recommendations/RecommendationDrawer';

const decisionOrder: Decision[] = ['CLEAR', 'MARKDOWN', 'PROMOTE', 'HOLD'];
type QueueBand = Decision | 'UNSCORED';
const queueBandOrder: QueueBand[] = ['UNSCORED', ...decisionOrder];
const SYSTEM_SYNC_LIMIT = 120;
const SYSTEM_SYNC_CONCURRENCY = 1;
const SYSTEM_SYNC_TTL_MS = 5 * 60_000;

type SystemDecisionState = {
  status: Exclude<SystemDecisionStatus, 'report'>;
  result?: IE2Result;
  error?: string;
  checkedAt: number;
  trigger?: SystemDecisionTrigger;
};

export default function Queue() {
  const { data: report, isLoading } = useReport();
  const { recState, setRecStatus, mode } = useSettings();
  const tenantScope = useTenantScopeKey();
  const [view, setView] = useState<'board' | 'table'>('board');
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<{ brand: string; category: string; decision: QueueBand | 'ALL' }>({
    brand: 'ALL', category: 'ALL', decision: 'ALL',
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openSku, setOpenSku] = useState<string | null>(null);

  const skus = report?.inventory.sku_analysis || [];
  const brands = useMemo(() => Array.from(new Set(skus.map((s) => s.brand))).sort(), [skus]);
  const categories = useMemo(() => Array.from(new Set(skus.map((s) => s.category))).sort(), [skus]);
  const [systemDecisionState, setSystemDecisionState] = useState<Record<string, SystemDecisionState>>(
    () => readSystemDecisionCache(tenantScope) as Record<string, SystemDecisionState>,
  );
  const [syncProgress, setSyncProgress] = useState({ active: false, completed: 0, total: 0 });
  const systemDecisionStateRef = useRef(systemDecisionState);
  const syncActiveRef = useRef(false);

  useEffect(() => {
    systemDecisionStateRef.current = systemDecisionState;
  }, [systemDecisionState]);

  useEffect(() => {
    syncActiveRef.current = syncProgress.active;
  }, [syncProgress.active]);

  useEffect(() => {
    setSystemDecisionState(readSystemDecisionCache(tenantScope) as Record<string, SystemDecisionState>);
  }, [tenantScope]);

  useEffect(() => {
    const onCacheUpdate = (event: Event) => {
      if (syncActiveRef.current) return;
      const detail = (event as CustomEvent<{ scopeKey?: string }>).detail;
      if (detail?.scopeKey && detail.scopeKey !== tenantScope) return;
      setSystemDecisionState(readSystemDecisionCache(tenantScope) as Record<string, SystemDecisionState>);
    };
    window.addEventListener(SYSTEM_DECISION_CACHE_EVENT, onCacheUpdate);
    return () => window.removeEventListener(SYSTEM_DECISION_CACHE_EVENT, onCacheUpdate);
  }, [tenantScope]);

  const systemDecisionCandidates = useMemo(() => {
    return skus
      .filter((sku) => matchesQueueScope(sku, filters.brand, filters.category, search))
      .sort((a, b) => systemSyncPriority(a) - systemSyncPriority(b))
      .slice(0, SYSTEM_SYNC_LIMIT);
  }, [skus, filters.brand, filters.category, search]);
  const systemDecisionCandidateKey = useMemo(
    () => systemDecisionCandidates.map((s) => s.sku_id).join('|'),
    [systemDecisionCandidates],
  );

  const startSystemSync = useCallback((targets: SkuAnalysis[], trigger: SystemDecisionTrigger, forceRefresh = false) => {
    if (mode !== 'eep-live' || targets.length === 0 || syncActiveRef.current) return;
    const now = Date.now();
    const syncTargets = targets.filter((sku) => {
      const existing = systemDecisionStateRef.current[sku.sku_id];
      return forceRefresh || !existing || existing.status === 'error' || now - existing.checkedAt > SYSTEM_SYNC_TTL_MS;
    });

    if (syncTargets.length === 0) {
      setSyncProgress({ active: false, completed: 0, total: 0 });
      return;
    }

    syncActiveRef.current = true;
    setSystemDecisionState((prev) => {
      const next = { ...prev };
      syncTargets.forEach((sku) => {
        next[sku.sku_id] = { ...next[sku.sku_id], status: 'queued', checkedAt: now, trigger };
      });
      return next;
    });
    setSyncProgress({ active: true, completed: 0, total: syncTargets.length });

    let nextIndex = 0;
    let active = 0;
    let completed = 0;
    let cancelled = false;

    const launchNext = () => {
      if (cancelled) return;
      while (active < SYSTEM_SYNC_CONCURRENCY && nextIndex < syncTargets.length) {
        const sku = syncTargets[nextIndex++];
        active += 1;
        setSystemDecisionState((prev) => ({
          ...prev,
          [sku.sku_id]: { ...prev[sku.sku_id], status: 'checking', checkedAt: Date.now(), trigger },
        }));

        recommend(toRecommendationRequest(sku))
          .then((result) => {
            if (cancelled) return;
            setSystemDecisionState((prev) => ({
              ...prev,
              [sku.sku_id]: {
                status: 'live',
                result: { ...result, sku_id: result.sku_id ?? sku.sku_id },
                checkedAt: Date.now(),
                trigger,
              },
            }));
            writeSystemDecisionEntry(tenantScope, sku.sku_id, {
              status: 'live',
              result: { ...result, sku_id: result.sku_id ?? sku.sku_id },
              checkedAt: Date.now(),
              trigger,
            });
          })
          .catch((error: unknown) => {
            if (cancelled) return;
            const message = error instanceof Error ? error.message : String(error);
            setSystemDecisionState((prev) => ({
              ...prev,
              [sku.sku_id]: {
                status: 'error',
                error: message,
                checkedAt: Date.now(),
                trigger,
              },
            }));
            writeSystemDecisionEntry(tenantScope, sku.sku_id, {
              status: 'error',
              error: message,
              checkedAt: Date.now(),
              trigger,
            });
          })
          .finally(() => {
            if (cancelled) return;
            active -= 1;
            completed += 1;
            const stillActive = completed < syncTargets.length;
            syncActiveRef.current = stillActive;
            setSyncProgress({ active: stillActive, completed, total: syncTargets.length });
            launchNext();
          });
      }
    };

    launchNext();

    return () => {
      cancelled = true;
      syncActiveRef.current = false;
    };
  }, [mode, tenantScope]);

  useEffect(() => {
    if (mode !== 'eep-live') return;
    const maybeRunDaily = () => {
      if (!syncActiveRef.current && isDailySystemDecisionDue(tenantScope)) {
        markDailySystemDecisionRun(tenantScope);
        startSystemSync(systemDecisionCandidates, 'daily_9am', true);
      }
    };
    maybeRunDaily();
    const interval = window.setInterval(maybeRunDaily, 60_000);
    return () => window.clearInterval(interval);
  }, [mode, tenantScope, systemDecisionCandidateKey, startSystemSync, systemDecisionCandidates]);

  const liveDecisionBySku = useMemo(() => {
    const map = new Map<string, IE2Result>();
    Object.entries(systemDecisionState).forEach(([skuId, state]) => {
      if (state.status === 'live' && state.result?.recommendation && !state.result.error) {
        map.set(skuId, state.result);
      }
    });
    return map;
  }, [systemDecisionState]);
  const resolvedBandBySku = useMemo(() => {
    const map = new Map<string, QueueBand>();
    skus.forEach((sku) => {
      map.set(sku.sku_id, liveDecisionBySku.get(sku.sku_id)?.recommendation ?? 'UNSCORED');
    });
    return map;
  }, [skus, liveDecisionBySku]);
  const resolvedBand = (sku: SkuAnalysis) => resolvedBandBySku.get(sku.sku_id) ?? 'UNSCORED';
  const liveStatus = (sku: SkuAnalysis): SystemDecisionStatus | undefined => {
    if (mode !== 'eep-live') return undefined;
    const state = systemDecisionState[sku.sku_id];
    if (state) return state.status;
    return 'report';
  };

  const filtered = useMemo(() => {
    return skus.filter((s) => {
      const band = resolvedBandBySku.get(s.sku_id) ?? 'UNSCORED';
      if (filters.brand !== 'ALL' && s.brand !== filters.brand) return false;
      if (filters.category !== 'ALL' && s.category !== filters.category) return false;
      if (filters.decision !== 'ALL' && band !== filters.decision) return false;
      if (search && !`${s.sku_id} ${s.product_name} ${s.brand}`.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [skus, filters, search, resolvedBandBySku]);

  const grouped = useMemo(() => {
    const m: Record<QueueBand, SkuAnalysis[]> = { UNSCORED: [], HOLD: [], PROMOTE: [], MARKDOWN: [], CLEAR: [] };
    filtered.forEach((s) => m[resolvedBandBySku.get(s.sku_id) ?? 'UNSCORED'].push(s));
    return m;
  }, [filtered, resolvedBandBySku]);

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
        subtitle={`${filtered.length} of ${skus.length} SKUs - ${
          syncProgress.active
            ? `system sync ${syncProgress.completed}/${syncProgress.total}`
            : liveDecisionBySku.size > 0
              ? `${liveDecisionBySku.size}/${systemDecisionCandidates.length} cached system decisions`
              : `${systemDecisionCandidates.length} report decisions - sync manually or daily at 9 AM`
        }`}
        actions={
          <div className="hidden md:flex items-center gap-2">
            <button
              onClick={() => startSystemSync(systemDecisionCandidates, 'manual', true)}
              disabled={syncProgress.active}
              className="h-8 px-3 rounded-md border border-border bg-surface-raised text-[12px] font-semibold inline-flex items-center gap-1.5 text-foreground hover:bg-accent"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', syncProgress.active && 'animate-spin')} />
              {syncProgress.active ? 'Syncing' : 'Sync system'}
            </button>
            <div className="flex items-center gap-1 rounded-md border border-border bg-surface-raised p-1">
              <button onClick={() => setView('board')} className={cn('px-2.5 py-1 rounded text-[12px] inline-flex items-center gap-1.5', view === 'board' ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground')}>
                <LayoutGrid className="h-3.5 w-3.5" /> Board
              </button>
              <button onClick={() => setView('table')} className={cn('px-2.5 py-1 rounded text-[12px] inline-flex items-center gap-1.5', view === 'table' ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground')}>
                <TableIcon className="h-3.5 w-3.5" /> Table
              </button>
            </div>
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
          <FilterSelect value={filters.decision} onChange={(v) => setFilters({ ...filters, decision: v as any })} options={['ALL', ...queueBandOrder]} label="Decision" />
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
            {queueBandOrder.map((d) => {
              const items = grouped[d];
              const s = bandStyles(d);
              return (
                <div key={d} className="rounded-xl bg-card border border-border overflow-hidden flex flex-col max-h-[78vh]">
                  <div className={cn('px-4 py-3 border-b border-border bg-gradient-to-br flex items-center justify-between', s.gradient)}>
                    <div className="flex items-center gap-2">
                      <BandBadge band={d} size="lg" />
                      <span className="text-[12px] text-muted-foreground font-mono">{items.length}</span>
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto scrollbar-thin p-2 space-y-2">
                    {items.length === 0 && (
                      <div className="text-center text-[12px] text-muted-foreground py-12">No SKUs in this band</div>
                    )}
                    {items.slice(0, 60).map((sku) => (
                      <SkuCard key={sku.sku_id} sku={sku} onOpen={() => setOpenSku(sku.sku_id)}
                        band={resolvedBand(sku)}
                        liveStatus={liveStatus(sku)}
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
                  {filtered.slice(0, 200).map((s) => {
                    const band = resolvedBand(s);
                    const currentLiveStatus = liveStatus(s);
                    return (
                      <tr key={s.sku_id} className="border-t border-border hover:bg-accent/40 cursor-pointer" onClick={() => setOpenSku(s.sku_id)}>
                        <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" checked={selected.has(s.sku_id)} onChange={() => toggleSel(s.sku_id)} />
                        </td>
                        <td className="px-4 py-2.5 font-mono text-[12px] text-muted-foreground">{s.sku_id}</td>
                        <td className="px-4 py-2.5 font-medium">{s.product_name}</td>
                        <td className="px-4 py-2.5 text-muted-foreground">{s.brand}</td>
                        <td className="px-4 py-2.5 text-right font-mono">{s.current_stock}</td>
                        <td className={cn('px-4 py-2.5 text-right font-mono', dosTextClass(s.days_of_supply))}>{fmtDos(s.days_of_supply, { suffix: false })}</td>
                        <td className={cn('px-4 py-2.5 text-right font-mono', s.margin_pct < 35 ? 'text-decision-clear' : s.margin_pct >= 45 ? 'text-decision-promote' : 'text-foreground')}>{fmtPct(s.margin_pct, 0)}</td>
                        <td className="px-4 py-2.5 text-right font-mono">{fmtUSD(s.retail_price_usd)}</td>
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2">
                            <BandBadge band={band} size="sm" />
                            {currentLiveStatus && <LiveStatusPill status={currentLiveStatus} />}
                          </div>
                        </td>
                        <td className="px-4 py-2.5">
                          <span className={cn('inline-flex px-2 py-0.5 rounded text-[10.5px] font-mono uppercase tracking-wider', statusStyles[recState[scopedSkuKey(s.sku_id, tenantScope)]?.status || 'pending'])}>
                            {recState[scopedSkuKey(s.sku_id, tenantScope)]?.status || 'pending'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
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

function isStaleClearCandidate(sku: SkuAnalysis) {
  if (sku.decision !== 'CLEAR') return false;
  const dos = Number(sku.days_of_supply);
  const age = Number(sku.days_since_launch);
  const margin = Number(sku.margin_pct);
  return age < 90 || !Number.isFinite(dos) || dos < 180 || margin >= 35;
}

function matchesQueueScope(sku: SkuAnalysis, brand: string, category: string, search: string) {
  if (brand !== 'ALL' && sku.brand !== brand) return false;
  if (category !== 'ALL' && sku.category !== category) return false;
  if (search && !`${sku.sku_id} ${sku.product_name} ${sku.brand}`.toLowerCase().includes(search.toLowerCase())) return false;
  return true;
}

function systemSyncPriority(sku: SkuAnalysis) {
  if (isStaleClearCandidate(sku)) return 0;
  if (sku.decision === 'CLEAR') return 1;
  if (Number(sku.days_since_launch) < 30) return 2;
  if (sku.decision === 'MARKDOWN') return 3;
  if (sku.decision === 'PROMOTE') return 4;
  return 5;
}

function toRecommendationRequest(sku: SkuAnalysis): IE2Request {
  return {
    sku_id: sku.sku_id,
    product_name: sku.product_name,
    brand: sku.brand,
    category: sku.category,
    retail_price_usd: sku.retail_price_usd,
    cost_price_usd: sku.cost_price_usd,
    current_stock: sku.current_stock,
    initial_stock: sku.initial_stock,
    days_since_launch: sku.days_since_launch,
    days_since_last_discount: sku.days_since_last_discount,
    days_at_current_price: sku.days_at_current_price,
  };
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

function SkuCard({ sku, band, liveStatus, onOpen, selected, onSelect, status }: {
  sku: SkuAnalysis;
  band: QueueBand;
  liveStatus?: SystemDecisionStatus;
  onOpen: () => void;
  selected: boolean;
  onSelect: () => void;
  status?: string;
}) {
  return (
    <div className={cn('group rounded-lg border bg-card p-3 hover:shadow-md-soft transition cursor-pointer', selected ? 'border-primary ring-1 ring-primary' : 'border-border')} onClick={onOpen}>
      <div className="flex items-start gap-2">
        <input type="checkbox" checked={selected} onClick={(e) => e.stopPropagation()} onChange={onSelect} className="mt-1" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10.5px] text-muted-foreground">{sku.sku_id}</span>
            <BandBadge band={band} size="sm" />
            {liveStatus && <LiveStatusPill status={liveStatus} />}
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
        <Stat label="DOS" value={fmtDos(sku.days_of_supply)} className={dosTextClass(sku.days_of_supply)} />
        <Stat label="Margin" value={fmtPct(sku.margin_pct, 0)} className={sku.margin_pct >= 45 ? 'text-decision-promote' : sku.margin_pct < 35 ? 'text-decision-clear' : ''} />
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[11px] font-mono text-muted-foreground">{fmtUSD(sku.retail_price_usd)}</span>
        <Pencil className="h-3 w-3 text-muted-foreground opacity-0 group-hover:opacity-100" />
      </div>
    </div>
  );
}

function BandBadge({ band, size = 'md' }: { band: QueueBand; size?: 'sm' | 'md' | 'lg' }) {
  if (band !== 'UNSCORED') {
    return <DecisionBadge decision={band} size={size} />;
  }
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border font-mono font-semibold uppercase tracking-wider',
        'bg-muted/40 text-muted-foreground border-muted-foreground/25',
        size === 'sm' && 'text-[10px] px-1.5 py-0.5',
        size === 'md' && 'text-[10.5px] px-2 py-0.5',
        size === 'lg' && 'text-[11.5px] px-2.5 py-1',
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" />
      Needs Sync
    </span>
  );
}

function bandStyles(band: QueueBand) {
  if (band !== 'UNSCORED') return decisionStyles[band];
  return {
    gradient: 'from-muted/50 to-muted/20',
  };
}

function LiveStatusPill({ status }: { status: SystemDecisionStatus }) {
  return (
    <span className={cn(
      'text-[9.5px] font-mono uppercase px-1.5 py-0.5 rounded border',
      status === 'live'
        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
        : status === 'checking'
          ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
          : status === 'queued'
            ? 'border-sky-500/30 bg-sky-500/10 text-sky-300'
            : status === 'report'
              ? 'border-muted-foreground/25 bg-muted/40 text-muted-foreground'
              : 'border-red-500/30 bg-red-500/10 text-red-300',
    )}>
      {status}
    </span>
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
