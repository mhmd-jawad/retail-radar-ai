import { useMemo, useRef, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLiveReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { KpiCard } from '@/components/shared/KpiCard';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtDos, fmtNum, fmtPct, fmtUSD, isUnknownDos } from '@/lib/format';
import { cn } from '@/lib/utils';
import {
  archiveRetailInventoryItem,
  createRetailInventoryItem,
  fetchRetailDbStatus,
  fetchRetailInventory,
  importRetailInventory,
  recordRetailInventoryMovement,
  recommend,
  updateRetailInventoryItem,
} from '@/lib/adapter';
import { parseInventoryCsv } from '@/lib/inventoryCsv';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { writeSystemDecisionEntry } from '@/lib/systemDecisionCache';
import type {
  Report,
  RetailInventoryInput,
  RetailInventoryItem,
  RetailInventoryMovementInput,
  RetailInventoryMovementType,
  RetailInventoryResponse,
  IE2Request,
} from '@/types/domain';
import {
  AlertTriangle,
  Archive,
  Boxes,
  Database,
  PackagePlus,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Search,
  ShoppingCart,
  SlidersHorizontal,
  Upload,
} from 'lucide-react';
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

type InventoryMovementFormState = {
  item: RetailInventoryItem;
  movement_type: RetailInventoryMovementType;
  quantity: string;
  unit_price_usd: string;
  unit_cost_usd: string;
  discount_pct: string;
  channel: string;
  reference_id: string;
  notes: string;
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

const MOVEMENT_LABELS: Record<RetailInventoryMovementType, string> = {
  sale: 'Sold',
  purchase_receipt: 'Restock',
  return: 'Return',
  adjustment_in: 'Add stock',
  adjustment_out: 'Remove stock',
  damaged: 'Damaged',
};

const NEGATIVE_MOVEMENTS = new Set<RetailInventoryMovementType>(['sale', 'adjustment_out', 'damaged']);

const SAMPLE_CSV = `sku_id,product_name,brand,category,current_stock,retail_price_usd,cost_price_usd,barcode,style_code,reorder_point,reorder_quantity
AD-RUN-001,Adidas Ultraboost 5,Adidas,footwear,18,180,92,,UB5-BLK,5,12
NK-TEE-022,Nike Dri-FIT Tee,Nike,apparel,42,45,19,,DRI-TEE,10,24`;

export default function Inventory() {
  const { data: report, isLoading } = useLiveReport();

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
  const tenantScope = useTenantScopeKey();
  const fileRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<RetailInventoryItem | null>(null);
  const [form, setForm] = useState<InventoryFormState>(EMPTY_FORM);
  const [movement, setMovement] = useState<InventoryMovementFormState | null>(null);
  const [csvText, setCsvText] = useState(SAMPLE_CSV);
  const [importMode, setImportMode] = useState<'upsert' | 'replace'>('upsert');

  const status = useQuery({
    queryKey: ['retail-db-status', tenantScope],
    queryFn: fetchRetailDbStatus,
    retry: false,
  });

  const inventory = useQuery({
    queryKey: ['retail-inventory', tenantScope, search],
    queryFn: () => fetchRetailInventory(search),
    retry: false,
  });

  const parsed = useMemo(() => parseInventoryCsv(csvText), [csvText]);
  const items = inventory.data?.items || [];
  const summary = inventory.data?.summary;
  const canWrite = status.data?.connected === true;

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (editing) return updateRetailInventoryItem(editing.sku_id, normalizedForm(form));
      return createRetailInventoryItem(normalizedForm(form));
    },
    onSuccess: (savedItem) => {
      const wasEditing = Boolean(editing);
      queryClient.setQueryData<RetailInventoryResponse>(
        ['retail-inventory', tenantScope, search],
        (current) => upsertInventoryCache(current, savedItem, search),
      );
      queryClient.invalidateQueries({ queryKey: ['retail-inventory'] });
      queryClient.invalidateQueries({ queryKey: ['retail-db-status'] });
      queryClient.invalidateQueries({ queryKey: ['report-live'] });
      queryClient.invalidateQueries({ queryKey: ['report'] });
      setDialogOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      toast.success(wasEditing ? 'Inventory item saved to DB' : 'Inventory item added to DB', {
        description: `${savedItem.sku_id} persisted in core inventory tables.`,
      });
      if (!wasEditing) {
        syncNewSkuDecision(savedItem, tenantScope);
      }
    },
    onError: (error: Error) => toast.error('Save failed', { description: error.message }),
  });

  const archiveMutation = useMutation({
    mutationFn: archiveRetailInventoryItem,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['retail-inventory'] });
      queryClient.invalidateQueries({ queryKey: ['retail-db-status'] });
      queryClient.invalidateQueries({ queryKey: ['report-live'] });
      queryClient.invalidateQueries({ queryKey: ['report'] });
      toast.success('SKU archived');
    },
    onError: (error: Error) => toast.error('Archive failed', { description: error.message }),
  });

  const movementMutation = useMutation({
    mutationFn: async () => {
      if (!movement) throw new Error('No inventory action selected.');
      return recordRetailInventoryMovement(movement.item.sku_id, normalizedMovement(movement));
    },
    onSuccess: (result) => {
      queryClient.setQueryData<RetailInventoryResponse>(
        ['retail-inventory', tenantScope, search],
        (current) => upsertInventoryCache(current, result.item, search),
      );
      queryClient.invalidateQueries({ queryKey: ['retail-inventory'] });
      queryClient.invalidateQueries({ queryKey: ['retail-db-status'] });
      queryClient.invalidateQueries({ queryKey: ['report-live'] });
      queryClient.invalidateQueries({ queryKey: ['report'] });
      toast.success(`${MOVEMENT_LABELS[result.movement.movement_type]} saved`, {
        description: `${result.item.sku_id}: ${result.movement.quantity_before} -> ${result.movement.quantity_after} units.`,
      });
      setMovement(null);
    },
    onError: (error: Error) => toast.error('Inventory action failed', { description: error.message }),
  });

  const importMutation = useMutation({
    mutationFn: () => importRetailInventory(parsed.rows, importMode),
    onSuccess: (result) => {
      if (!search.trim()) {
        queryClient.setQueryData<RetailInventoryResponse>(['retail-inventory', tenantScope, search], {
          items: result.items,
          summary: result.summary,
        });
      }
      queryClient.invalidateQueries({ queryKey: ['retail-inventory'] });
      queryClient.invalidateQueries({ queryKey: ['retail-db-status'] });
      queryClient.invalidateQueries({ queryKey: ['report-live'] });
      queryClient.invalidateQueries({ queryKey: ['report'] });
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
      supplier_name: item.supplier_name || '',
      notes: item.notes || '',
    });
    setDialogOpen(true);
  };

  const openMovement = (item: RetailInventoryItem, movementType: RetailInventoryMovementType) => {
    setMovement({
      item,
      movement_type: movementType,
      quantity: '1',
      unit_price_usd: String(item.retail_price_usd ?? ''),
      unit_cost_usd: String(item.cost_price_usd ?? ''),
      discount_pct: '0',
      channel: 'manual',
      reference_id: '',
      notes: movementType === 'sale' ? 'Manual sale from inventory screen' : '',
    });
  };

  const readCsvFile = async (file: File) => {
    setCsvText(await file.text());
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="DB status" icon={Database} value={status.data?.connected ? 'Online' : 'Offline'} hint={status.data?.store || 'MAIN'} />
        <KpiCard label="Managed SKUs" icon={Boxes} value={fmtNum(summary?.total_skus || 0)} hint={`${fmtNum(summary?.total_units || 0)} units`} />
        <KpiCard label="Cost value" icon={Boxes} value={fmtUSD(summary?.inventory_value_at_cost_usd || 0, { compact: true })} hint="live PostgreSQL" />
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
              <Button size="sm" onClick={openCreate} disabled={!canWrite} title={canWrite ? 'Add SKU' : 'Database must be online before adding inventory'}>
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
                  <th className="px-4 py-3 text-left">Details</th>
                  <th className="px-4 py-3 text-right">Stock</th>
                  <th className="px-4 py-3 text-right">Retail</th>
                  <th className="px-4 py-3 text-right">Cost</th>
                  <th className="px-4 py-3 text-right">Margin</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {inventory.isLoading && (
                  <tr><td colSpan={10} className="px-4 py-8 text-center text-muted-foreground">Loading inventory...</td></tr>
                )}
                {!inventory.isLoading && items.length === 0 && (
                  <tr><td colSpan={10} className="px-4 py-8 text-center text-muted-foreground">No inventory rows yet.</td></tr>
                )}
                {items.map((item) => {
                  const details = inventoryDetailPairs(item);
                  return (
                    <tr key={item.sku_id} className="border-t border-border hover:bg-accent/40">
                      <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground">{item.sku_id}</td>
                      <td className="px-4 py-2.5 min-w-[240px]">
                        <div className="font-medium">{item.product_name}</div>
                        <div className="text-[11px] text-muted-foreground font-mono">{item.style_code || item.barcode || 'no identifier'}</div>
                        {item.notes && <div className="mt-1 max-w-[280px] truncate text-[11px] text-muted-foreground">{item.notes}</div>}
                      </td>
                      <td className="px-4 py-2.5">{item.brand}</td>
                      <td className="px-4 py-2.5">{item.category}</td>
                      <td className="px-4 py-2.5 min-w-[220px]">
                        {details.length ? (
                          <div className="flex flex-wrap gap-1">
                            {details.map(([label, value]) => (
                              <span key={label} className="rounded-full bg-secondary/70 px-2 py-0.5 text-[10.5px] text-secondary-foreground">
                                <span className="text-muted-foreground">{label}:</span> {value}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-[11px] text-muted-foreground">Not set</span>
                        )}
                      </td>
                      <td className={cn('px-4 py-2.5 text-right font-mono', item.needs_reorder ? 'text-decision-markdown' : '')}>{fmtNum(item.current_stock)}</td>
                      <td className="px-4 py-2.5 text-right font-mono">{fmtUSD(item.retail_price_usd)}</td>
                      <td className="px-4 py-2.5 text-right font-mono">{fmtUSD(item.cost_price_usd)}</td>
                      <td className={cn('px-4 py-2.5 text-right font-mono', item.margin_pct < 35 ? 'text-decision-clear' : item.margin_pct >= 45 ? 'text-decision-promote' : '')}>{fmtPct(item.margin_pct, 0)}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="outline"
                            title="Record sale"
                            disabled={!canWrite || item.current_stock <= 0}
                            onClick={() => openMovement(item, 'sale')}
                          >
                            <ShoppingCart className="h-3.5 w-3.5" /> Sold
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            title="Add received stock"
                            disabled={!canWrite}
                            onClick={() => openMovement(item, 'purchase_receipt')}
                          >
                            <PackagePlus className="h-3.5 w-3.5" /> Restock
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            title="Remove, damage, or adjust stock"
                            disabled={!canWrite}
                            onClick={() => openMovement(item, 'adjustment_out')}
                          >
                            <SlidersHorizontal className="h-3.5 w-3.5" /> Remove
                          </Button>
                          <Button size="icon" variant="ghost" title="Edit SKU" onClick={() => openEdit(item)}>
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button size="icon" variant="ghost" title="Archive SKU" disabled={!canWrite} onClick={() => archiveMutation.mutate(item.sku_id)}>
                            <Archive className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>

        <Section title="Inventory CSV import" subtitle="Upload or paste rows directly into the PostgreSQL inventory DB" bodyClassName="space-y-4">
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
              disabled={parsed.rows.length === 0 || parsed.errors.length > 0 || importMutation.isPending || !canWrite}
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
              {parsed.rows.length} valid rows ready to save to DB. Required headers: sku_id, product_name, brand, category, current_stock, retail_price_usd, cost_price_usd.
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
        canWrite={canWrite}
        onClose={() => setDialogOpen(false)}
        onSave={() => saveMutation.mutate()}
      />
      <InventoryMovementDialog
        movement={movement}
        setMovement={setMovement}
        saving={movementMutation.isPending}
        canWrite={canWrite}
        onClose={() => setMovement(null)}
        onSave={() => movementMutation.mutate()}
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
  canWrite,
  onClose,
  onSave,
}: {
  open: boolean;
  editing: RetailInventoryItem | null;
  form: InventoryFormState;
  setForm: (value: InventoryFormState) => void;
  saving: boolean;
  canWrite: boolean;
  onClose: () => void;
  onSave: () => void;
}) {
  const update = (key: keyof InventoryFormState, value: string) => setForm({ ...form, [key]: value });
  const validationErrors = validateInventoryForm(form);
  const canSave = validationErrors.length === 0;

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
        {validationErrors.length > 0 && (
          <div className="rounded-md border border-decision-markdown/30 bg-decision-markdown-bg p-3 text-[12px] text-decision-markdown">
            {validationErrors.map((error) => <div key={error}>{error}</div>)}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!canSave || saving || !canWrite} onClick={onSave}>
            <Save className="h-3.5 w-3.5" /> Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function InventoryMovementDialog({
  movement,
  setMovement,
  saving,
  canWrite,
  onClose,
  onSave,
}: {
  movement: InventoryMovementFormState | null;
  setMovement: (value: InventoryMovementFormState | null) => void;
  saving: boolean;
  canWrite: boolean;
  onClose: () => void;
  onSave: () => void;
}) {
  const update = (key: keyof InventoryMovementFormState, value: string) => {
    if (!movement) return;
    setMovement({ ...movement, [key]: value });
  };
  const errors = movement ? validateMovementForm(movement) : [];
  const projectedStock = movement ? projectedMovementStock(movement) : 0;
  const isSale = movement?.movement_type === 'sale';

  return (
    <Dialog open={!!movement} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-xl">
        {movement && (
          <>
            <DialogHeader>
              <DialogTitle>{MOVEMENT_LABELS[movement.movement_type]} stock</DialogTitle>
            </DialogHeader>
            <div className="rounded-md border border-border bg-surface-sunken p-3">
              <div className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground">{movement.item.sku_id}</div>
              <div className="mt-0.5 font-semibold">{movement.item.product_name}</div>
              <div className="mt-2 grid grid-cols-3 gap-3 text-[12px]">
                <div>
                  <div className="text-muted-foreground">Current</div>
                  <div className="font-mono text-[16px]">{fmtNum(movement.item.current_stock)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Change</div>
                  <div className={cn('font-mono text-[16px]', NEGATIVE_MOVEMENTS.has(movement.movement_type) ? 'text-decision-clear' : 'text-decision-promote')}>
                    {NEGATIVE_MOVEMENTS.has(movement.movement_type) ? '-' : '+'}{readNumber(movement.quantity)}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">After</div>
                  <div className={cn('font-mono text-[16px]', projectedStock < 0 ? 'text-decision-clear' : '')}>{fmtNum(projectedStock)}</div>
                </div>
              </div>
            </div>

            <div className="grid md:grid-cols-2 gap-3">
              <Field label="Action">
                <select
                  value={movement.movement_type}
                  onChange={(e) => update('movement_type', e.target.value)}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                >
                  {(['sale', 'purchase_receipt', 'return', 'adjustment_in', 'adjustment_out', 'damaged'] as RetailInventoryMovementType[]).map((type) => (
                    <option key={type} value={type}>{MOVEMENT_LABELS[type]}</option>
                  ))}
                </select>
              </Field>
              <Field label="Quantity">
                <Input inputMode="numeric" value={movement.quantity} onChange={(e) => update('quantity', integerText(e.target.value))} />
              </Field>
              {isSale && (
                <>
                  <Field label="Sold price">
                    <Input inputMode="decimal" value={movement.unit_price_usd} onChange={(e) => update('unit_price_usd', decimalText(e.target.value))} />
                  </Field>
                  <Field label="Discount %">
                    <Input inputMode="decimal" value={movement.discount_pct} onChange={(e) => update('discount_pct', decimalText(e.target.value))} />
                  </Field>
                  <Field label="Channel">
                    <Input value={movement.channel} onChange={(e) => update('channel', e.target.value)} />
                  </Field>
                </>
              )}
              {!isSale && (
                <Field label="Unit cost">
                  <Input inputMode="decimal" value={movement.unit_cost_usd} onChange={(e) => update('unit_cost_usd', decimalText(e.target.value))} />
                </Field>
              )}
              <Field label="Reference">
                <Input value={movement.reference_id} onChange={(e) => update('reference_id', e.target.value)} placeholder={isSale ? 'receipt id' : 'invoice / reason'} />
              </Field>
              <Field label="Notes" className="md:col-span-2">
                <Textarea rows={3} value={movement.notes} onChange={(e) => update('notes', e.target.value)} />
              </Field>
            </div>

            {errors.length > 0 && (
              <div className="rounded-md border border-decision-markdown/30 bg-decision-markdown-bg p-3 text-[12px] text-decision-markdown">
                {errors.map((error) => <div key={error}>{error}</div>)}
              </div>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button disabled={errors.length > 0 || saving || !canWrite} onClick={onSave}>
                <Save className="h-3.5 w-3.5" /> Save action
              </Button>
            </DialogFooter>
          </>
        )}
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
  const knownDosSkus = r.inventory.sku_analysis.filter(s => !isUnknownDos(s.days_of_supply));
  const unknownDosCount = r.inventory.sku_analysis.length - knownDosSkus.length;

  const dosBands = [
    { band: '<= 21', count: knownDosSkus.filter(s => s.days_of_supply <= 21).length, color: 'hsl(var(--decision-clear))' },
    { band: '22-44', count: knownDosSkus.filter(s => s.days_of_supply > 21 && s.days_of_supply < 45).length, color: 'hsl(var(--decision-markdown))' },
    { band: '45-90', count: knownDosSkus.filter(s => s.days_of_supply >= 45 && s.days_of_supply <= 90).length, color: 'hsl(var(--decision-promote))' },
    { band: '91-180', count: knownDosSkus.filter(s => s.days_of_supply > 90 && s.days_of_supply <= 180).length, color: 'hsl(var(--decision-markdown))' },
    { band: '> 180', count: knownDosSkus.filter(s => s.days_of_supply > 180).length, color: 'hsl(var(--decision-clear))' },
    { band: 'No sales', count: unknownDosCount, color: 'hsl(var(--muted-foreground))' },
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
        <Section title="Days of Supply Distribution" subtitle={unknownDosCount > 0 ? `${unknownDosCount} SKUs need sales history` : 'Active dashboard report'}>
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
                  <td className="px-4 py-2.5 text-right font-mono">{fmtDos(v.median_dos)}</td>
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
                <div className={cn('text-[12px] font-mono font-semibold', s.days_of_supply <= 21 ? 'text-decision-clear' : 'text-decision-markdown')}>{fmtDos(s.days_of_supply)}</div>
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

function upsertInventoryCache(
  current: RetailInventoryResponse | undefined,
  savedItem: RetailInventoryItem,
  search: string,
): RetailInventoryResponse {
  const currentItems = current?.items ?? [];
  const exists = currentItems.some((item) => item.sku_id === savedItem.sku_id);
  const nextItems = exists
    ? currentItems.map((item) => (item.sku_id === savedItem.sku_id ? savedItem : item))
    : inventoryMatchesSearch(savedItem, search)
      ? [savedItem, ...currentItems]
      : currentItems;

  return {
    items: nextItems,
    summary: summarizeInventoryItems(nextItems),
  };
}

function inventoryMatchesSearch(item: RetailInventoryItem, search: string) {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;
  return [item.sku_id, item.product_name, item.brand, item.style_code]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(needle));
}

function summarizeInventoryItems(items: RetailInventoryItem[]) {
  const totalUnits = items.reduce((sum, item) => sum + item.current_stock, 0);
  const inventoryValueAtCost = items.reduce((sum, item) => sum + item.stock_value_usd, 0);
  const inventoryValueAtRetail = items.reduce(
    (sum, item) => sum + item.current_stock * item.retail_price_usd,
    0,
  );
  const categories = Array.from(new Set(items.map((item) => item.category).filter(Boolean))).sort();

  return {
    total_skus: items.length,
    total_units: totalUnits,
    inventory_value_at_cost_usd: roundMoney(inventoryValueAtCost),
    inventory_value_at_retail_usd: roundMoney(inventoryValueAtRetail),
    reorder_count: items.filter((item) => item.needs_reorder).length,
    categories,
  };
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}

function inventoryDetailPairs(item: RetailInventoryItem): Array<[string, string]> {
  return [
    ['Gender', item.gender_target],
    ['Season', item.season],
    ['Color', item.color],
    ['Size', item.size],
    ['Supplier', item.supplier_name],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]));
}

function validateInventoryForm(form: InventoryFormState) {
  const errors: string[] = [];
  const retailPrice = parseRequiredNumber(form.retail_price_usd);
  const costPrice = parseRequiredNumber(form.cost_price_usd);
  if (!form.sku_id.trim()) errors.push('SKU is required.');
  if (!form.product_name.trim()) errors.push('Product name is required.');
  if (!form.brand.trim()) errors.push('Brand is required.');
  if (!form.category.trim()) errors.push('Category is required.');
  if (parseRequiredNumber(form.current_stock) === null) errors.push('Stock is required and must be a valid number.');
  if (retailPrice === null || retailPrice <= 0) errors.push('Retail price is required and must be greater than 0.');
  if (costPrice === null || costPrice <= 0) errors.push('Cost price is required and must be greater than 0.');
  if (retailPrice !== null && costPrice !== null && costPrice >= retailPrice) errors.push('Cost price must be lower than retail price.');
  return errors;
}

function validateMovementForm(form: InventoryMovementFormState) {
  const errors: string[] = [];
  const quantity = readNumber(form.quantity);
  const unitPrice = readNumber(form.unit_price_usd);
  const unitCost = readNumber(form.unit_cost_usd);
  const discountPct = readNumber(form.discount_pct);
  if (!Number.isInteger(quantity) || quantity <= 0) errors.push('Quantity must be a whole number greater than 0.');
  if (NEGATIVE_MOVEMENTS.has(form.movement_type) && quantity > form.item.current_stock) {
    errors.push(`Quantity cannot exceed current stock (${form.item.current_stock}).`);
  }
  if (form.movement_type === 'sale' && unitPrice <= 0) errors.push('Sold price must be greater than 0.');
  if (form.movement_type !== 'sale' && unitCost < 0) errors.push('Unit cost cannot be negative.');
  if (discountPct < 0 || discountPct > 100) errors.push('Discount must be between 0 and 100.');
  return errors;
}

function projectedMovementStock(form: InventoryMovementFormState) {
  const quantity = readNumber(form.quantity);
  return form.item.current_stock + (NEGATIVE_MOVEMENTS.has(form.movement_type) ? -quantity : quantity);
}

function normalizedMovement(form: InventoryMovementFormState): RetailInventoryMovementInput {
  return {
    movement_type: form.movement_type,
    quantity: readNumber(form.quantity),
    unit_price_usd: form.movement_type === 'sale' ? readNumber(form.unit_price_usd) : null,
    unit_cost_usd: form.movement_type !== 'sale' ? readNumber(form.unit_cost_usd) : form.item.cost_price_usd,
    discount_pct: readNumber(form.discount_pct),
    channel: cleanNullable(form.channel) || 'manual',
    reference_id: cleanNullable(form.reference_id),
    notes: cleanNullable(form.notes),
  };
}

function parseRequiredNumber(value: string) {
  if (!value.trim()) return null;
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) ? parsed : null;
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

function syncNewSkuDecision(item: RetailInventoryItem, tenantScope: string) {
  toast.info('Syncing system decision for new SKU', {
    description: `${item.sku_id} is being sent through EEP -> IE1 -> IE2.`,
  });
  recommend(toRecommendationRequest(item))
    .then((result) => {
      writeSystemDecisionEntry(tenantScope, item.sku_id, {
        status: 'live',
        result: { ...result, sku_id: result.sku_id ?? item.sku_id },
        checkedAt: Date.now(),
        trigger: 'new_sku',
      });
      toast.success('System decision synced for new SKU', {
        description: `${item.sku_id}: ${result.recommendation}`,
      });
    })
    .catch((error: Error) => {
      writeSystemDecisionEntry(tenantScope, item.sku_id, {
        status: 'error',
        error: error.message,
        checkedAt: Date.now(),
        trigger: 'new_sku',
      });
      toast.error('System decision failed for new SKU', {
        description: `${item.sku_id}: ${error.message}`,
      });
    });
}

function toRecommendationRequest(item: RetailInventoryItem): IE2Request {
  return {
    sku_id: item.sku_id,
    product_name: item.product_name,
    brand: item.brand,
    category: item.category,
    retail_price_usd: item.retail_price_usd,
    cost_price_usd: item.cost_price_usd,
    current_stock: item.current_stock,
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
