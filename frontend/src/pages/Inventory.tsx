import { useMemo, useRef, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { KpiCard } from '@/components/shared/KpiCard';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtNum, fmtPct, fmtUSD } from '@/lib/format';
import { cn } from '@/lib/utils';
import {
  archiveRetailInventoryItem,
  createRetailInventoryItem,
  fetchRetailDbStatus,
  fetchRetailInventory,
  importRetailInventory,
  updateRetailInventoryItem,
} from '@/lib/adapter';
import { parseInventoryCsv } from '@/lib/inventoryCsv';
import type { Report, RetailInventoryInput, RetailInventoryItem } from '@/types/domain';
import { AlertTriangle, Archive, Boxes, Database, Pencil, Plus, RefreshCw, Save, Search, Upload } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid, Cell } from 'recharts';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';

type InventoryFormState = Omit<
  RetailInventoryInput,
  'current_stock' | 'retail_price_usd' | 'cost_price_usd' | 'reorder_point' | 'reorder_quantity'
> & {
  current_stock: string;
  retail_price_usd: string;
  cost_price_usd: string;
  reorder_point: string;
  reorder_quantity: string;
};

const EMPTY_FORM: InventoryFormState = {
  sku_id: '',
  product_name: '',
  brand: '',
  category: '',
  current_stock: '',
  retail_price_usd: '',
  cost_price_usd: '',
  barcode: '',
  style_code: '',
  color: '',
  size: '',
  gender_target: '',
  season: '',
  reorder_point: '',
  reorder_quantity: '',
  supplier_name: '',
  notes: '',
};

const SAMPLE_CSV = `sku_id,product_name,brand,category,current_stock,retail_price_usd,cost_price_usd,barcode,style_code,reorder_point,reorder_quantity
AD-RUN-001,Adidas Ultraboost 5,Adidas,footwear,18,180,92,,UB5-BLK,5,12
NK-TEE-022,Nike Dri-FIT Tee,Nike,apparel,42,45,19,,DRI-TEE,10,24`;

export default function Inventory() {
  const { data: report, isLoading } = useReport();

  return (
    <>
      <TopBar title="Inventory" subtitle="Retail stock control and inventory health" />
      <main className="flex-1 px-6 lg:px-8 py-6 animate-fade-in">
        <Tabs defaultValue="manage" className="space-y-6">
          <TabsList>
            <TabsTrigger value="manage">Manage inventory</TabsTrigger>
            <TabsTrigger value="analytics">Health analytics</TabsTrigger>
          </TabsList>
          <TabsContent value="manage">
            <InventoryManager />
          </TabsContent>
          <TabsContent value="analytics">
            {isLoading || !report ? <PageSkeleton /> : <InventoryAnalytics report={report} />}
          </TabsContent>
        </Tabs>
      </main>
    </>
  );
}

function InventoryManager() {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<RetailInventoryItem | null>(null);
  const [form, setForm] = useState<InventoryFormState>(EMPTY_FORM);
  const [csvText, setCsvText] = useState(SAMPLE_CSV);
  const [importMode, setImportMode] = useState<'upsert' | 'replace'>('upsert');

  const status = useQuery({
    queryKey: ['retail-db-status'],
    queryFn: fetchRetailDbStatus,
    retry: false,
  });

  const inventory = useQuery({
    queryKey: ['retail-inventory', search],
    queryFn: () => fetchRetailInventory(search),
    retry: false,
  });

  const parsed = useMemo(() => parseInventoryCsv(csvText), [csvText]);
  const items = inventory.data?.items || [];
  const summary = inventory.data?.summary;

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (editing) return updateRetailInventoryItem(editing.sku_id, normalizedForm(form));
      return createRetailInventoryItem(normalizedForm(form));
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['retail-inventory'] });
      queryClient.invalidateQueries({ queryKey: ['retail-db-status'] });
      setDialogOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      toast.success('Inventory item saved');
    },
    onError: (error: Error) => toast.error('Save failed', { description: error.message }),
  });

  const archiveMutation = useMutation({
    mutationFn: archiveRetailInventoryItem,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['retail-inventory'] });
      queryClient.invalidateQueries({ queryKey: ['retail-db-status'] });
      toast.success('SKU archived');
    },
    onError: (error: Error) => toast.error('Archive failed', { description: error.message }),
  });

  const importMutation = useMutation({
    mutationFn: () => importRetailInventory(parsed.rows, importMode),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['retail-inventory'] });
      queryClient.invalidateQueries({ queryKey: ['retail-db-status'] });
      toast.success('Inventory imported', { description: `${result.imported} rows imported, ${result.archived} archived.` });
    },
    onError: (error: Error) => toast.error('Import failed', { description: error.message }),
  });

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  };

  const openEdit = (item: RetailInventoryItem) => {
    setEditing(item);
    setForm({
      sku_id: item.sku_id,
      product_name: item.product_name,
      brand: item.brand,
      category: item.category,
      current_stock: String(item.current_stock ?? ''),
      retail_price_usd: String(item.retail_price_usd ?? ''),
      cost_price_usd: String(item.cost_price_usd ?? ''),
      barcode: item.barcode || '',
      style_code: item.style_code || '',
      color: item.color || '',
      size: item.size || '',
      gender_target: item.gender_target || '',
      season: item.season || '',
      reorder_point: String(item.reorder_point ?? ''),
      reorder_quantity: String(item.reorder_quantity ?? ''),
    });
    setDialogOpen(true);
  };

  const readCsvFile = async (file: File) => {
    setCsvText(await file.text());
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="DB status" icon={Database} value={status.data?.connected ? 'Online' : 'Offline'} hint={status.data?.store || 'MAIN'} />
        <KpiCard label="Managed SKUs" icon={Boxes} value={fmtNum(summary?.total_skus || 0)} hint={`${fmtNum(summary?.total_units || 0)} units`} />
        <KpiCard label="Cost value" icon={Boxes} value={fmtUSD(summary?.inventory_value_at_cost_usd || 0, { compact: true })} hint="local PostgreSQL" />
        <KpiCard label="Reorder flags" icon={AlertTriangle} variant="warning" value={fmtNum(summary?.reorder_count || 0)} hint="stock <= reorder point" />
      </div>

      {!status.data?.connected && (
        <Section title="PostgreSQL connection">
          <div className="text-[13px] text-decision-clear">
            {status.data?.error || inventory.error?.message || 'EEP cannot reach PostgreSQL.'}
          </div>
          <div className="mt-2 text-[12px] text-muted-foreground font-mono">
            DATABASE_URL={status.data?.database_url_hint || 'postgresql://postgres:postgres@localhost:5432/retail_radar'}
          </div>
        </Section>
      )}

      <div className="grid xl:grid-cols-[1.35fr_0.9fr] gap-6">
        <Section
          title="Inventory records"
          subtitle={`${items.length} rows from core.sku_variants and core.inventory_balances`}
          action={
            <div className="flex items-center gap-2">
              <div className="hidden md:flex items-center gap-2 h-9 px-3 rounded-md border border-border bg-card">
                <Search className="h-3.5 w-3.5 text-muted-foreground" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search SKU, product, brand"
                  className="w-52 bg-transparent outline-none text-[12.5px]"
                />
              </div>
              <Button size="sm" variant="outline" onClick={() => inventory.refetch()}>
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </Button>
              <Button size="sm" onClick={openCreate}>
                <Plus className="h-3.5 w-3.5" /> Add SKU
              </Button>
            </div>
          }
          bodyClassName="p-0"
        >
          <div className="overflow-x-auto scrollbar-thin">
            <table className="w-full text-[12.5px]">
              <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 text-left">SKU</th>
                  <th className="px-4 py-3 text-left">Product</th>
                  <th className="px-4 py-3 text-left">Brand</th>
                  <th className="px-4 py-3 text-left">Category</th>
                  <th className="px-4 py-3 text-right">Stock</th>
                  <th className="px-4 py-3 text-right">Retail</th>
                  <th className="px-4 py-3 text-right">Cost</th>
                  <th className="px-4 py-3 text-right">Margin</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {inventory.isLoading && (
                  <tr><td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">Loading inventory...</td></tr>
                )}
                {!inventory.isLoading && items.length === 0 && (
                  <tr><td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">No inventory rows yet.</td></tr>
                )}
                {items.map((item) => (
                  <tr key={item.sku_id} className="border-t border-border hover:bg-accent/40">
                    <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground">{item.sku_id}</td>
                    <td className="px-4 py-2.5 min-w-[240px]">
                      <div className="font-medium">{item.product_name}</div>
                      <div className="text-[11px] text-muted-foreground font-mono">{item.style_code || item.barcode || 'no identifier'}</div>
                    </td>
                    <td className="px-4 py-2.5">{item.brand}</td>
                    <td className="px-4 py-2.5">{item.category}</td>
                    <td className={cn('px-4 py-2.5 text-right font-mono', item.needs_reorder ? 'text-decision-markdown' : '')}>{fmtNum(item.current_stock)}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{fmtUSD(item.retail_price_usd)}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{fmtUSD(item.cost_price_usd)}</td>
                    <td className={cn('px-4 py-2.5 text-right font-mono', item.margin_pct < 35 ? 'text-decision-clear' : item.margin_pct >= 45 ? 'text-decision-promote' : '')}>{fmtPct(item.margin_pct, 0)}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex justify-end gap-1">
                        <Button size="icon" variant="ghost" title="Edit SKU" onClick={() => openEdit(item)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="icon" variant="ghost" title="Archive SKU" onClick={() => archiveMutation.mutate(item.sku_id)}>
                          <Archive className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <Section title="Bulk import" subtitle="CSV upload or direct paste" bodyClassName="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
              <Upload className="h-3.5 w-3.5" /> CSV file
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(event) => event.target.files?.[0] && readCsvFile(event.target.files[0])}
            />
            <select
              value={importMode}
              onChange={(event) => setImportMode(event.target.value as 'upsert' | 'replace')}
              className="h-9 rounded-md border border-border bg-card px-3 text-[12.5px]"
            >
              <option value="upsert">Upsert rows</option>
              <option value="replace">Replace full inventory</option>
            </select>
            <Button
              size="sm"
              disabled={parsed.rows.length === 0 || parsed.errors.length > 0 || importMutation.isPending}
              onClick={() => importMutation.mutate()}
            >
              <Save className="h-3.5 w-3.5" /> Import {parsed.rows.length || ''}
            </Button>
          </div>
          <Textarea
            value={csvText}
            onChange={(event) => setCsvText(event.target.value)}
            className="min-h-[220px] font-mono text-[12px]"
            spellCheck={false}
          />
          {parsed.errors.length > 0 ? (
            <div className="rounded-md border border-decision-clear/30 bg-decision-clear-bg p-3 text-[12px] text-decision-clear">
              {parsed.errors.slice(0, 5).map((error) => <div key={error}>{error}</div>)}
            </div>
          ) : (
            <div className="text-[12px] text-muted-foreground">
              {parsed.rows.length} valid rows. Required headers: sku_id, product_name, brand, category, current_stock, retail_price_usd, cost_price_usd.
            </div>
          )}
        </Section>
      </div>

      <InventoryDialog
        open={dialogOpen}
        editing={editing}
        form={form}
        setForm={setForm}
        saving={saveMutation.isPending}
        onClose={() => setDialogOpen(false)}
        onSave={() => saveMutation.mutate()}
      />
    </div>
  );
}

function InventoryDialog({
  open,
  editing,
  form,
  setForm,
  saving,
  onClose,
  onSave,
}: {
  open: boolean;
  editing: RetailInventoryItem | null;
  form: InventoryFormState;
  setForm: (value: InventoryFormState) => void;
  saving: boolean;
  onClose: () => void;
  onSave: () => void;
}) {
  const update = (key: keyof InventoryFormState, value: string) => setForm({ ...form, [key]: value });
  const canSave = form.sku_id.trim() && form.product_name.trim();

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit inventory item' : 'Add inventory item'}</DialogTitle>
        </DialogHeader>
        <div className="grid md:grid-cols-3 gap-3">
          <Field label="SKU"><Input value={form.sku_id} disabled={!!editing} onChange={(e) => update('sku_id', e.target.value)} /></Field>
          <Field label="Product" className="md:col-span-2"><Input value={form.product_name} onChange={(e) => update('product_name', e.target.value)} /></Field>
          <Field label="Brand"><Input value={form.brand} onChange={(e) => update('brand', e.target.value)} /></Field>
          <Field label="Category"><Input value={form.category} onChange={(e) => update('category', e.target.value)} /></Field>
          <Field label="Style code"><Input value={form.style_code || ''} onChange={(e) => update('style_code', e.target.value)} /></Field>
          <Field label="Stock"><Input inputMode="numeric" value={form.current_stock} onChange={(e) => update('current_stock', integerText(e.target.value))} /></Field>
          <Field label="Retail price"><Input inputMode="decimal" value={form.retail_price_usd} onChange={(e) => update('retail_price_usd', decimalText(e.target.value))} /></Field>
          <Field label="Cost price"><Input inputMode="decimal" value={form.cost_price_usd} onChange={(e) => update('cost_price_usd', decimalText(e.target.value))} /></Field>
          <Field label="Barcode"><Input value={form.barcode || ''} onChange={(e) => update('barcode', e.target.value)} /></Field>
          <Field label="Color"><Input value={form.color || ''} onChange={(e) => update('color', e.target.value)} /></Field>
          <Field label="Size"><Input value={form.size || ''} onChange={(e) => update('size', e.target.value)} /></Field>
          <Field label="Gender"><Input value={form.gender_target || ''} onChange={(e) => update('gender_target', e.target.value)} /></Field>
          <Field label="Season"><Input value={form.season || ''} onChange={(e) => update('season', e.target.value)} /></Field>
          <Field label="Reorder point"><Input inputMode="numeric" value={form.reorder_point} onChange={(e) => update('reorder_point', integerText(e.target.value))} /></Field>
          <Field label="Reorder qty"><Input inputMode="numeric" value={form.reorder_quantity} onChange={(e) => update('reorder_quantity', integerText(e.target.value))} /></Field>
          <Field label="Supplier"><Input value={form.supplier_name || ''} onChange={(e) => update('supplier_name', e.target.value)} /></Field>
          <Field label="Notes" className="md:col-span-3"><Textarea value={form.notes || ''} onChange={(e) => update('notes', e.target.value)} /></Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!canSave || saving} onClick={onSave}>
            <Save className="h-3.5 w-3.5" /> Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <label className={cn('space-y-1.5', className)}>
      <span className="text-[11px] uppercase tracking-wider text-muted-foreground font-mono">{label}</span>
      {children}
    </label>
  );
}

function InventoryAnalytics({ report: r }: { report: Report }) {
  const m = r.inventory.metrics;

  const dosBands = [
    { band: '<= 21', count: r.inventory.sku_analysis.filter(s => s.days_of_supply <= 21).length, color: 'hsl(var(--decision-clear))' },
    { band: '22-44', count: r.inventory.sku_analysis.filter(s => s.days_of_supply > 21 && s.days_of_supply < 45).length, color: 'hsl(var(--decision-markdown))' },
    { band: '45-90', count: r.inventory.sku_analysis.filter(s => s.days_of_supply >= 45 && s.days_of_supply <= 90).length, color: 'hsl(var(--decision-promote))' },
    { band: '91-180', count: r.inventory.sku_analysis.filter(s => s.days_of_supply > 90 && s.days_of_supply <= 180).length, color: 'hsl(var(--decision-markdown))' },
    { band: '> 180', count: r.inventory.sku_analysis.filter(s => s.days_of_supply > 180).length, color: 'hsl(var(--decision-clear))' },
  ];
  const watchlist = r.inventory.sku_analysis.filter(s => s.days_of_supply <= 30).slice(0, 12);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="Total SKUs" icon={Boxes} value={fmtNum(m.total_skus)} hint={`${fmtNum(m.total_units)} units`} />
        <KpiCard label="Healthy" icon={Boxes} variant="success" value={fmtNum(m.healthy_skus)} hint="DOS 45-90" />
        <KpiCard label="Excess Stock" icon={AlertTriangle} variant="warning" value={fmtNum(m.excess_stock_skus)} hint="DOS > 90" />
        <KpiCard label="Dead Stock" icon={Archive} variant="danger" value={fmtNum(m.dead_stock_skus)} hint="DOS > 180" />
      </div>

      <div className="grid lg:grid-cols-[1.3fr_1fr] gap-6">
        <Section title="Days of Supply Distribution" subtitle="Active dashboard report">
          <div className="h-72 -mx-2">
            <ResponsiveContainer>
              <BarChart data={dosBands} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="band" stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {dosBands.map((d) => <Cell key={d.band} fill={d.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Section>
        <Section title="Inventory Value" subtitle="Cost vs retail">
          <div className="space-y-4">
            <ValueBar label="At cost" value={m.inventory_value_at_cost_usd} max={m.inventory_value_at_retail_usd} color="bg-decision-hold" />
            <ValueBar label="At retail" value={m.inventory_value_at_retail_usd} max={m.inventory_value_at_retail_usd} color="bg-gradient-data" />
            <div className="rounded-lg bg-decision-promote-bg p-3 mt-4">
              <div className="text-[11px] uppercase font-mono tracking-wider text-decision-promote">Implied gross profit</div>
              <div className="text-data text-[24px] text-decision-promote mt-1">
                {fmtUSD(m.inventory_value_at_retail_usd - m.inventory_value_at_cost_usd, { compact: true })}
              </div>
              <div className="text-[12px] text-muted-foreground mt-1">at {fmtPct(m.blended_margin_pct)} blended margin</div>
            </div>
          </div>
        </Section>
      </div>

      <Section title="Category Comparison" bodyClassName="p-0">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-[13px]">
            <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-left">Category</th>
                <th className="px-4 py-3 text-right">SKUs</th>
                <th className="px-4 py-3 text-right">Units</th>
                <th className="px-4 py-3 text-right">Value</th>
                <th className="px-4 py-3 text-right">Margin</th>
                <th className="px-4 py-3 text-right">Median DOS</th>
                <th className="px-4 py-3 text-right">Health</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(r.inventory.category_summary).sort((a, b) => b[1].value_usd - a[1].value_usd).map(([k, v]) => (
                <tr key={k} className="border-t border-border hover:bg-accent/40">
                  <td className="px-4 py-2.5 font-semibold">{k}</td>
                  <td className="px-4 py-2.5 text-right font-mono">{v.skus}</td>
                  <td className="px-4 py-2.5 text-right font-mono">{fmtNum(v.units)}</td>
                  <td className="px-4 py-2.5 text-right font-mono">{fmtUSD(v.value_usd, { compact: true })}</td>
                  <td className={cn('px-4 py-2.5 text-right font-mono', v.avg_margin_pct >= 45 ? 'text-decision-promote' : v.avg_margin_pct < 35 ? 'text-decision-clear' : '')}>{fmtPct(v.avg_margin_pct, 0)}</td>
                  <td className="px-4 py-2.5 text-right font-mono">{v.median_dos}d</td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="inline-flex items-center gap-2">
                      <div className="h-1.5 w-16 rounded-full bg-muted overflow-hidden">
                        <div className={cn('h-full', v.health_score >= 70 ? 'bg-decision-promote' : v.health_score >= 50 ? 'bg-decision-markdown' : 'bg-decision-clear')} style={{ width: `${v.health_score}%` }} />
                      </div>
                      <span className="font-mono text-[12px]">{v.health_score}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="grid lg:grid-cols-[1.4fr_1fr] gap-6">
        <Section title="Stockout Watchlist" subtitle="DOS <= 30 days">
          <ul className="space-y-1.5">
            {watchlist.map(s => (
              <li key={s.sku_id} className="flex items-center gap-3 p-2.5 rounded-md hover:bg-accent/40">
                <div className="font-mono text-[10.5px] text-muted-foreground w-20">{s.sku_id}</div>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-medium truncate">{s.product_name}</div>
                  <div className="text-[11px] text-muted-foreground">{s.brand} / {s.category}</div>
                </div>
                <div className={cn('text-[12px] font-mono font-semibold', s.days_of_supply <= 21 ? 'text-decision-clear' : 'text-decision-markdown')}>{s.days_of_supply}d</div>
                <div className="text-[11px] text-muted-foreground font-mono w-12 text-right">{s.current_stock} u</div>
              </li>
            ))}
          </ul>
        </Section>
        <Section title="Inventory Alerts">
          <ul className="space-y-2">
            {r.inventory.alerts.map(a => (
              <li key={a.id} className="flex items-start gap-3 p-3 rounded-lg border border-border">
                <AlertTriangle className={cn('h-4 w-4 shrink-0 mt-0.5', a.severity === 'critical' ? 'text-decision-clear' : a.severity === 'high' ? 'text-decision-markdown' : 'text-amber-600')} />
                <div>
                  <div className="text-[13px] font-semibold">{a.title}</div>
                  <p className="text-[12px] text-muted-foreground mt-0.5">{a.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </div>
  );
}

function ValueBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-[12.5px] font-medium">{label}</span>
        <span className="text-data text-[16px] font-semibold">{fmtUSD(value, { compact: true })}</span>
      </div>
      <div className="h-3 rounded-full bg-muted overflow-hidden">
        <div className={cn('h-full', color)} style={{ width: `${max ? (value / max) * 100 : 0}%` }} />
      </div>
    </div>
  );
}

function normalizedForm(form: InventoryFormState): RetailInventoryInput {
  return {
    ...form,
    sku_id: form.sku_id.trim(),
    product_name: form.product_name.trim(),
    brand: form.brand.trim() || 'Unknown',
    category: form.category.trim() || 'uncategorized',
    current_stock: readNumber(form.current_stock),
    retail_price_usd: readNumber(form.retail_price_usd),
    cost_price_usd: readNumber(form.cost_price_usd),
    reorder_point: readNumber(form.reorder_point),
    reorder_quantity: readNumber(form.reorder_quantity),
    barcode: cleanNullable(form.barcode),
    style_code: cleanNullable(form.style_code),
    color: cleanNullable(form.color),
    size: cleanNullable(form.size),
    gender_target: cleanNullable(form.gender_target),
    season: cleanNullable(form.season),
    supplier_name: cleanNullable(form.supplier_name),
    notes: cleanNullable(form.notes),
  };
}

function cleanNullable(value: string | null | undefined) {
  return value?.trim() || null;
}

function readNumber(value: string) {
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) ? parsed : 0;
}

function integerText(value: string) {
  return value.replace(/[^\d]/g, '');
}

function decimalText(value: string) {
  const cleaned = value.replace(/[^\d.]/g, '');
  const [head, ...tail] = cleaned.split('.');
  return tail.length > 0 ? `${head}.${tail.join('')}` : head;
}
