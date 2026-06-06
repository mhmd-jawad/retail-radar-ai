import { useMemo, useState } from 'react';
import { Sheet, SheetContent } from '@/components/ui/sheet';
import type { SkuAnalysis, IE2Result } from '@/types/domain';
import { useQuery } from '@tanstack/react-query';
import { recommend, fetchPortfolioAccuracy } from '@/lib/adapter';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import { fmtDos, fmtPct, fmtUSD, statusStyles } from '@/lib/format';
import { useSettings } from '@/store/settings';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { scopedSkuKey } from '@/lib/tenantScope';
import { Check, X, Clock, Pencil, Copy, Sparkles, AlertTriangle, Activity, Target } from 'lucide-react';
import { Slider } from '@/components/ui/slider';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useReport } from '@/hooks/useReport';

interface Props {
  sku: SkuAnalysis | null;
  open: boolean;
  onClose: () => void;
}

export function RecommendationDrawer({ sku, open, onClose }: Props) {
  const { recState, setRecStatus, mode } = useSettings();
  const { data: report } = useReport();
  const tenantScope = useTenantScopeKey();
  const [discount, setDiscount] = useState(15);
  const isLive = mode === 'eep-live';

  const { data: ie2 } = useQuery({
    queryKey: ['ie2', tenantScope, sku?.sku_id],
    enabled: !!sku,
    queryFn: async (): Promise<IE2Result> =>
      recommend({
        sku_id: sku!.sku_id, product_name: sku!.product_name, brand: sku!.brand, category: sku!.category,
        retail_price_usd: sku!.retail_price_usd, cost_price_usd: sku!.cost_price_usd,
        current_stock: sku!.current_stock, initial_stock: sku!.initial_stock,
        days_since_launch: sku!.days_since_launch,
        days_since_last_discount: sku!.days_since_last_discount,
        days_at_current_price: sku!.days_at_current_price,
      }),
  });

  const { data: accuracy } = useQuery({
    queryKey: ['portfolio-accuracy', tenantScope, ie2?.recommendation],
    queryFn: () => fetchPortfolioAccuracy(ie2?.recommendation),
    enabled: isLive && !!ie2?.recommendation,
    staleTime: 5 * 60_000,
  });

  const promo = useMemo(() => sku && report ? report.promotions.promote.find((p) => p.sku_id === sku.sku_id) : null, [sku, report]);
  const status = sku ? recState[scopedSkuKey(sku.sku_id, tenantScope)]?.status || 'pending' : 'pending';

  const newPrice = sku ? sku.retail_price_usd * (1 - discount / 100) : 0;
  const marginAfter = sku ? ((newPrice - sku.cost_price_usd) / newPrice) * 100 : 0;

  const act = (s: 'approved' | 'rejected' | 'snoozed' | 'edited') => {
    if (!sku) return;
    setRecStatus(sku.sku_id, s, s === 'edited' ? { editedDiscountPct: discount, editedPriceUsd: Number(newPrice.toFixed(2)) } : {});
    toast.success(`Recommendation ${s}`, { description: `${sku.sku_id} · logged to audit trail.` });
    onClose();
  };

  const copy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    toast.success(`${label} copied`);
  };

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full sm:max-w-2xl p-0 overflow-y-auto scrollbar-thin">
        {sku && (
          <div className="flex flex-col min-h-full">
            {/* Header */}
            <div className="panel-dark p-6 border-b border-panel-border">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[10.5px] font-mono uppercase tracking-[0.16em] text-panel-muted">{sku.sku_id} · {sku.brand}</div>
                  <h2 className="font-display text-[20px] text-panel-foreground font-semibold mt-1 leading-tight">{sku.product_name}</h2>
                  <div className="text-[12.5px] text-panel-muted mt-1">{sku.category}</div>
                </div>
                <div className="flex items-center gap-2">
                  <DecisionBadge decision={ie2?.recommendation || sku.decision} size="lg" />
                  <span className={cn('text-[10.5px] font-mono uppercase px-2 py-0.5 rounded', statusStyles[status])}>{status}</span>
                </div>
              </div>
              <div className="grid grid-cols-4 gap-3 mt-5">
                {[
                  { l: 'Stock', v: sku.current_stock },
                  { l: 'DOS', v: fmtDos(sku.days_of_supply) },
                  { l: 'Margin', v: fmtPct(sku.margin_pct, 0) },
                  { l: 'Price', v: fmtUSD(sku.retail_price_usd) },
                ].map((x) => (
                  <div key={x.l} className="rounded-md bg-white/5 border border-panel-border p-2.5">
                    <div className="text-[9.5px] font-mono uppercase tracking-wider text-panel-muted">{x.l}</div>
                    <div className="text-data text-[16px] text-panel-foreground mt-0.5">{x.v}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="p-6 space-y-6 flex-1">
              {/* Explanation */}
              {ie2 && (
                <div>
                  <div className="text-[10.5px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5 flex items-center gap-2">
                    <Sparkles className="h-3 w-3 text-primary" /> System Decision · {(ie2.confidence * 100).toFixed(0)}% confidence
                  </div>
                  <p className="text-[14px] leading-relaxed text-foreground">{ie2.explanation}</p>
                  {ie2.rule_override && (
                    <div className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-mono px-2 py-1 rounded bg-decision-clear-bg text-decision-clear">
                      <AlertTriangle className="h-3 w-3" /> Rule override: {ie2.rule_override}
                    </div>
                  )}
                  {ie2.error && (
                    <div className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-mono px-2 py-1 rounded bg-decision-clear-bg text-decision-clear">
                      <AlertTriangle className="h-3 w-3" /> Prediction error: {ie2.error}
                    </div>
                  )}
                </div>
              )}

              {/* SHAP */}
              {ie2 && (
                <div>
                  <div className="text-[10.5px] font-mono uppercase tracking-wider text-muted-foreground mb-2">Top 5 Reasons (SHAP)</div>
                  <div className="space-y-1.5">
                    {ie2.shap_top5.map((r) => (
                      <div key={r.feature} className="flex items-center gap-3">
                        <div className="text-[12px] w-44 truncate text-foreground">{r.feature}</div>
                        <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden relative">
                          <div className={cn('absolute top-0 h-full', r.direction === 'positive' ? 'bg-decision-promote left-1/2' : 'bg-decision-clear right-1/2')}
                            style={{ width: `${Math.abs(r.impact) * 50}%` }} />
                          <div className="absolute top-0 left-1/2 h-full w-px bg-border" />
                        </div>
                        <div className="text-[11px] font-mono w-12 text-right text-muted-foreground">{(r.impact * 100).toFixed(0)}%</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Margin simulator (markdown) */}
              {(ie2?.recommendation === 'MARKDOWN' || sku.decision === 'MARKDOWN') && (
                <div className="rounded-lg border border-decision-markdown/20 bg-decision-markdown-bg/50 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-[12px] font-semibold text-decision-markdown uppercase tracking-wider">Margin Simulator</div>
                    <div className="text-[11px] font-mono text-muted-foreground">Floor 35%</div>
                  </div>
                  <Slider value={[discount]} min={0} max={50} step={1} onValueChange={(v) => setDiscount(v[0])} />
                  <div className="grid grid-cols-3 gap-3 mt-4">
                    <Cell label="Discount" value={`-${discount}%`} />
                    <Cell label="New price" value={fmtUSD(newPrice, { decimals: 2 })} />
                    <Cell label="Margin after" value={fmtPct(marginAfter, 1)} className={marginAfter < 35 ? 'text-decision-clear' : 'text-decision-promote'} />
                  </div>
                </div>
              )}

              {/* Live competitor context */}
              {ie2?.competitor_signals_used && (
                <div>
                  <div className="text-[10.5px] font-mono uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-2">
                    <Activity className="h-3 w-3" /> Live Competitor Signal · {ie2.processing_time_ms}ms
                  </div>
                  <div className="rounded-lg border border-border bg-card p-3">
                    {ie2.competitor_signals_used.num_competitors_tracked > 0 ? (
                      <>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                          <SignalCell label="Cheapest" value={ie2.competitor_signals_used.cheapest_competitor_name || 'unknown'} />
                          <SignalCell label="Min price" value={fmtUSD(ie2.competitor_signals_used.competitor_min_price, { decimals: 2 })} />
                          <SignalCell label="Price gap" value={fmtPct(ie2.competitor_signals_used.price_gap_pct * 100, 1)} />
                          <SignalCell label="Freshness" value={`${ie2.competitor_signals_used.data_freshness_hours}h`} />
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
                          <SignalCell label="Matches" value={`${ie2.competitor_signals_used.num_competitors_tracked}`} />
                          <SignalCell label="Match type" value={ie2.competitor_signals_used.match_type || 'matched'} />
                          <SignalCell label="On sale" value={`${ie2.competitor_signals_used.competitors_on_sale_count}`} />
                          <SignalCell label="OOS" value={`${ie2.competitor_signals_used.competitors_out_of_stock_count}`} />
                        </div>
                      </>
                    ) : (
                      <div className="flex items-start gap-2 text-[12.5px] text-muted-foreground">
                        <AlertTriangle className="h-4 w-4 text-decision-clear shrink-0 mt-0.5" />
                        <span>{ie2.competitor_signals_used.fallback_reason || 'No live competitor match was available for this SKU.'}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Campaign preview */}
              {(ie2?.recommendation === 'PROMOTE' || sku.decision === 'PROMOTE') && promo?.creative && (
                <div>
                  <div className="text-[10.5px] font-mono uppercase tracking-wider text-muted-foreground mb-2">Campaign Creative · confidence {Math.round(promo.creative.generation_confidence * 100)}%</div>
                  <div className="rounded-lg border border-decision-promote/20 bg-decision-promote-bg p-4 space-y-3">
                    <div>
                      <div className="font-display text-[16px] font-semibold leading-tight">{promo.creative.headline}</div>
                      <div className="text-[12.5px] text-muted-foreground mt-1">{promo.creative.subheadline}</div>
                    </div>
                    {[
                      { l: 'Instagram', v: promo.creative.instagram_post },
                      { l: 'WhatsApp', v: promo.creative.whatsapp_broadcast },
                      { l: 'Facebook', v: promo.creative.facebook_post },
                    ].map((c) => (
                      <div key={c.l} className="rounded-md bg-card border border-border p-2.5">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10.5px] font-mono uppercase tracking-wider text-muted-foreground">{c.l}</span>
                          <button onClick={() => copy(c.v, c.l)} className="text-[10.5px] font-mono inline-flex items-center gap-1 text-primary hover:underline"><Copy className="h-3 w-3" />Copy</button>
                        </div>
                        <p className="text-[12.5px] whitespace-pre-line">{c.v}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Service metadata */}
              {ie2 && (
                <div className="grid grid-cols-3 gap-2 text-[11px] font-mono text-muted-foreground">
                  <div>model: <span className="text-foreground">{ie2.model_version}</span></div>
                  <div>fallback: <span className="text-foreground">{String(ie2.fallback_used)}</span></div>
                  <div>approval: <span className="text-foreground">{String(ie2.requires_human_approval)}</span></div>
                </div>
              )}
            </div>

            {/* Portfolio accuracy signal */}
            {isLive && accuracy && accuracy.decision_count >= 3 && ie2 && (
              <div className="mx-4 mb-3 flex items-center gap-2 px-3 py-2 rounded-md bg-indigo-500/5 border border-indigo-500/15 text-[11.5px]">
                <Target className="h-3.5 w-3.5 text-indigo-400 shrink-0" />
                <span className="text-muted-foreground">Past accuracy for</span>
                <span className="font-semibold text-indigo-300">{ie2.recommendation}</span>
                <span className="text-muted-foreground">decisions:</span>
                <span className="font-bold text-indigo-400 ml-0.5">
                  {accuracy.by_type[ie2.recommendation] != null
                    ? `${accuracy.by_type[ie2.recommendation]}%`
                    : `${accuracy.avg_accuracy ?? '—'}%`}
                </span>
                <span className="text-muted-foreground ml-auto">({accuracy.decision_count} tracked)</span>
              </div>
            )}

            {/* Sticky actions */}
            <div className="sticky bottom-0 border-t border-border bg-background/95 backdrop-blur p-4 flex items-center gap-2">
              <button onClick={() => act('approved')} className="flex-1 h-10 rounded-md bg-decision-promote text-white font-semibold text-[13px] inline-flex items-center justify-center gap-2"><Check className="h-4 w-4" />Approve</button>
              <button onClick={() => act('edited')} className="flex-1 h-10 rounded-md bg-foreground text-background font-semibold text-[13px] inline-flex items-center justify-center gap-2"><Pencil className="h-4 w-4" />Save edit</button>
              <button onClick={() => act('snoozed')} className="h-10 px-3 rounded-md border border-border font-semibold text-[13px] inline-flex items-center gap-1.5"><Clock className="h-4 w-4" />Snooze</button>
              <button onClick={() => act('rejected')} className="h-10 px-3 rounded-md border border-decision-clear/30 text-decision-clear font-semibold text-[13px] inline-flex items-center gap-1.5"><X className="h-4 w-4" />Reject</button>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Cell({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-md bg-card border border-border p-2.5">
      <div className="text-[10.5px] font-mono uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={cn('text-data text-[16px] font-semibold mt-0.5', className)}>{value}</div>
    </div>
  );
}

function SignalCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-surface-sunken border border-border p-2.5 min-w-0">
      <div className="text-[10.5px] font-mono uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="text-[12.5px] font-semibold mt-0.5 truncate">{value}</div>
    </div>
  );
}
