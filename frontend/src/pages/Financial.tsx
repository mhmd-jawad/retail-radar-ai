import { useState } from 'react';
import { useQueryClient, useMutation, useQuery } from '@tanstack/react-query';
import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { KpiCard } from '@/components/shared/KpiCard';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtPct, fmtUSD, fmtNum, relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import {
  TrendingUp, DollarSign, Boxes, AlertTriangle, Bot, ShieldAlert,
  BarChart2, ArrowRight, Settings, Save, Plus, Pencil, Trash2, X, Check, Info,
  CheckCircle2, XCircle,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  RadarChart, PolarGrid, PolarAngleAxis, Radar,
  ResponsiveContainer, BarChart, Bar, Cell, LabelList, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine,
} from 'recharts';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { useAuth } from '@/store/auth';
import {
  fetchFinancialProfile, updateFinancialProfile,
  fetchFinancialLineItems, createFinancialLineItem, updateFinancialLineItem, deleteFinancialLineItem,
} from '@/lib/adapter';
import type { FinancialProfileInput, FinancialLineItem } from '@/types/domain';

const MARGIN_HEALTHY = 45;
const MARGIN_FLOOR = 35;
const FINANCIAL_PROMPT = "Give me a financial health summary for my store — focus on margin, cash runway, and any risks I should know about.";

// ── Form helpers ──────────────────────────────────────────────────────────────

function decimalText(v: string) {
  return v.replace(/[^0-9.]/g, '').replace(/(\..*)\./g, '$1');
}

type ProfileFormState = {
  total_assets_usd: string;
  total_liabilities_usd: string;
  monthly_fixed_opex_usd: string;
  annual_revenue_projected_usd: string;
  cash_runway_months: string;
  breakeven_monthly_revenue_usd: string;
};

function toForm(p: Partial<FinancialProfileInput>): ProfileFormState {
  return {
    total_assets_usd: p.total_assets_usd != null ? String(p.total_assets_usd) : '',
    total_liabilities_usd: p.total_liabilities_usd != null ? String(p.total_liabilities_usd) : '',
    monthly_fixed_opex_usd: p.monthly_fixed_opex_usd != null ? String(p.monthly_fixed_opex_usd) : '',
    annual_revenue_projected_usd: p.annual_revenue_projected_usd != null ? String(p.annual_revenue_projected_usd) : '',
    cash_runway_months: p.cash_runway_months != null ? String(p.cash_runway_months) : '',
    breakeven_monthly_revenue_usd: p.breakeven_monthly_revenue_usd != null ? String(p.breakeven_monthly_revenue_usd) : '',
  };
}

function parseForm(f: ProfileFormState): FinancialProfileInput {
  const n = (s: string) => (s.trim() === '' ? null : parseFloat(s));
  return {
    total_assets_usd: n(f.total_assets_usd),
    total_liabilities_usd: n(f.total_liabilities_usd),
    monthly_fixed_opex_usd: n(f.monthly_fixed_opex_usd),
    annual_revenue_projected_usd: n(f.annual_revenue_projected_usd),
    cash_runway_months: n(f.cash_runway_months),
    breakeven_monthly_revenue_usd: n(f.breakeven_monthly_revenue_usd),
  };
}

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn('space-y-1.5', className)}>
      <span className="text-[11px] uppercase tracking-wider text-muted-foreground font-mono">{label}</span>
      {children}
    </label>
  );
}

// ── Balance sheet line item row ───────────────────────────────────────────────

function LineItemRow({
  item,
  onSave,
  onDelete,
  isSaving,
  isDeleting,
}: {
  item: FinancialLineItem;
  onSave: (id: string, label: string, amount_usd: number) => void;
  onDelete: (id: string) => void;
  isSaving: boolean;
  isDeleting: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(item.label);
  const [amount, setAmount] = useState(String(item.amount_usd));

  function startEdit() {
    setLabel(item.label);
    setAmount(String(item.amount_usd));
    setEditing(true);
  }

  function handleSave() {
    const parsed = parseFloat(amount);
    if (!label.trim() || isNaN(parsed)) return;
    onSave(item.id, label.trim(), parsed);
    setEditing(false);
  }

  function handleCancel() {
    setLabel(item.label);
    setAmount(String(item.amount_usd));
    setEditing(false);
  }

  if (editing) {
    return (
      <div className="flex items-center gap-2 py-1.5">
        <Input
          className="h-7 text-[12px] flex-1"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Label"
          autoFocus
        />
        <Input
          className="h-7 text-[12px] w-28 text-right font-mono"
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(decimalText(e.target.value))}
          placeholder="0"
        />
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="h-7 w-7 rounded flex items-center justify-center text-decision-promote hover:bg-accent/50 shrink-0"
          title="Save"
        >
          <Check className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={handleCancel}
          className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:bg-accent/50 shrink-0"
          title="Cancel"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="group flex items-center gap-2 py-1.5 hover:bg-accent/20 rounded-md px-1 -mx-1">
      <span className="flex-1 text-[13px] text-foreground truncate">{item.label}</span>
      <span className="text-[13px] font-mono font-semibold text-foreground shrink-0">
        {fmtUSD(item.amount_usd, { compact: true })}
      </span>
      <button
        onClick={startEdit}
        className="h-6 w-6 rounded flex items-center justify-center text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition shrink-0"
        title="Edit"
      >
        <Pencil className="h-3 w-3" />
      </button>
      <button
        onClick={() => onDelete(item.id)}
        disabled={isDeleting}
        className="h-6 w-6 rounded flex items-center justify-center text-muted-foreground hover:text-decision-clear opacity-0 group-hover:opacity-100 transition shrink-0"
        title="Delete"
      >
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  );
}

// ── Add-item row ─────────────────────────────────────────────────────────────

function AddItemRow({
  itemType,
  onAdd,
  onCancel,
  isSaving,
}: {
  itemType: 'asset' | 'liability';
  onAdd: (label: string, amount_usd: number) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const [label, setLabel] = useState('');
  const [amount, setAmount] = useState('');

  function handleAdd() {
    const parsed = parseFloat(amount);
    if (!label.trim() || isNaN(parsed)) return;
    onAdd(label.trim(), parsed);
    setLabel('');
    setAmount('');
  }

  return (
    <div className="flex items-center gap-2 py-1.5 mt-1 border-t border-dashed border-border">
      <Input
        className="h-7 text-[12px] flex-1"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder={`e.g. ${itemType === 'asset' ? 'Cash on hand' : 'Supplier payables'}`}
        autoFocus
        onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); if (e.key === 'Escape') onCancel(); }}
      />
      <Input
        className="h-7 text-[12px] w-28 text-right font-mono"
        inputMode="decimal"
        value={amount}
        onChange={(e) => setAmount(decimalText(e.target.value))}
        placeholder="USD"
        onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); if (e.key === 'Escape') onCancel(); }}
      />
      <button
        onClick={handleAdd}
        disabled={isSaving || !label.trim() || !amount.trim()}
        className="h-7 w-7 rounded flex items-center justify-center text-decision-promote hover:bg-accent/50 disabled:opacity-40 shrink-0"
        title="Add"
      >
        <Check className="h-3.5 w-3.5" />
      </button>
      <button
        onClick={onCancel}
        className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:bg-accent/50 shrink-0"
        title="Cancel"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Financial() {
  const { data: report, isLoading } = useReport();
  const token = useAuth((s) => s.token);
  const queryClient = useQueryClient();

  const [profileOpen, setProfileOpen] = useState(false);
  const [form, setForm] = useState<ProfileFormState>(toForm({}));
  const [addingType, setAddingType] = useState<'asset' | 'liability' | null>(null);

  // Financial profile from DB (user-entered aggregates)
  const { data: storedProfile } = useQuery({
    queryKey: ['financial-profile'],
    queryFn: fetchFinancialProfile,
    enabled: !!token,
    staleTime: 60_000,
  });

  // Financial line items (itemized assets/liabilities)
  const { data: lineItems = [] } = useQuery({
    queryKey: ['financial-items'],
    queryFn: fetchFinancialLineItems,
    enabled: !!token,
    staleTime: 30_000,
  });

  const assets = lineItems.filter((i) => i.item_type === 'asset');
  const liabilities = lineItems.filter((i) => i.item_type === 'liability');

  const saveMutation = useMutation({
    mutationFn: (payload: FinancialProfileInput) => updateFinancialProfile(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['financial-profile'] });
      toast.success('Financial profile updated');
      setProfileOpen(false);
    },
    onError: (err: Error) => toast.error('Save failed', { description: err.message }),
  });

  const createItemMutation = useMutation({
    mutationFn: (p: { label: string; amount_usd: number; item_type: 'asset' | 'liability' }) =>
      createFinancialLineItem({ label: p.label, amount_usd: p.amount_usd, item_type: p.item_type }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['financial-items'] });
      setAddingType(null);
    },
    onError: (err: Error) => toast.error('Failed to add item', { description: err.message }),
  });

  const updateItemMutation = useMutation({
    mutationFn: (p: { id: string; label: string; amount_usd: number; item_type: 'asset' | 'liability' }) =>
      updateFinancialLineItem(p.id, { label: p.label, amount_usd: p.amount_usd, item_type: p.item_type }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['financial-items'] }),
    onError: (err: Error) => toast.error('Failed to update item', { description: err.message }),
  });

  const deleteItemMutation = useMutation({
    mutationFn: (id: string) => deleteFinancialLineItem(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['financial-items'] }),
    onError: (err: Error) => toast.error('Failed to delete item', { description: err.message }),
  });

  function openDialog() {
    setForm(toForm(storedProfile ?? {}));
    setProfileOpen(true);
  }

  function handleSave() {
    saveMutation.mutate(parseForm(form));
  }

  const update = (key: keyof ProfileFormState, value: string) => setForm((f) => ({ ...f, [key]: value }));

  if (isLoading || !report) {
    return (
      <>
        <TopBar title="Financial Health" subtitle="Loading…" />
        <PageSkeleton />
      </>
    );
  }

  const { inventory, metadata } = report;
  const m = inventory.metrics;

  // Prefer stored profile values where available
  const cashRunway = storedProfile?.cash_runway_months ?? null;
  const storedAssets = storedProfile?.total_assets_usd ?? null;
  const storedLiabilities = storedProfile?.total_liabilities_usd ?? null;
  const monthlyOpex = storedProfile?.monthly_fixed_opex_usd ?? null;
  const annualRevenue = storedProfile?.annual_revenue_projected_usd ?? null;
  const currentRatio = (storedProfile as { current_ratio?: number | null } | undefined)?.current_ratio ?? null;
  const equity = (storedProfile as { total_equity_usd?: number | null } | undefined)?.total_equity_usd ?? null;

  // Balance sheet totals: live inventory + user items
  const inventoryCostUSD = m.inventory_value_at_cost_usd;
  const userAssetTotal = assets.reduce((s, i) => s + i.amount_usd, 0);
  const userLiabilityTotal = liabilities.reduce((s, i) => s + i.amount_usd, 0);
  const computedTotalAssets = inventoryCostUSD + userAssetTotal;
  const computedTotalEquity = computedTotalAssets - userLiabilityTotal;
  const computedCurrentRatio = userLiabilityTotal > 0 ? computedTotalAssets / userLiabilityTotal : null;

  // Use computed values if user has added items, else fall back to stored profile
  const displayAssets = assets.length > 0 ? computedTotalAssets : (storedAssets ?? inventoryCostUSD);
  const displayLiabilities = liabilities.length > 0 ? userLiabilityTotal : (storedLiabilities ?? 0);
  const displayEquity = displayAssets - displayLiabilities;
  const displayCurrentRatio = liabilities.length > 0 ? computedCurrentRatio : currentRatio;

  const blendedMargin = m.blended_margin_pct;
  const marginHealth =
    blendedMargin >= MARGIN_HEALTHY ? 'healthy' : blendedMargin >= MARGIN_FLOOR ? 'warning' : 'critical';

  const grossProfit = m.inventory_value_at_retail_usd - m.inventory_value_at_cost_usd;
  const deadStockValue = m.inventory_value_at_cost_usd * (m.dead_stock_skus / Math.max(m.total_skus, 1));
  const capitalUtilisation = m.total_skus > 0
    ? Math.round(((m.total_skus - m.dead_stock_skus) / m.total_skus) * 100)
    : 0;

  const runwayStatus = cashRunway == null ? null : cashRunway >= 4 ? 'safe' : cashRunway >= 2.5 ? 'adequate' : 'critical';

  const categoryFinancials = Object.entries(inventory.category_summary)
    .map(([name, v]) => ({
      name,
      margin: Math.max(0, Math.round(v.avg_margin_pct)),
      value: Math.round(v.value_usd / 1000),
    }))
    .filter((c) => c.margin > 0)
    .sort((a, b) => b.margin - a.margin);

  const radarAssets = displayAssets;
  const radarLiabilities = displayLiabilities;
  const healthRadar = [
    { subject: 'Margin', value: Math.min(100, (blendedMargin / MARGIN_HEALTHY) * 100) },
    { subject: 'Stock Turnover', value: Math.min(100, capitalUtilisation) },
    { subject: 'SKU Health', value: Math.min(100, (m.healthy_skus / Math.max(m.total_skus, 1)) * 100) },
    { subject: 'Dead Stock', value: Math.max(0, 100 - (m.dead_stock_skus / Math.max(m.total_skus, 1)) * 200) },
    { subject: 'Retail Cover', value: radarAssets > 0 ? Math.min(100, ((radarAssets - radarLiabilities) / radarAssets) * 100) : 50 },
  ];

  const healthScore = Math.round(healthRadar.reduce((s, d) => s + d.value, 0) / healthRadar.length);

  const alertCounts = { critical: 0, high: 0, medium: 0, low: 0 };
  inventory.alerts.forEach((a) => {
    if (a.severity in alertCounts) (alertCounts as Record<string, number>)[a.severity]++;
  });

  const breakevenRevenue = storedProfile?.breakeven_monthly_revenue_usd ?? null;
  const opexCoverage = annualRevenue != null && monthlyOpex != null && monthlyOpex > 0
    ? (annualRevenue * (blendedMargin / 100)) / (monthlyOpex * 12)
    : null;

  const hasStoredProfile = !!storedProfile && (
    storedProfile.total_assets_usd != null ||
    storedProfile.monthly_fixed_opex_usd != null ||
    storedProfile.cash_runway_months != null
  );

  // Profitability formula components
  const retailTotal = m.inventory_value_at_retail_usd;
  const costTotal = m.inventory_value_at_cost_usd;
  const marginPct = retailTotal > 0
    ? ((retailTotal - costTotal) / retailTotal) * 100
    : 0;

  return (
    <>
      <TopBar
        title="Financial Health"
        subtitle={`Lebanon · fresh USD · synced ${relativeTime(metadata.generated_at)}`}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={openDialog}
              className="hidden md:inline-flex items-center gap-2 text-[12.5px]"
            >
              <Settings className="h-3.5 w-3.5" />
              Update Profile
            </Button>
            <Link
              to="/assistant"
              state={{ initialMessage: FINANCIAL_PROMPT }}
              className="hidden md:inline-flex items-center gap-2 h-9 px-4 rounded-md bg-foreground text-background text-[12.5px] font-semibold hover:bg-foreground/90 transition"
            >
              <Bot className="h-3.5 w-3.5" />
              Ask Radar AI
            </Link>
          </div>
        }
      />

      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">

        {/* No financial profile banner */}
        {!hasStoredProfile && lineItems.length === 0 && (
          <div className="flex items-center justify-between gap-4 rounded-xl border border-dashed border-border bg-accent/20 px-5 py-4">
            <div>
              <p className="text-[13px] font-semibold text-foreground">No financial profile set</p>
              <p className="text-[12px] text-muted-foreground mt-0.5">
                Add your assets and liabilities below, or enter aggregate figures via Update Profile.
              </p>
            </div>
            <Button size="sm" variant="outline" onClick={openDialog} className="shrink-0 gap-2">
              <Settings className="h-3.5 w-3.5" /> Update Profile
            </Button>
          </div>
        )}

        {/* KPI cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard
            label="Blended Margin"
            icon={TrendingUp}
            variant={marginHealth === 'healthy' ? 'success' : marginHealth === 'warning' ? 'warning' : 'danger'}
            value={fmtPct(blendedMargin)}
            hint={`Target ≥ ${MARGIN_HEALTHY}% · Lebanon healthy band`}
            trend={blendedMargin >= MARGIN_HEALTHY ? { value: 'Healthy', direction: 'up' } : { value: 'Below target', direction: 'down' }}
          />
          <KpiCard
            label="Total Assets"
            icon={DollarSign}
            variant="data"
            value={fmtUSD(displayAssets, { compact: true })}
            hint={
              displayLiabilities > 0
                ? `Liabilities ${fmtUSD(displayLiabilities, { compact: true })} · Equity ${fmtUSD(displayEquity, { compact: true })}`
                : `Inventory at cost + user items`
            }
          />
          <KpiCard
            label={cashRunway != null ? 'Cash Runway' : 'Capital Utilisation'}
            icon={Boxes}
            variant={
              cashRunway != null
                ? runwayStatus === 'safe' ? 'success' : runwayStatus === 'adequate' ? 'warning' : 'danger'
                : capitalUtilisation >= 85 ? 'success' : 'warning'
            }
            value={cashRunway != null ? `${cashRunway} mo` : `${capitalUtilisation}%`}
            hint={
              cashRunway != null
                ? `Target ≥ 4 months · Status: ${runwayStatus}`
                : `${m.total_skus - m.dead_stock_skus} of ${m.total_skus} SKUs actively moving`
            }
            trend={
              cashRunway != null
                ? runwayStatus === 'safe' ? { value: 'Safe', direction: 'up' } : { value: 'At risk', direction: 'down' }
                : undefined
            }
          />
          <KpiCard
            label="Dead Stock Exposure"
            icon={ShieldAlert}
            variant={m.dead_stock_skus === 0 ? 'success' : 'danger'}
            value={fmtNum(m.dead_stock_skus)}
            hint={`Est. ${fmtUSD(deadStockValue, { compact: true })} tied up in dead stock`}
          />
        </div>

        {/* Additional profile KPIs if stored */}
        {(displayCurrentRatio != null || monthlyOpex != null || annualRevenue != null || breakevenRevenue != null) && (
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
            {displayCurrentRatio != null && (
              <KpiCard
                label="Current Ratio"
                icon={TrendingUp}
                variant={displayCurrentRatio >= 2 ? 'success' : displayCurrentRatio >= 1.5 ? 'warning' : 'danger'}
                value={`${displayCurrentRatio.toFixed(2)}x`}
                hint="Target ≥ 2.0x for Lebanon · Total Assets / Total Liabilities"
              />
            )}
            {monthlyOpex != null && (
              <KpiCard
                label="Monthly Fixed OpEx"
                icon={DollarSign}
                variant="default"
                value={fmtUSD(monthlyOpex, { compact: true })}
                hint={`Annual ${fmtUSD(monthlyOpex * 12, { compact: true })} fixed cost base`}
              />
            )}
            {annualRevenue != null && (
              <KpiCard
                label="Annual Revenue (Proj.)"
                icon={BarChart2}
                variant="data"
                value={fmtUSD(annualRevenue, { compact: true })}
                hint={monthlyOpex ? `OpEx coverage ${((annualRevenue * (blendedMargin / 100)) / (monthlyOpex * 12)).toFixed(1)}x` : 'Projected annual revenue'}
              />
            )}
            {opexCoverage != null && (
              <KpiCard
                label="OpEx Coverage"
                icon={BarChart2}
                variant={opexCoverage >= 1.5 ? 'success' : opexCoverage >= 1 ? 'warning' : 'danger'}
                value={`${opexCoverage.toFixed(1)}x`}
                hint="Gross profit / annual fixed OpEx · target ≥ 1.5×"
              />
            )}
            {breakevenRevenue != null && (
              <KpiCard
                label="Breakeven/Month"
                icon={TrendingUp}
                variant={annualRevenue != null ? ((annualRevenue / 12) >= breakevenRevenue ? 'success' : 'danger') : 'default'}
                value={fmtUSD(breakevenRevenue, { compact: true })}
                hint={annualRevenue != null
                  ? `Proj. monthly ${fmtUSD(annualRevenue / 12, { compact: true })} · ${(annualRevenue / 12) >= breakevenRevenue ? 'above target' : 'below target'}`
                  : 'Minimum monthly revenue to cover costs'
                }
                trend={annualRevenue != null
                  ? (annualRevenue / 12) >= breakevenRevenue
                    ? { value: 'Above', direction: 'up' }
                    : { value: 'Below', direction: 'down' }
                  : undefined
                }
              />
            )}
          </div>
        )}

        {/* ── Balance Sheet ──────────────────────────────────────────────── */}
        <Section
          title="Balance Sheet"
          subtitle="Itemized assets and liabilities — edit inline, add new rows, or remove"
          action={
            <div className="flex items-center gap-1.5">
              <Info className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-[11px] text-muted-foreground font-mono">Inventory rows are live · cannot edit</span>
            </div>
          }
        >
          <div className="grid lg:grid-cols-2 gap-6 mt-1">

            {/* Assets column */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-[11px] uppercase tracking-wider font-mono text-decision-promote font-semibold">Assets</span>
                <span className="text-[11px] font-mono text-muted-foreground">
                  Total: <span className="text-foreground font-semibold">{fmtUSD(displayAssets, { compact: true })}</span>
                </span>
              </div>

              {/* Live inventory row — non-editable */}
              <div className="flex items-center gap-2 py-1.5 px-1 rounded-md bg-accent/10">
                <span className="flex-1 text-[13px] text-foreground truncate">Inventory at Cost</span>
                <span className="text-[10px] font-mono bg-primary/10 text-primary px-1.5 py-0.5 rounded shrink-0">live</span>
                <span className="text-[13px] font-mono font-semibold text-foreground shrink-0">
                  {fmtUSD(inventoryCostUSD, { compact: true })}
                </span>
                <span className="h-6 w-6 shrink-0" />
                <span className="h-6 w-6 shrink-0" />
              </div>

              {/* User-added asset rows */}
              {assets.map((item) => (
                <LineItemRow
                  key={item.id}
                  item={item}
                  onSave={(id, label, amount_usd) =>
                    updateItemMutation.mutate({ id, label, amount_usd, item_type: 'asset' })
                  }
                  onDelete={(id) => deleteItemMutation.mutate(id)}
                  isSaving={updateItemMutation.isPending}
                  isDeleting={deleteItemMutation.isPending}
                />
              ))}

              {/* Add asset form */}
              {addingType === 'asset' ? (
                <AddItemRow
                  itemType="asset"
                  onAdd={(label, amount_usd) =>
                    createItemMutation.mutate({ label, amount_usd, item_type: 'asset' })
                  }
                  onCancel={() => setAddingType(null)}
                  isSaving={createItemMutation.isPending}
                />
              ) : (
                <button
                  onClick={() => setAddingType('asset')}
                  className="mt-2 flex items-center gap-1.5 text-[12px] text-muted-foreground hover:text-foreground transition"
                >
                  <Plus className="h-3.5 w-3.5" /> Add asset
                </button>
              )}

              {/* Formula */}
              <div className="mt-4 rounded-lg bg-accent/20 px-3 py-2.5 text-[11.5px] text-muted-foreground leading-relaxed font-mono">
                <span className="text-foreground font-semibold">How calculated: </span>
                Inventory ({fmtUSD(inventoryCostUSD, { compact: true })}, live)
                {assets.map((a) => (
                  <span key={a.id}> + {a.label} ({fmtUSD(a.amount_usd, { compact: true })})</span>
                ))}
                {' '}<span className="text-decision-promote">= {fmtUSD(displayAssets, { compact: true })}</span>
              </div>
            </div>

            {/* Liabilities column */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-[11px] uppercase tracking-wider font-mono text-decision-clear font-semibold">Liabilities</span>
                <span className="text-[11px] font-mono text-muted-foreground">
                  Total: <span className="text-foreground font-semibold">{fmtUSD(displayLiabilities, { compact: true })}</span>
                </span>
              </div>

              {/* User-added liability rows */}
              {liabilities.length === 0 && addingType !== 'liability' && (
                <p className="text-[12.5px] text-muted-foreground py-2">No liabilities added yet.</p>
              )}
              {liabilities.map((item) => (
                <LineItemRow
                  key={item.id}
                  item={item}
                  onSave={(id, label, amount_usd) =>
                    updateItemMutation.mutate({ id, label, amount_usd, item_type: 'liability' })
                  }
                  onDelete={(id) => deleteItemMutation.mutate(id)}
                  isSaving={updateItemMutation.isPending}
                  isDeleting={deleteItemMutation.isPending}
                />
              ))}

              {/* Add liability form */}
              {addingType === 'liability' ? (
                <AddItemRow
                  itemType="liability"
                  onAdd={(label, amount_usd) =>
                    createItemMutation.mutate({ label, amount_usd, item_type: 'liability' })
                  }
                  onCancel={() => setAddingType(null)}
                  isSaving={createItemMutation.isPending}
                />
              ) : (
                <button
                  onClick={() => setAddingType('liability')}
                  className="mt-2 flex items-center gap-1.5 text-[12px] text-muted-foreground hover:text-foreground transition"
                >
                  <Plus className="h-3.5 w-3.5" /> Add liability
                </button>
              )}

              {/* Formula + net equity */}
              <div className="mt-4 rounded-lg bg-accent/20 px-3 py-2.5 text-[11.5px] text-muted-foreground leading-relaxed font-mono space-y-1">
                {liabilities.length > 0 ? (
                  <div>
                    <span className="text-foreground font-semibold">How calculated: </span>
                    {liabilities.map((l, i) => (
                      <span key={l.id}>{i > 0 ? ' + ' : ''}{l.label} ({fmtUSD(l.amount_usd, { compact: true })})</span>
                    ))}
                    {' '}<span className="text-decision-clear">= {fmtUSD(displayLiabilities, { compact: true })}</span>
                  </div>
                ) : (
                  <div>Add liabilities to see the formula.</div>
                )}
                <div className="border-t border-border pt-1.5 text-foreground font-semibold">
                  Net Equity = {fmtUSD(displayAssets, { compact: true })} − {fmtUSD(displayLiabilities, { compact: true })}{' '}
                  <span className={displayEquity >= 0 ? 'text-decision-promote' : 'text-decision-clear'}>
                    = {fmtUSD(displayEquity, { compact: true })}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {displayLiabilities > 0 && displayAssets > 0 && (
            <div className="mt-4 space-y-1.5">
              <div className="flex justify-between text-[11px] font-mono text-muted-foreground">
                <span>Equity {fmtPct((displayEquity / displayAssets) * 100, 0)}</span>
                <span>Liabilities {fmtPct((displayLiabilities / displayAssets) * 100, 0)}</span>
              </div>
              <div className="h-2 rounded-full bg-accent overflow-hidden flex">
                <div
                  className="h-full bg-decision-promote transition-all"
                  style={{ width: `${Math.min(100, Math.max(0, (displayEquity / displayAssets) * 100))}%` }}
                />
                <div
                  className="h-full bg-decision-clear"
                  style={{ width: `${Math.min(100, (displayLiabilities / displayAssets) * 100)}%` }}
                />
              </div>
              <div className="text-[11px] font-mono text-muted-foreground text-center">
                {displayCurrentRatio != null
                  ? `${displayCurrentRatio.toFixed(2)}x current ratio · equity/asset leverage`
                  : 'Add liabilities to compute leverage ratio'}
              </div>
            </div>
          )}
        </Section>

        {/* ── Profitability Breakdown ───────────────────────────────────── */}
        <Section
          title="Profitability Breakdown"
          subtitle="How gross margin is calculated from your live inventory"
        >
          <div className="grid lg:grid-cols-3 gap-4 mt-1">
            <div className="rounded-lg bg-accent/20 px-4 py-3 space-y-1">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-mono">Retail Value</div>
              <div className="text-[22px] font-display font-bold text-foreground">{fmtUSD(retailTotal, { compact: true })}</div>
              <div className="text-[11.5px] text-muted-foreground font-mono">Sum of all SKU retail prices × units</div>
            </div>
            <div className="rounded-lg bg-accent/20 px-4 py-3 space-y-1">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-mono">Cost Value</div>
              <div className="text-[22px] font-display font-bold text-foreground">{fmtUSD(costTotal, { compact: true })}</div>
              <div className="text-[11.5px] text-muted-foreground font-mono">Sum of all SKU cost prices × units (live)</div>
            </div>
            <div className="rounded-lg bg-accent/20 px-4 py-3 space-y-1">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-mono">Gross Profit</div>
              <div className="text-[22px] font-display font-bold text-decision-promote">{fmtUSD(grossProfit, { compact: true })}</div>
              <div className="text-[11.5px] text-muted-foreground font-mono">Retail − Cost</div>
            </div>
          </div>

          <div className="mt-4 rounded-lg border border-border bg-background px-4 py-3 font-mono text-[12.5px] leading-loose">
            <div className="text-muted-foreground">
              Blended Margin = <span className="text-foreground">(Retail − Cost) / Retail × 100</span>
            </div>
            <div className="text-muted-foreground">
              = <span className="text-foreground">
                ({fmtUSD(retailTotal, { compact: true })} − {fmtUSD(costTotal, { compact: true })}) / {fmtUSD(retailTotal, { compact: true })} × 100
              </span>
            </div>
            <div className="text-muted-foreground">
              = <span className={cn(
                'font-bold text-[14px]',
                marginHealth === 'healthy' ? 'text-decision-promote' : marginHealth === 'warning' ? 'text-decision-markdown' : 'text-decision-clear'
              )}>
                {marginPct.toFixed(1)}%
              </span>
              <span className={cn('ml-3 text-[11px] inline-flex items-center gap-1', marginHealth === 'healthy' ? 'text-decision-promote' : marginHealth === 'warning' ? 'text-decision-markdown' : 'text-decision-clear')}>
                {marginHealth === 'healthy'
                  ? <><CheckCircle2 className="h-3 w-3" /> Above target</>
                  : marginHealth === 'warning'
                  ? <><AlertTriangle className="h-3 w-3" /> Below healthy threshold</>
                  : <><XCircle className="h-3 w-3" /> Below floor</>}
              </span>
            </div>
            <div className="mt-2 pt-2 border-t border-border text-[11px] text-muted-foreground">
              Target: ≥ {MARGIN_HEALTHY}% healthy · ≥ {MARGIN_FLOOR}% floor · Lebanon sportswear thresholds
            </div>
          </div>

          <div className="mt-3 space-y-1.5">
            <div className="flex justify-between text-[10px] font-mono text-muted-foreground">
              <span>0%</span>
              <span>Floor {MARGIN_FLOOR}%</span>
              <span>Target {MARGIN_HEALTHY}%</span>
              <span>100%</span>
            </div>
            <div className="relative h-2.5 rounded-full bg-accent">
              <div
                className={cn('h-full rounded-full transition-all', marginHealth === 'healthy' ? 'bg-decision-promote' : marginHealth === 'warning' ? 'bg-decision-markdown' : 'bg-decision-clear')}
                style={{ width: `${Math.min(100, Math.max(0, marginPct))}%` }}
              />
              <div className="absolute top-0 h-full w-0.5 bg-decision-markdown/70 rounded-full" style={{ left: `${MARGIN_FLOOR}%` }} />
              <div className="absolute top-0 h-full w-0.5 bg-decision-promote/70 rounded-full" style={{ left: `${MARGIN_HEALTHY}%` }} />
            </div>
          </div>

          {/* Per-category breakdown hint */}
          <p className="text-[12px] text-muted-foreground mt-3 flex items-center gap-1.5">
            <Info className="h-3.5 w-3.5 shrink-0" />
            See Margin by Category below for per-category breakdown. Categories below {MARGIN_FLOOR}% may be pulling the blended rate down.
          </p>
        </Section>

        {/* Health radar + Alerts */}
        <div className="grid lg:grid-cols-[1fr_1.4fr] gap-6">
          <Section
            title="Financial Health Radar"
            subtitle="Composite score across key financial dimensions"
            action={
              <span className={cn(
                'text-[13px] font-bold font-mono px-2.5 py-1 rounded-lg',
                healthScore >= 70 ? 'bg-decision-promote-bg text-decision-promote' :
                healthScore >= 50 ? 'bg-decision-markdown-bg text-decision-markdown' :
                'bg-decision-clear-bg text-decision-clear'
              )}>
                {healthScore}/100
              </span>
            }
          >
            <div className="h-64">
              <ResponsiveContainer>
                <RadarChart data={healthRadar}>
                  <PolarGrid stroke="hsl(var(--border))" />
                  <PolarAngleAxis dataKey="subject" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
                  <Radar
                    name="Health"
                    dataKey="value"
                    stroke="hsl(var(--primary))"
                    fill="hsl(var(--primary))"
                    fillOpacity={0.2}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {[
                { label: 'Margin health', value: marginHealth, color: marginHealth === 'healthy' ? 'text-decision-promote' : marginHealth === 'warning' ? 'text-decision-markdown' : 'text-decision-clear' },
                { label: 'Dead stock SKUs', value: fmtNum(m.dead_stock_skus), color: m.dead_stock_skus === 0 ? 'text-decision-promote' : 'text-decision-clear' },
                { label: 'Healthy SKUs', value: fmtNum(m.healthy_skus), color: 'text-decision-promote' },
                { label: 'Excess SKUs', value: fmtNum(m.excess_stock_skus), color: 'text-decision-markdown' },
              ].map((row) => (
                <div key={row.label} className="flex items-center justify-between px-3 py-2 rounded-md bg-accent/30 text-[12px]">
                  <span className="text-muted-foreground">{row.label}</span>
                  <span className={`font-semibold font-mono ${row.color}`}>{row.value}</span>
                </div>
              ))}
            </div>
          </Section>

          <Section
            title="Financial Alerts"
            subtitle="Signals from the analytics engine"
            action={<span className="text-[11px] font-mono text-muted-foreground">{inventory.alerts.length} total</span>}
          >
            {inventory.alerts.length === 0 ? (
              <p className="text-[13px] text-muted-foreground py-4 text-center">No active financial alerts.</p>
            ) : (
              <>
                {(alertCounts.critical > 0 || alertCounts.high > 0 || alertCounts.medium > 0 || alertCounts.low > 0) && (
                  <div className="flex flex-wrap gap-1.5 mb-3">
                    {alertCounts.critical > 0 && <span className="text-[10px] font-mono bg-decision-clear-bg text-decision-clear px-2 py-0.5 rounded-full">{alertCounts.critical} critical</span>}
                    {alertCounts.high > 0 && <span className="text-[10px] font-mono bg-decision-markdown-bg text-decision-markdown px-2 py-0.5 rounded-full">{alertCounts.high} high</span>}
                    {alertCounts.medium > 0 && <span className="text-[10px] font-mono bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">{alertCounts.medium} medium</span>}
                    {alertCounts.low > 0 && <span className="text-[10px] font-mono bg-secondary text-secondary-foreground px-2 py-0.5 rounded-full">{alertCounts.low} low</span>}
                  </div>
                )}
                <ul className="divide-y divide-border -my-2">
                  {inventory.alerts.slice(0, 7).map((a) => (
                    <li key={a.id} className="flex items-start gap-3 py-3">
                      <div className={`h-7 w-7 rounded-md flex items-center justify-center shrink-0 ${
                        a.severity === 'critical' ? 'bg-decision-clear-bg text-decision-clear' :
                        a.severity === 'high' ? 'bg-decision-markdown-bg text-decision-markdown' :
                        a.severity === 'medium' ? 'bg-amber-100 text-amber-700' : 'bg-secondary text-secondary-foreground'
                      }`}>
                        {a.severity === 'critical' ? <ShieldAlert className="h-3.5 w-3.5" /> :
                         a.severity === 'high' ? <AlertTriangle className="h-3.5 w-3.5" /> :
                         a.severity === 'medium' ? <Info className="h-3.5 w-3.5" /> :
                         <CheckCircle2 className="h-3.5 w-3.5" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-semibold text-foreground">{a.title}</div>
                        <p className="text-[12px] text-muted-foreground mt-0.5">{a.detail}</p>
                      </div>
                      <div className={`text-[10px] font-mono uppercase shrink-0 ${
                        a.severity === 'critical' || a.severity === 'high' ? 'text-decision-clear' :
                        a.severity === 'medium' ? 'text-decision-markdown' : 'text-muted-foreground'
                      }`}>
                        {a.severity}
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Section>
        </div>

        {/* Category margins */}
        <Section title="Margin by Category" subtitle="Gross margin % across product categories">
          <div className="h-56 -mx-2">
            <ResponsiveContainer>
              <BarChart data={categoryFinancials} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false}
                  tickFormatter={(v) => `${v}%`} domain={[0, 'auto']} />
                <Tooltip
                  contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                  formatter={(v: number, _name: string, props: { payload?: { value?: number } }) => [
                    [`${v}%`, 'Margin'],
                    [fmtUSD((props.payload?.value ?? 0) * 1000, { compact: true }), 'Inventory'],
                  ]}
                />
                <ReferenceLine y={MARGIN_HEALTHY} stroke="hsl(var(--decision-promote))" strokeDasharray="4 3" strokeWidth={1.5} />
                <ReferenceLine y={MARGIN_FLOOR} stroke="hsl(var(--decision-markdown))" strokeDasharray="4 3" strokeWidth={1.5} />
                <Bar dataKey="margin" radius={[6, 6, 0, 0]}>
                  {categoryFinancials.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={
                        entry.margin >= MARGIN_HEALTHY
                          ? 'hsl(var(--decision-promote))'
                          : entry.margin >= MARGIN_FLOOR
                          ? 'hsl(var(--decision-markdown))'
                          : 'hsl(var(--decision-clear))'
                      }
                    />
                  ))}
                  <LabelList dataKey="margin" position="top" formatter={(v: number) => `${v}%`} style={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="flex gap-4 mt-2 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-4 rounded-full bg-decision-promote inline-block" /> Healthy ≥{MARGIN_HEALTHY}%
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-4 rounded-full bg-decision-markdown inline-block" /> Floor ≥{MARGIN_FLOOR}%
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-4 rounded-full bg-decision-clear inline-block" /> Below floor
            </span>
          </div>
        </Section>

        {/* Radar Assistant CTA */}
        <div className="relative panel-dark rounded-2xl overflow-hidden shadow-lg-soft">
          <div className="absolute inset-0 opacity-25" style={{
            background: 'radial-gradient(600px 200px at 90% 50%, hsl(218 92% 60% / 0.5), transparent)',
          }} />
          <div className="relative p-6 lg:p-8 flex flex-col lg:flex-row items-start lg:items-center gap-6">
            <div className="h-12 w-12 rounded-xl bg-primary-glow/20 border border-primary/30 flex items-center justify-center shrink-0">
              <Bot className="h-6 w-6 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[11px] font-mono uppercase tracking-[0.16em] text-panel-muted mb-1">Radar Assistant</div>
              <h3 className="font-display text-[18px] font-semibold text-panel-foreground">
                Ask financial questions in plain language
              </h3>
              <p className="text-panel-muted text-[13.5px] mt-1 max-w-xl">
                "What's dragging my margin down?", "Which categories are most profitable?",
                "How much cash is locked in dead stock?" — Radar AI answers from live data.
              </p>
            </div>
            <div className="flex flex-col sm:flex-row gap-3 shrink-0">
              <Link
                to="/assistant"
                state={{ initialMessage: FINANCIAL_PROMPT }}
                className="inline-flex items-center gap-2 h-10 px-5 rounded-md bg-primary-glow text-primary-foreground text-[13px] font-semibold hover:opacity-90 transition shadow-glow"
              >
                Open Radar Assistant <ArrowRight className="h-3.5 w-3.5" />
              </Link>
              <Link
                to="/queue"
                className="inline-flex items-center gap-2 h-10 px-5 rounded-md border border-panel-border text-panel-foreground text-[13px] font-medium hover:bg-white/5 transition"
              >
                <BarChart2 className="h-3.5 w-3.5" />
                Review recommendations
              </Link>
            </div>
          </div>
        </div>

      </main>

      {/* Financial Profile Dialog */}
      <Dialog open={profileOpen} onOpenChange={(next) => !next && setProfileOpen(false)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Update Financial Profile</DialogTitle>
          </DialogHeader>
          <p className="text-[12.5px] text-muted-foreground -mt-2">
            Enter aggregate balance sheet and cashflow figures. For itemized assets and liabilities, use the Balance Sheet section on the page.
          </p>
          <div className="grid grid-cols-2 gap-3 mt-1">
            <Field label="Total Assets (USD)">
              <Input inputMode="decimal" placeholder="e.g. 300000"
                value={form.total_assets_usd} onChange={(e) => update('total_assets_usd', decimalText(e.target.value))} />
            </Field>
            <Field label="Total Liabilities (USD)">
              <Input inputMode="decimal" placeholder="e.g. 45000"
                value={form.total_liabilities_usd} onChange={(e) => update('total_liabilities_usd', decimalText(e.target.value))} />
            </Field>
            <Field label="Monthly Fixed OpEx (USD)">
              <Input inputMode="decimal" placeholder="e.g. 3500"
                value={form.monthly_fixed_opex_usd} onChange={(e) => update('monthly_fixed_opex_usd', decimalText(e.target.value))} />
            </Field>
            <Field label="Annual Revenue Projected (USD)">
              <Input inputMode="decimal" placeholder="e.g. 2000000"
                value={form.annual_revenue_projected_usd} onChange={(e) => update('annual_revenue_projected_usd', decimalText(e.target.value))} />
            </Field>
            <Field label="Cash Runway (months)">
              <Input inputMode="decimal" placeholder="e.g. 6"
                value={form.cash_runway_months} onChange={(e) => update('cash_runway_months', decimalText(e.target.value))} />
            </Field>
            <Field label="Breakeven Monthly Revenue (USD)" className="col-span-2 md:col-span-1">
              <Input inputMode="decimal" placeholder="optional"
                value={form.breakeven_monthly_revenue_usd} onChange={(e) => update('breakeven_monthly_revenue_usd', decimalText(e.target.value))} />
            </Field>
          </div>
          <DialogFooter className="mt-2">
            <Button variant="outline" onClick={() => setProfileOpen(false)}>Cancel</Button>
            <Button disabled={saveMutation.isPending} onClick={handleSave} className="gap-2">
              <Save className="h-3.5 w-3.5" />
              {saveMutation.isPending ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
