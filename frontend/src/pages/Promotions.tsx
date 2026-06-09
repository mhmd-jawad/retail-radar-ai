import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useLiveReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import { fmtPct, fmtUSD } from '@/lib/format';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  ChevronDown, ChevronUp, Copy, ExternalLink, Loader2, RefreshCw,
  Sparkles, TrendingUp, CheckCircle2, Package, Tag, PauseCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useSettings } from '@/store/settings';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { scopedSkuKey } from '@/lib/tenantScope';
import { generateAndPublishCampaign, patchInventoryPrice, recordDecision, persistCampaign } from '@/lib/adapter';
import type {
  CampaignCreative, ClearanceItem, HoldPricingItem,
  MarkdownItem, PromoteItem,
} from '@/types/domain';

// ─────────────────────────────────────────────────────────────────────────────
// Brand icons (Lucide has no social brand icons)
// ─────────────────────────────────────────────────────────────────────────────

function FacebookIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z" />
    </svg>
  );
}

function InstagramIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z" />
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Micro-components
// ─────────────────────────────────────────────────────────────────────────────

function ToneBadge({ tone }: { tone: CampaignCreative['tone_used'] }) {
  const styles: Record<CampaignCreative['tone_used'], string> = {
    urgent:       'bg-red-500/15 text-red-400 border-red-500/30',
    aspirational: 'bg-violet-500/15 text-violet-400 border-violet-500/30',
    value_focused:'bg-amber-500/15 text-amber-400 border-amber-500/30',
  };
  return (
    <span className={cn('text-[10px] font-mono uppercase px-2 py-0.5 rounded border', styles[tone])}>
      {tone.replace('_', ' ')}
    </span>
  );
}

function UrgencyPill({ urgency }: { urgency: string }) {
  const styles: Record<string, string> = {
    low:      'bg-muted/60 text-muted-foreground',
    medium:   'bg-amber-500/15 text-amber-400',
    high:     'bg-red-500/15 text-red-400',
    critical: 'bg-red-600/30 text-red-300 font-bold',
  };
  return (
    <span className={cn('text-[10px] font-mono uppercase px-2 py-0.5 rounded', styles[urgency] ?? styles.medium)}>
      {urgency}
    </span>
  );
}

function TabExplainer({ icon: Icon, title, detail }: {
  icon: React.ElementType; title: string; detail: string;
}) {
  return (
    <div className="flex items-start gap-3 px-4 py-3 rounded-lg bg-muted/30 border border-border mb-5 text-[12.5px]">
      <Icon className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
      <div>
        <span className="font-semibold">{title}. </span>
        <span className="text-muted-foreground">{detail}</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Campaign detail panel — inline expansion inside Promote accordion
// ─────────────────────────────────────────────────────────────────────────────

function CampaignPanel({ creative, item, onRegenerate, isPending }: {
  creative: CampaignCreative;
  item: PromoteItem;
  onRegenerate: () => void;
  isPending: boolean;
}) {
  const [imgError, setImgError] = useState(false);

  return (
    <div className="bg-muted/10 border-t border-border px-5 py-5 space-y-5">
      {/* Top row: image + headline + controls */}
      <div className="flex items-start gap-5">
        {creative.image_url && !imgError ? (
          <img
            src={creative.image_url}
            alt={item.product_name}
            className="w-40 h-40 object-cover rounded-xl shrink-0 border border-border shadow-md"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="w-40 h-40 rounded-xl shrink-0 border border-dashed border-border bg-muted/30 flex items-center justify-center text-[10px] text-muted-foreground font-mono">
            {imgError ? 'image unavailable' : 'no image'}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-4 mb-3">
            <div>
              <div className="text-[15px] font-semibold leading-tight">{creative.headline}</div>
              <div className="text-[12px] text-muted-foreground mt-0.5">{creative.subheadline}</div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {creative.tone_used && <ToneBadge tone={creative.tone_used} />}
              {creative.fallback_used && (
                <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  fallback
                </span>
              )}
              <button
                onClick={onRegenerate}
                disabled={isPending}
                className="text-[11px] text-muted-foreground hover:text-primary inline-flex items-center gap-1 disabled:opacity-50 transition"
              >
                <RefreshCw className="h-3 w-3" />Regenerate
              </button>
            </div>
          </div>

          {/* Social publish status chips */}
          {(creative.social_posts?.length ?? 0) > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] text-muted-foreground font-mono uppercase tracking-wider">Channels:</span>
              {creative.social_posts!.map(sp => {
                const icons: Record<string, string> = { facebook: '👥', instagram: '📸', telegram: '✈️', tiktok: '🎵' };
                const icon = icons[sp.platform.toLowerCase()] ?? '🔗';
                if (sp.success && sp.post_url) {
                  return (
                    <a key={sp.platform} href={sp.post_url} target="_blank" rel="noreferrer"
                      className="h-7 px-3 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20 text-[11px] font-medium inline-flex items-center gap-1 transition">
                      {icon} {sp.platform} <ExternalLink className="h-2.5 w-2.5 ml-0.5" />
                    </a>
                  );
                }
                return (
                  <span key={sp.platform} title={sp.error ?? 'publish failed'}
                    className="h-7 px-3 rounded-full bg-red-500/10 border border-red-500/20 text-red-400/70 text-[11px] inline-flex items-center gap-1 cursor-default max-w-[220px]">
                    {icon} {sp.platform} ✗
                    {sp.error && (
                      <span className="truncate text-[9px] text-red-400/50 ml-1 hidden sm:inline">
                        — {sp.error.replace(/^[A-Za-z0-9_]+Error:\s*/i, '').slice(0, 60)}
                      </span>
                    )}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Copy grid: Instagram · Facebook · Telegram */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-2">
        {[
          { l: 'Instagram', v: creative.instagram_post,    emoji: '📸' },
          { l: 'Facebook',  v: creative.facebook_post,     emoji: '👥' },
          { l: 'Telegram',  v: creative.telegram_broadcast, emoji: '✈️' },
        ].filter(c => c.v).map(c => (
          <div key={c.l} className="rounded-lg bg-card border border-border/60 p-3">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[10px] font-mono uppercase text-muted-foreground">{c.emoji} {c.l}</span>
              <button
                onClick={() => { navigator.clipboard.writeText(c.v); toast.success(`${c.l} copied`); }}
                className="text-[10px] inline-flex items-center gap-0.5 text-primary hover:text-primary/70 transition"
              >
                <Copy className="h-2.5 w-2.5" />Copy
              </button>
            </div>
            <p className="text-[11.5px] leading-relaxed line-clamp-4">{c.v}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Promote accordion row
// ─────────────────────────────────────────────────────────────────────────────

function PromoteRow({ item, index }: { item: PromoteItem; index: number }) {
  const { campaignCache, setCampaign, mode } = useSettings();
  const tenantScope = useTenantScopeKey();
  const campaignKey = scopedSkuKey(item.sku_id, tenantScope);
  const [creative, setCreative] = useState<CampaignCreative | null>(
    campaignCache[campaignKey] ?? item.creative ?? null,
  );
  const [expanded, setExpanded] = useState(false);

  void mode;

  useEffect(() => {
    setCreative(campaignCache[campaignKey] ?? item.creative ?? null);
  }, [campaignCache, campaignKey, item.creative]);

  const mutation = useMutation({
    mutationFn: () => generateAndPublishCampaign(item.sku_id, item.product_name, {
      recommendation: 'PROMOTE', confidence: 0.9, explanation: item.reason,
      shap_top5: [], fallback_used: false, model_version: 'ie3',
      processing_time_ms: 0, requires_human_approval: false,
    }),
    onSuccess: async (data) => {
      setCreative(data);
      setCampaign(item.sku_id, data);
      try {
        await persistCampaign({
          channel: 'multi-channel',
          headline: data.headline || item.product_name,
          body: data.ad_copy_long || data.ad_copy_short || data.instagram_post || data.facebook_post || '',
          tone: data.tone_used,
          generation_confidence: data.generation_confidence,
          fallback_used: data.fallback_used,
        });
      } catch {
        // Campaign analytics persistence should not block the retailer action.
      }
      await recordDecision(item.sku_id, 'promote', `Campaign generated — ${item.product_name}`);
      const failed = (data.social_posts ?? []).filter(p => !p.success);
      if (failed.length) {
        toast.warning(`Draft ready; publish failed for ${failed.map(p => p.platform).join(', ')}`);
      } else {
        toast.success(`Campaign live for ${item.product_name}`);
      }
    },
    onError: (err: Error) => toast.error(`Failed: ${err.message}`),
  });

  const hasCreative = !!creative;
  const isPosted = hasCreative && (creative!.social_posts?.some(p => p.success) ?? false);

  return (
    <div className={cn('border-b border-border last:border-0 transition-colors', expanded && 'bg-card/60')}>
      <div className="flex items-center gap-3 px-4 py-3 hover:bg-accent/20 transition min-w-0">
        <span className="text-[10px] font-mono text-muted-foreground/40 w-5 shrink-0 text-right">{index + 1}</span>
        <div className={cn('h-2 w-2 rounded-full shrink-0',
          isPosted ? 'bg-emerald-500 ring-2 ring-emerald-500/20'
          : hasCreative ? 'bg-blue-400/70'
          : 'bg-muted-foreground/20',
        )} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-medium text-[13px] truncate">{item.product_name}</span>
            <span className="text-[10px] font-mono text-muted-foreground shrink-0 hidden sm:inline">{item.brand}</span>
            <span className="text-[10px] font-mono text-muted-foreground/40 shrink-0 hidden md:inline">{item.sku_id}</span>
          </div>
          <p className="text-[11px] text-muted-foreground truncate mt-0.5">{item.reason}</p>
        </div>
        <div className="text-emerald-400 font-bold text-[12.5px] tabular-nums shrink-0 inline-flex items-center gap-0.5">
          <TrendingUp className="h-3 w-3" />+{item.expected_lift_pct}%
        </div>
        <div className="hidden lg:flex gap-1 shrink-0">
          {item.channels.map(ch => (
            <span key={ch} className="text-[9px] bg-secondary/60 text-secondary-foreground px-1.5 py-0.5 rounded-full capitalize">{ch}</span>
          ))}
        </div>
        {hasCreative ? (
          <button
            onClick={() => setExpanded(e => !e)}
            className="h-7 px-3 rounded-md bg-secondary hover:bg-secondary/80 text-[11px] font-medium inline-flex items-center gap-1 shrink-0 transition"
          >
            {isPosted
              ? <span className="text-emerald-400 inline-flex items-center gap-1"><CheckCircle2 className="h-3 w-3" />Live</span>
              : 'Campaign'
            }
            {expanded ? <ChevronUp className="h-3 w-3 ml-0.5" /> : <ChevronDown className="h-3 w-3 ml-0.5" />}
          </button>
        ) : (
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="h-7 px-3 rounded-md bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white text-[11px] font-semibold inline-flex items-center gap-1.5 shrink-0 transition"
          >
            {mutation.isPending
              ? <><Loader2 className="h-3 w-3 animate-spin" />Generating…</>
              : <><Sparkles className="h-3 w-3" />Generate</>
            }
          </button>
        )}
      </div>
      {mutation.isPending && (
        <div className="px-12 py-2.5 bg-emerald-500/5 border-t border-border flex items-center gap-2.5 text-[11px] text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin text-emerald-500" />
          <span className="animate-pulse">Writing copy and trying social publishing...</span>
        </div>
      )}
      {isPosted && creative && !expanded && (
        <div className="px-12 py-2 border-t border-border bg-emerald-500/5 flex items-center gap-3">
          {creative.image_url && (
            <img
              src={creative.image_url}
              alt=""
              className="h-8 w-8 rounded-md object-cover shrink-0 border border-border"
              onError={(e) => { e.currentTarget.style.display = 'none'; }}
            />
          )}
          <span className="text-[11px] text-emerald-400 inline-flex items-center gap-1 font-medium">
            <CheckCircle2 className="h-3 w-3" />Posted live
          </span>
          {creative.social_posts?.filter(p => p.success && p.post_url).map(sp => {
            const platform = sp.platform.toLowerCase();
            if (platform !== 'facebook' && platform !== 'instagram') return null;
            return (
              <a
                key={sp.platform}
                href={sp.post_url!}
                target="_blank"
                rel="noreferrer"
                title={`Open on ${sp.platform}`}
                className="h-6 w-6 rounded-full flex items-center justify-center transition hover:opacity-80 shrink-0"
                style={platform === 'instagram'
                  ? { background: 'linear-gradient(45deg, #f09433, #e6683c, #dc2743, #cc2366, #bc1888)' }
                  : { background: '#1877f2' }}
              >
                {platform === 'facebook'
                  ? <FacebookIcon className="h-3.5 w-3.5 text-white" />
                  : <InstagramIcon className="h-3.5 w-3.5 text-white" />
                }
              </a>
            );
          })}
        </div>
      )}
      {expanded && creative && (
        <CampaignPanel creative={creative} item={item} onRegenerate={() => mutation.mutate()} isPending={mutation.isPending} />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Markdown interactive row
// ─────────────────────────────────────────────────────────────────────────────

function MarkdownRow({ item, onActioned }: { item: MarkdownItem; onActioned?: () => void }) {
  const [customPct, setCustomPct] = useState(item.suggested_discount_pct);
  const [applied, setApplied] = useState(false);
  const newPrice = Number((item.current_price_usd * (1 - customPct / 100)).toFixed(2));
  const isDirty = customPct !== item.suggested_discount_pct;

  const mutation = useMutation({
    mutationFn: () => patchInventoryPrice(item.sku_id, newPrice, 'markdown',
      `Markdown ${customPct}% applied — ${item.product_name}`),
    onSuccess: ({ db_connected }) => {
      setApplied(true);
      onActioned?.();
      if (db_connected) {
        toast.success(`Markdown saved — ${item.product_name} → ${fmtUSD(newPrice, { decimals: 2 })}`);
      } else {
        toast.warning(`Markdown applied locally — SKU not synced to DB yet`);
      }
    },
    onError: (err: Error) => toast.error(`Failed to save: ${err.message}`),
  });

  return (
    <tr className={cn('border-t border-border hover:bg-accent/20 transition', applied && 'opacity-55')}>
      <td className="px-4 py-3">
        <div className="font-medium text-[13px]">{item.product_name}</div>
        <div className="text-[10.5px] font-mono text-muted-foreground mt-0.5">{item.sku_id} · {item.brand}</div>
      </td>
      <td className="px-4 py-3 text-right font-mono text-[12.5px]">{fmtUSD(item.current_price_usd, { decimals: 2 })}</td>
      <td className="px-4 py-3">
        <div className="flex items-center justify-end gap-1">
          <span className="text-[11px] text-muted-foreground">−</span>
          <input type="number" min={1} max={80} value={customPct}
            onChange={e => setCustomPct(Math.min(80, Math.max(1, Number(e.target.value))))}
            disabled={applied || mutation.isPending}
            className={cn(
              'w-14 h-7 rounded border bg-background text-center text-[12px] font-mono px-1 focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50 transition',
              isDirty && !applied ? 'border-amber-400/70 ring-1 ring-amber-400/30' : 'border-border',
            )}
          />
          <span className="text-[11px] text-muted-foreground">%</span>
          {isDirty && !applied && (
            <span className="text-[9px] font-mono uppercase text-amber-400 ml-0.5">modified</span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-right font-mono text-[12.5px] text-decision-markdown font-semibold">{fmtUSD(newPrice, { decimals: 2 })}</td>
      <td className={cn('px-4 py-3 text-right font-mono text-[12.5px]', item.margin_after_pct < 30 ? 'text-decision-clear' : 'text-muted-foreground')}>
        {fmtPct(item.margin_after_pct, 0)}
      </td>
      <td className="px-4 py-3 text-[11.5px] text-muted-foreground max-w-[180px]">{item.reason}</td>
      <td className="px-4 py-3"><UrgencyPill urgency={item.urgency} /></td>
      <td className="px-4 py-3">
        {applied
          ? <span className="text-[11px] text-emerald-400 inline-flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" />Applied</span>
          : <button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
              className="h-7 px-3 rounded-md bg-decision-markdown/10 hover:bg-decision-markdown/20 border border-decision-markdown/30 text-decision-markdown text-[11px] font-medium transition whitespace-nowrap disabled:opacity-60 inline-flex items-center gap-1"
            >
              {mutation.isPending
                ? <><Loader2 className="h-3 w-3 animate-spin" />Saving…</>
                : isDirty ? `Apply at ${fmtUSD(newPrice, { decimals: 2 })}` : 'Apply Markdown'
              }
            </button>
        }
      </td>
    </tr>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Clearance card with confirm action
// ─────────────────────────────────────────────────────────────────────────────

function ClearanceCard({ item, onActioned }: { item: ClearanceItem; onActioned?: () => void }) {
  const [confirmed, setConfirmed] = useState(false);
  const [customPrice, setCustomPrice] = useState(item.suggested_price_usd.toFixed(2));
  const parsedPrice = Number(Number(customPrice).toFixed(2));
  const isDirty = Math.abs(parsedPrice - item.suggested_price_usd) > 0.001;
  const isValidPrice = parsedPrice > 0 && !isNaN(parsedPrice);
  const liveRecover = isValidPrice ? Number((parsedPrice * item.current_stock).toFixed(2)) : item.recovered_cash_usd;

  const mutation = useMutation({
    mutationFn: () => patchInventoryPrice(
      item.sku_id,
      parsedPrice,
      'clearance',
      `Clearance confirmed at ${fmtUSD(parsedPrice, { decimals: 2 })} — ${item.product_name}`,
    ),
    onSuccess: ({ db_connected }) => {
      setConfirmed(true);
      onActioned?.();
      if (db_connected) {
        toast.success(`Clearance saved — ${item.product_name} at ${fmtUSD(parsedPrice, { decimals: 2 })}`);
      } else {
        toast.warning(`Clearance applied locally — SKU not synced to DB yet`);
      }
    },
    onError: (err: Error) => toast.error(`Failed to save: ${err.message}`),
  });

  return (
    <div className={cn('rounded-xl border bg-card p-5 transition',
      item.urgency === 'critical' ? 'border-red-500/40' : 'border-decision-clear/30',
      confirmed && 'opacity-55',
    )}>
      <div className="flex items-start justify-between mb-3">
        <DecisionBadge decision="CLEAR" size="lg" />
        <UrgencyPill urgency={item.urgency} />
      </div>
      <div className="text-[15px] font-semibold">{item.product_name}</div>
      <div className="text-[11px] font-mono text-muted-foreground mt-0.5 mb-4">{item.sku_id} · {item.brand}</div>
      <div className="grid grid-cols-3 gap-3 mb-4">
        {[
          { label: 'Stock left',   value: String(item.current_stock), unit: 'units' },
          { label: 'Age',          value: String(item.age_days),       unit: 'days' },
          { label: 'Recover',      value: fmtUSD(liveRecover, { decimals: 2 }), unit: 'if cleared', highlight: true },
        ].map(({ label, value, unit, highlight }) => (
          <div key={label}>
            <div className="text-[9.5px] uppercase font-mono text-muted-foreground mb-0.5">{label}</div>
            <div className={cn('text-[18px] font-bold tabular-nums', highlight && 'text-emerald-400')}>{value}</div>
            <div className="text-[10px] text-muted-foreground">{unit}</div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="text-[11.5px] text-muted-foreground">Clearance price:</span>
        <div className={cn(
          'flex items-center rounded-md overflow-hidden bg-background border transition',
          confirmed ? 'opacity-50' : isDirty ? 'border-amber-400/70 ring-1 ring-amber-400/30' : 'border-border',
        )}>
          <span className="text-[11px] px-2 text-muted-foreground bg-muted/40">$</span>
          <input
            type="number" min={0.01} step={0.01} value={customPrice}
            onChange={e => setCustomPrice(e.target.value)}
            disabled={confirmed || mutation.isPending}
            className="w-20 h-7 text-[12px] font-mono px-1 bg-background focus:outline-none disabled:opacity-50"
          />
        </div>
        {isDirty && !confirmed
          ? <span className="text-[10px] font-mono text-amber-400">modified · was {fmtUSD(item.suggested_price_usd, { decimals: 2 })}</span>
          : <span className="text-[10.5px] text-muted-foreground">AI suggested {fmtUSD(item.suggested_price_usd, { decimals: 2 })}</span>
        }
      </div>
      {confirmed
        ? <div className="h-8 flex items-center gap-1.5 text-[12px] text-emerald-400">
            <CheckCircle2 className="h-4 w-4" />Clearance confirmed at {fmtUSD(parsedPrice, { decimals: 2 })}
          </div>
        : <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !isValidPrice}
            className="h-8 px-4 rounded-md bg-decision-clear/10 hover:bg-decision-clear/20 border border-decision-clear/40 text-decision-clear text-[12px] font-medium transition disabled:opacity-60 inline-flex items-center gap-1.5"
          >
            {mutation.isPending
              ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Saving…</>
              : isDirty
                ? `Confirm at ${fmtUSD(parsedPrice, { decimals: 2 })}`
                : 'Confirm Clearance Price'
            }
          </button>
      }
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Hold Pricing row with acknowledge
// ─────────────────────────────────────────────────────────────────────────────

function HoldRow({ item, onActioned }: { item: HoldPricingItem; onActioned?: () => void }) {
  const [acked, setAcked] = useState(false);

  const mutation = useMutation({
    mutationFn: () => recordDecision(item.sku_id, 'hold',
      `Hold pricing reviewed — ${item.product_name} (margin ${fmtPct(item.margin_pct, 1)}, velocity ${item.velocity}/d)`),
    onSuccess: ({ db_connected }) => {
      setAcked(true);
      onActioned?.();
      if (db_connected) {
        toast.success(`${item.product_name} — hold acknowledged & logged`);
      } else {
        toast.warning(`${item.product_name} — acknowledged locally (SKU not in DB)`);
      }
    },
    onError: (err: Error) => toast.error(`Failed: ${err.message}`),
  });

  return (
    <tr className={cn('border-t border-border hover:bg-accent/20 transition', acked && 'opacity-55')}>
      <td className="px-4 py-3">
        <div className="font-medium text-[13px]">{item.product_name}</div>
        <div className="text-[10.5px] font-mono text-muted-foreground mt-0.5">{item.sku_id} · {item.brand}</div>
      </td>
      <td className="px-4 py-3 text-[12px] text-muted-foreground max-w-[220px]">{item.reason}</td>
      <td className="px-4 py-3 text-right font-mono text-decision-promote text-[12.5px] font-semibold">{fmtPct(item.margin_pct, 1)}</td>
      <td className="px-4 py-3 text-right font-mono text-[12.5px]">{item.velocity}/d</td>
      <td className="px-4 py-3 text-right">
        {acked
          ? <span className="text-[11px] text-emerald-400 inline-flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" />Reviewed</span>
          : <button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
              className="h-7 px-3 rounded-md bg-secondary hover:bg-secondary/80 text-[11px] font-medium transition disabled:opacity-60 inline-flex items-center gap-1"
            >
              {mutation.isPending
                ? <><Loader2 className="h-3 w-3 animate-spin" />Logging…</>
                : 'Acknowledge'
              }
            </button>
        }
      </td>
    </tr>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

export default function Promotions() {
  const { data: r, isLoading, isError, error, refetch } = useLiveReport();
  const [handledSkus, setHandledSkus] = useState({
    markdown: [] as string[],
    clearance: [] as string[],
    hold: [] as string[],
  });
  const markHandled = (key: keyof typeof handledSkus, skuId: string) => {
    setHandledSkus(current => (
      current[key].includes(skuId)
        ? current
        : { ...current, [key]: [...current[key], skuId] }
    ));
  };

  if (isLoading) return (<><TopBar title="Promotions & Campaigns" /><PageSkeleton /></>);

  if (isError || !r) return (
    <>
      <TopBar title="Promotions & Campaigns" />
      <div className="flex flex-col items-center justify-center flex-1 gap-4 p-8 text-center">
        <div className="h-12 w-12 rounded-full bg-destructive/10 flex items-center justify-center">
          <span className="text-destructive text-xl">!</span>
        </div>
        <div>
          <p className="font-semibold text-[15px] mb-1">Unable to load promotions data</p>
          <p className="text-[13px] text-muted-foreground max-w-sm">
            {error instanceof Error ? error.message : 'The analytics engine could not be reached. Make sure the backend is running on port 8000.'}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="h-9 px-4 rounded-md bg-primary text-primary-foreground text-[13px] font-semibold hover:opacity-90 transition"
        >
          Retry
        </button>
      </div>
    </>
  );

  const p = r.promotions;
  const visiblePromote = p.promote;
  const visibleMarkdown = p.markdown.filter(item => !handledSkus.markdown.includes(item.sku_id));
  const visibleClearance = p.clearance.filter(item => !handledSkus.clearance.includes(item.sku_id));
  const visibleHold = p.hold_pricing.filter(item => !handledSkus.hold.includes(item.sku_id));

  return (
    <>
      <TopBar
        title="Promotions & Campaigns"
        subtitle={`${visiblePromote.length} promote · ${visibleMarkdown.length} markdown · ${visibleClearance.length} clearance · ${visibleHold.length} hold`}
      />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <Tabs defaultValue="promote">
          <TabsList className="bg-surface-raised border border-border">
            <TabsTrigger value="promote">Promote ({visiblePromote.length})</TabsTrigger>
            <TabsTrigger value="markdown">Markdown ({visibleMarkdown.length})</TabsTrigger>
            <TabsTrigger value="clearance">Clearance ({visibleClearance.length})</TabsTrigger>
            <TabsTrigger value="hold">Hold Pricing ({visibleHold.length})</TabsTrigger>
          </TabsList>

          {/* PROMOTE */}
          <TabsContent value="promote" className="mt-5">
            <TabExplainer
              icon={Sparkles}
              title="AI-suggested promotions based on live inventory signals"
              detail="Items with healthy margins, strong velocity, and below-market pricing. All suggestions come from your inventory data — days of supply, sell-through rate, price gap vs. competitors. Click Generate & Post to write copy, create a product image, and publish to Instagram & Facebook in one step."
            />
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3 text-[12px] text-muted-foreground">
                <span>{visiblePromote.length} promotion opportunities ready</span>
              </div>
            </div>
            <div className="rounded-xl border border-border bg-card overflow-hidden">
              <div className="grid items-center gap-3 px-4 py-2 bg-muted/30 border-b border-border text-[10px] uppercase tracking-wider font-mono text-muted-foreground"
                style={{ gridTemplateColumns: '1.5rem 0.5rem 1fr 4.5rem auto 7rem' }}>
                <span>#</span><span /><span>Product · Brand · Inventory reason</span>
                <span className="text-right">Lift</span>
                <span className="hidden lg:block">Channels</span>
                <span className="text-right">Action</span>
              </div>
              {visiblePromote.map((item, i) => (
                <PromoteRow key={item.sku_id} item={item} index={i} />
              ))}
            </div>
          </TabsContent>

          {/* MARKDOWN */}
          <TabsContent value="markdown" className="mt-5">
            <TabExplainer
              icon={Tag}
              title="Inventory-driven price markdown queue"
              detail="Items with slow sell-through, excess stock, or too many days of supply where a discount will accelerate movement and free up cash. Adjust the % if needed — the margin impact updates live — then click Apply Markdown."
            />
            <div className="rounded-xl border border-border bg-card overflow-hidden">
              <table className="w-full text-[13px]">
                <thead className="bg-surface-sunken text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left">Product</th>
                    <th className="px-4 py-3 text-right">Current</th>
                    <th className="px-4 py-3 text-right">Discount</th>
                    <th className="px-4 py-3 text-right">New Price</th>
                    <th className="px-4 py-3 text-right">Margin After</th>
                    <th className="px-4 py-3 text-left">Inventory Signal</th>
                    <th className="px-4 py-3 text-center">Urgency</th>
                    <th className="px-4 py-3 text-right">Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleMarkdown.map(m => <MarkdownRow key={m.sku_id} item={m} onActioned={() => markHandled('markdown', m.sku_id)} />)}
                </tbody>
              </table>
            </div>
          </TabsContent>

          {/* CLEARANCE */}
          <TabsContent value="clearance" className="mt-5">
            <TabExplainer
              icon={Package}
              title="Dead or ageing stock that needs to leave the floor"
              detail="Items sitting far beyond their expected days of supply with very low velocity. Clearing them now recovers cash and shelf space before they become a write-off. Override the AI-suggested price if needed, then confirm."
            />
            <div className="grid md:grid-cols-2 gap-4">
              {visibleClearance.map(c => <ClearanceCard key={c.sku_id} item={c} onActioned={() => markHandled('clearance', c.sku_id)} />)}
            </div>
          </TabsContent>

          {/* HOLD PRICING */}
          <TabsContent value="hold" className="mt-5">
            <TabExplainer
              icon={PauseCircle}
              title="Items performing well — no price change needed"
              detail="These SKUs have healthy margins and strong sell-through at current prices. The inventory engine advises against discounts or promotions. Review and acknowledge to keep your pricing queue clean and up to date."
            />
            <div className="rounded-xl border border-border bg-card overflow-hidden">
              <table className="w-full text-[13px]">
                <thead className="bg-surface-sunken text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left">Product</th>
                    <th className="px-4 py-3 text-left">Inventory Signal</th>
                    <th className="px-4 py-3 text-right">Margin</th>
                    <th className="px-4 py-3 text-right">Velocity</th>
                    <th className="px-4 py-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleHold.map(h => <HoldRow key={h.sku_id} item={h} onActioned={() => markHandled('hold', h.sku_id)} />)}
                </tbody>
              </table>
            </div>
          </TabsContent>

        </Tabs>
      </main>
    </>
  );
}
