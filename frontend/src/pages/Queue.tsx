import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import { decisionStyles, dosTextClass, fmtDos, fmtPct, fmtUSD, statusStyles } from '@/lib/format';
import { useSettings } from '@/store/settings';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { scopedSkuKey } from '@/lib/tenantScope';
import {
  fetchSystemDecisionLatest,
  fetchSystemDecisionRun,
  fetchReviewAnalytics,
  fetchRecommendationReviews,
  startSystemDecisionSyncAll,
  startSystemDecisionSyncUnsynced,
} from '@/lib/adapter';
import type {
  Decision,
  IE2Result,
  RecommendationReview,
  ReviewAnalytics,
  SkuAnalysis,
  SystemDecisionLatestItem,
  SystemDecisionLatestStatus,
  SystemDecisionRun,
} from '@/types/domain';
import { Search, LayoutGrid, Table as TableIcon, Filter, Check, X, Clock, Pencil, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { RecommendationDrawer } from '@/components/recommendations/RecommendationDrawer';

const decisionOrder: Decision[] = ['CLEAR', 'MARKDOWN', 'PROMOTE', 'HOLD'];
type QueueBand = Decision | 'UNSCORED';
type ActionFilter = QueueBand | 'ALL';
const queueBandOrder: QueueBand[] = ['UNSCORED', ...decisionOrder];
const actionTabs: ActionFilter[] = ['ALL', 'PROMOTE', 'MARKDOWN', 'CLEAR', 'HOLD', 'UNSCORED'];

type ActionDetails = {
  reason: string;
  suggested: string;
};

export default function Queue() {
  const { data: report, isLoading } = useReport();
  const { recState, setRecStatus, mode } = useSettings();
  const tenantScope = useTenantScopeKey();
  const queryClient = useQueryClient();
  const [view, setView] = useState<'board' | 'table'>('board');
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<{ brand: string; category: string; decision: ActionFilter }>({
    brand: 'ALL', category: 'ALL', decision: 'ALL',
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openSku, setOpenSku] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  const skus = useMemo(() => report?.inventory.sku_analysis ?? [], [report]);
  const brands = useMemo(() => Array.from(new Set(skus.map((s) => s.brand))).sort(), [skus]);
  const categories = useMemo(() => Array.from(new Set(skus.map((s) => s.category))).sort(), [skus]);

  const systemDecisions = useQuery({
    queryKey: ['system-decisions-latest', tenantScope],
    queryFn: fetchSystemDecisionLatest,
    enabled: mode === 'eep-live',
    retry: false,
    refetchInterval: activeRunId ? 5_000 : false,
  });

  const runQuery = useQuery({
    queryKey: ['system-decision-run', tenantScope, activeRunId],
    queryFn: () => fetchSystemDecisionRun(activeRunId!),
    enabled: mode === 'eep-live' && Boolean(activeRunId),
    retry: false,
    refetchInterval: activeRunId ? 3_000 : false,
  });

  useEffect(() => {
    const run = runQuery.data;
    if (!run || isRunActive(run)) return;
    queryClient.invalidateQueries({ queryKey: ['system-decisions-latest'] });
    queryClient.invalidateQueries({ queryKey: ['report'] });
    queryClient.invalidateQueries({ queryKey: ['report-live'] });
    setActiveRunId(null);
    if (run.status === 'completed') {
      toast.success('System decision sync completed', {
        description: `${run.completed_count}/${run.total_count} SKUs synced.`,
      });
    } else {
      toast.warning('System decision sync finished with issues', {
        description: `${run.failed_count}/${run.total_count} SKUs failed. Open Needs Sync for details.`,
      });
    }
  }, [queryClient, runQuery.data]);

  const latestBySku = useMemo(() => {
    const map = new Map<string, SystemDecisionLatestItem>();
    (systemDecisions.data?.items || []).forEach((item) => map.set(item.sku_id, item));
    return map;
  }, [systemDecisions.data]);

  const liveDecisionBySku = useMemo(() => {
    const map = new Map<string, IE2Result>();
    latestBySku.forEach((item, skuId) => {
      const result = resultFromLatest(item);
      if (result) map.set(skuId, result);
    });
    return map;
  }, [latestBySku]);

  const reviewsQuery = useQuery({
    queryKey: ['recommendation-reviews', tenantScope],
    queryFn: () => fetchRecommendationReviews({ limit: 500 }),
    enabled: mode === 'eep-live',
    retry: false,
    staleTime: 30_000,
  });

  const reviewBySku = useMemo(() => {
    const map = new Map<string, RecommendationReview>();
    (reviewsQuery.data ?? []).forEach((r) => map.set(r.sku_id, r));
    return map;
  }, [reviewsQuery.data]);

  const resolvedBand = (sku: SkuAnalysis): QueueBand => {
    // Human override takes priority — move the card to the overridden band
    const review = reviewBySku.get(sku.sku_id);
    if (review?.review_action === 'override' && review.final_decision) {
      return review.final_decision as Decision;
    }
    if (mode !== 'eep-live') return sku.decision;
    return liveDecisionBySku.get(sku.sku_id)?.recommendation ?? 'UNSCORED';
  };

  const filtered = useMemo(() => {
    return skus.filter((s) => {
      const band = resolvedBand(s);
      if (filters.brand !== 'ALL' && s.brand !== filters.brand) return false;
      if (filters.category !== 'ALL' && s.category !== filters.category) return false;
      if (filters.decision !== 'ALL' && band !== filters.decision) return false;
      if (search && !`${s.sku_id} ${s.product_name} ${s.brand}`.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [skus, filters, search, liveDecisionBySku, reviewBySku, mode]);

  const actionCounts = useMemo(() => {
    const counts: Record<ActionFilter, number> = { ALL: 0, UNSCORED: 0, HOLD: 0, PROMOTE: 0, MARKDOWN: 0, CLEAR: 0 };
    skus.forEach((sku) => {
      if (filters.brand !== 'ALL' && sku.brand !== filters.brand) return;
      if (filters.category !== 'ALL' && sku.category !== filters.category) return;
      if (search && !`${sku.sku_id} ${sku.product_name} ${sku.brand}`.toLowerCase().includes(search.toLowerCase())) return;
      const band = resolvedBand(sku);
      counts.ALL += 1;
      counts[band] += 1;
    });
    return counts;
  }, [skus, filters.brand, filters.category, search, liveDecisionBySku, reviewBySku, mode]);

  const grouped = useMemo(() => {
    const m: Record<QueueBand, SkuAnalysis[]> = { UNSCORED: [], HOLD: [], PROMOTE: [], MARKDOWN: [], CLEAR: [] };
    filtered.forEach((s) => m[resolvedBand(s)].push(s));
    return m;
  }, [filtered, liveDecisionBySku, reviewBySku, mode]);

  const syncAll = useMutation({
    mutationFn: startSystemDecisionSyncAll,
    onSuccess: (run) => handleRunStarted(run, setActiveRunId, queryClient),
    onError: (error: Error) => toast.error('Sync all failed to start', { description: error.message }),
  });

  const syncUnsynced = useMutation({
    mutationFn: startSystemDecisionSyncUnsynced,
    onSuccess: (run) => handleRunStarted(run, setActiveRunId, queryClient),
    onError: (error: Error) => toast.error('Sync unsynced failed to start', { description: error.message }),
  });

  const reviewAnalytics = useQuery({
    queryKey: ['review-analytics', tenantScope],
    queryFn: () => fetchReviewAnalytics(),
    enabled: mode === 'eep-live',
    retry: false,
    staleTime: 60_000,
  });

  const competitorBySku = useMemo(() => {
    return new Map((report?.competitor.sku_positioning ?? []).map((item) => [item.sku_id, item]));
  }, [report]);

  const actionDetailsBySku = useMemo(() => {
    const map = new Map<string, ActionDetails>();
    report?.promotions.promote.forEach((item) => {
      map.set(item.sku_id, {
        reason: item.reason,
        suggested: `${item.expected_lift_pct.toFixed(0)}% lift`,
      });
    });
    report?.promotions.markdown.forEach((item) => {
      map.set(item.sku_id, {
        reason: item.reason,
        suggested: `${item.suggested_discount_pct.toFixed(0)}% off -> ${fmtUSD(item.suggested_price_usd)}`,
      });
    });
    report?.promotions.clearance.forEach((item) => {
      map.set(item.sku_id, {
        reason: `${item.age_days}d old stock`,
        suggested: `Clear at ${fmtUSD(item.suggested_price_usd)}`,
      });
    });
    report?.promotions.hold_pricing.forEach((item) => {
      map.set(item.sku_id, {
        reason: item.reason,
        suggested: 'Hold price',
      });
    });
    return map;
  }, [report]);

  if (isLoading || !report) {
    return (<><TopBar title="Recommendations Queue" /><PageSkeleton /></>);
  }

  const run = runQuery.data || systemDecisions.data?.latest_run || null;
  const syncActive = isRunActive(run) || syncAll.isPending || syncUnsynced.isPending;
  const summary = systemDecisions.data?.summary;
  const openSkuItem = openSku ? skus.find((s) => s.sku_id === openSku) || null : null;
  const openSystemDecision = openSku ? liveDecisionBySku.get(openSku) : undefined;

  const toggleSel = (sku: string) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(sku)) {
        n.delete(sku);
      } else {
        n.add(sku);
      }
      return n;
    });
  };

  const bulkAction = (status: 'approved' | 'rejected' | 'snoozed') => {
    if (status === 'approved') {
      const selectedSkus = skus.filter((sku) => selected.has(sku.sku_id));
      const selectedBands = selectedSkus.map((sku) => resolvedBand(sku));
      const promoteCount = selectedBands.filter((band) => band === 'PROMOTE').length;
      const markdownCount = selectedBands.filter((band) => band === 'MARKDOWN').length;
      const clearCount = selectedBands.filter((band) => band === 'CLEAR').length;
      const estimatedApiActions = promoteCount + markdownCount + clearCount;
      const ok = window.confirm(
        `Approve ${selected.size} selected recommendation(s)?\n\n` +
        `Estimated costly actions if executed later: ${estimatedApiActions} API/campaign action(s) ` +
        `(${promoteCount} promote, ${markdownCount} markdown, ${clearCount} clear).\n\n` +
        'This approval only updates the dashboard status. Campaign generation or notifications still require a separate execution step.',
      );
      if (!ok) return;
    }
    selected.forEach((sku) => setRecStatus(sku, status));
    toast.success(`${selected.size} SKUs ${status}`, { description: 'Logged to audit trail.' });
    setSelected(new Set());
  };

  return (
    <>
      <TopBar
        title="Recommendations Queue"
        subtitle={`${filtered.length} of ${skus.length} SKUs - ${queueSubtitle(mode, summary, run)}`}
        actions={
          <div className="hidden md:flex items-center gap-2">
            <button
              onClick={() => syncUnsynced.mutate()}
              disabled={mode !== 'eep-live' || syncActive}
              className="h-8 px-3 rounded-md border border-border bg-surface-raised text-[12px] font-semibold inline-flex items-center gap-1.5 text-foreground hover:bg-accent disabled:opacity-50"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', syncActive && 'animate-spin')} />
              Sync Unsynced
            </button>
            <button
              onClick={() => syncAll.mutate()}
              disabled={mode !== 'eep-live' || syncActive}
              className="h-8 px-3 rounded-md border border-primary/30 bg-primary/10 text-[12px] font-semibold inline-flex items-center gap-1.5 text-primary hover:bg-primary/15 disabled:opacity-50"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', syncActive && 'animate-spin')} />
              Sync All
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
        <div className="flex flex-wrap items-center gap-1 rounded-lg border border-border bg-surface-raised p-1">
          {actionTabs.map((band) => {
            const active = filters.decision === band;
            const count = actionCounts[band];
            return (
              <button
                key={band}
                onClick={() => setFilters({ ...filters, decision: band })}
                className={cn(
                  'h-8 px-3 rounded-md text-[12px] font-semibold inline-flex items-center gap-2 transition-colors',
                  active ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
                )}
              >
                {band === 'ALL' ? 'All actions' : <BandBadge band={band} size="sm" />}
                <span className={cn('font-mono text-[10.5px]', active ? 'text-background/70' : 'text-muted-foreground')}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {mode === 'eep-live' && reviewAnalytics.data && reviewAnalytics.data.total_reviews > 0 && (
          <ReviewAnalyticsStrip data={reviewAnalytics.data} />
        )}

        {/* Filters bar */}
        <div className="flex flex-wrap items-center gap-2 p-3 rounded-xl bg-surface-raised border border-border">
          <div className="flex items-center gap-2 min-w-[260px] flex-1 px-3 h-9 rounded-md border border-border bg-card">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="SKU, product, brand..." className="bg-transparent outline-none text-[13px] flex-1" />
          </div>
          <FilterSelect value={filters.brand} onChange={(v) => setFilters({ ...filters, brand: v })} options={['ALL', ...brands]} label="Brand" />
          <FilterSelect value={filters.category} onChange={(v) => setFilters({ ...filters, category: v })} options={['ALL', ...categories]} label="Category" />
          <FilterSelect value={filters.decision} onChange={(v) => setFilters({ ...filters, decision: v as ActionFilter })} options={['ALL', ...queueBandOrder]} label="Decision" />
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
              const syncingCount = items.filter((item) => latestBySku.get(item.sku_id)?.status === 'syncing').length;
              const s = bandStyles(d);
              return (
                <div key={d} className="rounded-xl bg-card border border-border overflow-hidden flex flex-col max-h-[78vh]">
                  <div className={cn('px-4 py-3 border-b border-border bg-gradient-to-br flex items-center justify-between', s.gradient)}>
                    <div className="flex items-center gap-2">
                      <BandBadge band={d} size="lg" />
                      <span className="text-[12px] text-muted-foreground font-mono">{items.length}</span>
                      {syncingCount > 0 && (
                        <span className="text-[10px] font-mono uppercase tracking-wider text-amber-300">
                          {syncingCount} syncing
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto scrollbar-thin p-2 space-y-2">
                    {items.length === 0 && (
                      <div className="text-center text-[12px] text-muted-foreground py-12">No SKUs in this band</div>
                    )}
                    {items.slice(0, 60).map((sku) => {
                      const latest = latestBySku.get(sku.sku_id);
                      return (
                        <SkuCard
                          key={sku.sku_id}
                          sku={sku}
                          onOpen={() => setOpenSku(sku.sku_id)}
                          band={resolvedBand(sku)}
                          latest={latest}
                          review={reviewBySku.get(sku.sku_id)}
                          selected={selected.has(sku.sku_id)}
                          onSelect={() => toggleSel(sku.sku_id)}
                          status={recState[scopedSkuKey(sku.sku_id, tenantScope)]?.status}
                        />
                      );
                    })}
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
                    <th className="px-4 py-3 text-left">Category</th>
                    <th className="px-4 py-3 text-right">Stock</th>
                    <th className="px-4 py-3 text-right">DOS</th>
                    <th className="px-4 py-3 text-right">Margin</th>
                    <th className="px-4 py-3 text-right">Price</th>
                    <th className="px-4 py-3 text-right">Competitor</th>
                    <th className="px-4 py-3 text-right">Gap</th>
                    <th className="px-4 py-3 text-left">Action</th>
                    <th className="px-4 py-3 text-left">Sync</th>
                    <th className="px-4 py-3 text-right">Confidence</th>
                    <th className="px-4 py-3 text-left">Suggested</th>
                    <th className="px-4 py-3 text-left">Reason</th>
                    <th className="px-4 py-3 text-left">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.slice(0, 200).map((s) => {
                    const band = resolvedBand(s);
                    const latest = latestBySku.get(s.sku_id);
                    const liveResult = liveDecisionBySku.get(s.sku_id);
                    const position = competitorBySku.get(s.sku_id);
                    const detail = actionDetailsBySku.get(s.sku_id);
                    const confidence = liveResult?.confidence;
                    const suggested = liveResult?.suggested_price_usd
                      ? `${fmtUSD(liveResult.suggested_price_usd)}${liveResult.suggested_discount_pct ? ` · ${liveResult.suggested_discount_pct.toFixed(0)}% off` : ''}`
                      : detail?.suggested ?? (band === 'HOLD' ? 'Hold price' : 'Sync for suggestion');
                    const reason = liveResult?.explanation || detail?.reason || 'Awaiting live recommendation';
                    return (
                      <tr key={s.sku_id} className="border-t border-border hover:bg-accent/40 cursor-pointer" onClick={() => setOpenSku(s.sku_id)}>
                        <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" checked={selected.has(s.sku_id)} onChange={() => toggleSel(s.sku_id)} />
                        </td>
                        <td className="px-4 py-2.5 font-mono text-[12px] text-muted-foreground">{s.sku_id}</td>
                        <td className="px-4 py-2.5 font-medium">{s.product_name}</td>
                        <td className="px-4 py-2.5 text-muted-foreground">{s.brand}</td>
                        <td className="px-4 py-2.5 text-muted-foreground">{s.category}</td>
                        <td className="px-4 py-2.5 text-right font-mono">{s.current_stock}</td>
                        <td className={cn('px-4 py-2.5 text-right font-mono', dosTextClass(s.days_of_supply))}>{fmtDos(s.days_of_supply, { suffix: false })}</td>
                        <td className={cn('px-4 py-2.5 text-right font-mono', s.margin_pct < 35 ? 'text-decision-clear' : s.margin_pct >= 45 ? 'text-decision-promote' : 'text-foreground')}>{fmtPct(s.margin_pct, 0)}</td>
                        <td className="px-4 py-2.5 text-right font-mono">{fmtUSD(s.retail_price_usd)}</td>
                        <td className="px-4 py-2.5 text-right font-mono">
                          {position?.market_min_usd ? fmtUSD(position.market_min_usd) : '—'}
                        </td>
                        <td className={cn('px-4 py-2.5 text-right font-mono', (position?.price_gap_pct ?? 0) > 10 ? 'text-decision-markdown' : (position?.price_gap_pct ?? 0) < -10 ? 'text-decision-promote' : 'text-muted-foreground')}>
                          {position ? `${position.price_gap_pct > 0 ? '+' : ''}${fmtPct(position.price_gap_pct, 1)}` : '—'}
                        </td>
                        <td className="px-4 py-2.5"><BandBadge band={band} size="sm" /></td>
                        <td className="px-4 py-2.5">
                          <div className="flex flex-col gap-1">
                            <SyncStatusPill status={latest?.status || 'pending'} />
                            {latest?.error_code && <span className="text-[10px] font-mono text-decision-clear">{latest.error_code}</span>}
                          </div>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono">
                          {typeof confidence === 'number' ? fmtPct(confidence * 100, 0) : latest?.status === 'live' ? '—' : 'Sync'}
                        </td>
                        <td className="px-4 py-2.5 text-muted-foreground max-w-[180px] truncate">{suggested}</td>
                        <td className="px-4 py-2.5 text-muted-foreground max-w-[260px] truncate">{reason}</td>
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
        sku={openSkuItem}
        systemDecision={openSystemDecision}
        disableLiveFetch
        open={!!openSku}
        onClose={() => setOpenSku(null)}
      />
    </>
  );
}

function handleRunStarted(
  run: SystemDecisionRun,
  setActiveRunId: (runId: string | null) => void,
  queryClient: ReturnType<typeof useQueryClient>,
) {
  queryClient.invalidateQueries({ queryKey: ['system-decisions-latest'] });
  if (run.total_count === 0 || !isRunActive(run)) {
    toast.info('No SKUs need syncing', { description: 'The backend did not find any matching sync targets.' });
    return;
  }
  setActiveRunId(run.id);
  toast.success(run.already_running ? 'System sync already running' : 'System sync started', {
    description: `${run.total_count} SKUs queued through EEP -> IE1 -> IE2.`,
  });
}

function queueSubtitle(mode: string, summary: { active_skus: number; live_count: number; error_count: number; unsynced_count: number } | undefined, run: SystemDecisionRun | null) {
  if (mode !== 'eep-live') return 'report decisions shown in local mode';
  if (run && isRunActive(run)) {
    return `system sync ${run.completed_count}/${run.total_count} (${run.failed_count} errors)`;
  }
  if (!summary) return 'loading persisted system decisions';
  return `${summary.live_count}/${summary.active_skus} live decisions · ${summary.error_count} errors · ${summary.unsynced_count} need sync`;
}

function resultFromLatest(item: SystemDecisionLatestItem): IE2Result | undefined {
  if (item.status !== 'live' || !item.recommendation) return undefined;
  const payload = item.decision_payload || {};
  return {
    ...payload,
    sku_id: item.sku_id,
    product_name: item.product_name || payload.product_name,
    recommendation: item.recommendation,
    confidence: Number(item.confidence ?? payload.confidence ?? 0),
    explanation: payload.explanation || '',
    shap_top5: payload.shap_top5 || [],
    rule_override: item.rule_override ?? payload.rule_override ?? null,
    fallback_used: Boolean(item.fallback_used ?? payload.fallback_used),
    suggested_discount_pct: item.suggested_discount_pct ?? payload.suggested_discount_pct,
    suggested_price_usd: item.suggested_price_usd ?? payload.suggested_price_usd,
    margin_after_action_pct: payload.margin_after_action_pct,
    model_version: item.model_version || payload.model_version || 'unknown',
    processing_time_ms: Number(payload.processing_time_ms ?? 0),
    requires_human_approval: Boolean(item.requires_human_approval ?? payload.requires_human_approval),
    competitor_signals_used: item.competitor_signals ?? payload.competitor_signals_used ?? null,
    input_context: item.input_context ?? payload.input_context ?? null,
  };
}

function isRunActive(run?: SystemDecisionRun | null) {
  return run?.status === 'queued' || run?.status === 'running';
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

function SkuCard({ sku, band, latest, review, onOpen, selected, onSelect, status }: {
  sku: SkuAnalysis;
  band: QueueBand;
  latest?: SystemDecisionLatestItem;
  review?: RecommendationReview;
  onOpen: () => void;
  selected: boolean;
  onSelect: () => void;
  status?: string;
}) {
  const isSyncing = latest?.status === 'syncing';
  const isHumanOverride = review?.review_action === 'override' && !!review.final_decision;
  const isHumanAccepted = review?.review_action === 'accept';
  const isHumanRejected = review?.review_action === 'reject';
  return (
    <div
      className={cn(
        'group rounded-lg border bg-card p-3 hover:shadow-md-soft transition cursor-pointer',
        selected ? 'border-primary ring-1 ring-primary' : 'border-border',
        isSyncing && 'border-amber-400/70 ring-1 ring-amber-400/40 bg-amber-500/[0.04]',
        isHumanOverride && 'border-violet-500/40 ring-1 ring-violet-500/20',
        isHumanRejected && 'opacity-60',
      )}
      onClick={onOpen}
    >
      <div className="flex items-start gap-2">
        <input type="checkbox" checked={selected} onClick={(e) => e.stopPropagation()} onChange={onSelect} className="mt-1" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-[10.5px] text-muted-foreground">{sku.sku_id}</span>
            <BandBadge band={band} size="sm" />
            {isHumanOverride && (
              <span className="inline-flex items-center gap-1 text-[9px] font-mono uppercase px-1.5 py-0.5 rounded border border-violet-500/40 bg-violet-500/10 text-violet-300">
                <Pencil className="h-2.5 w-2.5" /> overridden
              </span>
            )}
            {isHumanAccepted && (
              <span className="inline-flex items-center gap-1 text-[9px] font-mono uppercase px-1.5 py-0.5 rounded border border-emerald-500/40 bg-emerald-500/10 text-emerald-300">
                <Check className="h-2.5 w-2.5" /> approved
              </span>
            )}
            {isHumanRejected && (
              <span className="inline-flex items-center gap-1 text-[9px] font-mono uppercase px-1.5 py-0.5 rounded border border-red-500/40 bg-red-500/10 text-red-300">
                <X className="h-2.5 w-2.5" /> rejected
              </span>
            )}
            <SyncStatusPill status={latest?.status || 'pending'} />
            {status && status !== 'pending' && (
              <span className={cn('text-[9.5px] font-mono uppercase px-1.5 rounded', statusStyles[status as keyof typeof statusStyles])}>
                {status}
              </span>
            )}
          </div>
          <div className="text-[13px] font-semibold leading-snug mt-0.5 truncate">{sku.product_name}</div>
          <div className="text-[11px] text-muted-foreground mt-0.5">{sku.brand} · {sku.category}</div>
          {isSyncing && (
            <div className="mt-2 rounded-md border border-amber-400/20 bg-amber-500/10 px-2 py-1 text-[10.5px] font-mono uppercase tracking-wider text-amber-200">
              Syncing through IE1 matching to IE2 decision
            </div>
          )}
          {latest?.status === 'error' && (
            <div className="mt-2 rounded-md border border-red-500/20 bg-red-500/10 px-2 py-1 text-[10.5px] text-red-300">
              <span className="font-mono">{latest.error_stage || 'SYNC'} / {latest.error_code || 'ERROR'}:</span> {latest.error_detail || 'Decision sync failed.'}
            </div>
          )}
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

function SyncStatusPill({ status }: { status: SystemDecisionLatestStatus }) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 text-[9.5px] font-mono uppercase px-1.5 py-0.5 rounded border',
      status === 'live'
        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
        : status === 'syncing'
          ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
          : status === 'pending'
            ? 'border-muted-foreground/25 bg-muted/40 text-muted-foreground'
            : 'border-red-500/30 bg-red-500/10 text-red-300',
    )}>
      {status === 'syncing' && <span className="h-1.5 w-1.5 rounded-full bg-amber-300 animate-pulse" />}
      {status === 'pending' ? 'unsynced' : status}
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

function ReviewAnalyticsStrip({ data }: { data: ReviewAnalytics }) {
  const pct = (v: number | null) => (v == null ? '—' : `${Math.round(v * 100)}%`);
  const cells = [
    { l: 'Reviews', v: `${data.total_reviews}`, hint: 'human validations logged' },
    { l: 'Acceptance', v: pct(data.acceptance_rate), hint: `${data.accept_count} accepted` },
    { l: 'Override', v: pct(data.override_rate), hint: `${data.override_count} overridden` },
    { l: 'Agreement', v: pct(data.agreement_rate), hint: 'human ↔ system match' },
    { l: 'Rejected', v: `${data.reject_count}`, hint: 'declined' },
  ];
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3">
      <div className="text-[10.5px] font-mono uppercase tracking-wider text-muted-foreground mb-2">
        Human validation · acceptance & override
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {cells.map((c) => (
          <div key={c.l} className="rounded-md bg-card border border-border p-2.5">
            <div className="text-[9.5px] font-mono uppercase tracking-wider text-muted-foreground">{c.l}</div>
            <div className="text-data text-[18px] font-semibold mt-0.5">{c.v}</div>
            <div className="text-[10px] text-muted-foreground mt-0.5 truncate">{c.hint}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
