import { useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { Upload, FileSpreadsheet, Check, Boxes } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import type { Decision } from '@/types/domain';

const SAMPLE_ROWS = [
  { sku_id: 'RR-90021', product_name: 'Adidas Predator Elite FG', brand: 'Adidas', category: 'Football Boots', stock: 12, price: 245 },
  { sku_id: 'RR-90022', product_name: 'Nike Pegasus 41', brand: 'Nike', category: 'Running Shoes', stock: 48, price: 138 },
  { sku_id: 'RR-90023', product_name: 'Puma RS-X3', brand: 'Puma', category: 'Lifestyle Sneakers', stock: 130, price: 110 },
  { sku_id: 'RR-90024', product_name: 'Asics Gel-Kayano 31', brand: 'Asics', category: 'Running Shoes', stock: 7, price: 175 },
  { sku_id: 'RR-90025', product_name: 'New Balance 990v6', brand: 'New Balance', category: 'Lifestyle Sneakers', stock: 88, price: 198 },
];

const DECISIONS: Decision[] = ['MARKDOWN', 'PROMOTE', 'HOLD', 'PROMOTE', 'MARKDOWN'];

export default function UploadBatch() {
  const [stage, setStage] = useState<'idle' | 'preview' | 'mapping' | 'results'>('idle');
  const [filename, setFilename] = useState('');
  const ref = useRef<HTMLInputElement>(null);

  const onFile = (f: File) => {
    setFilename(f.name);
    setStage('preview');
    toast.success('CSV parsed', { description: `${SAMPLE_ROWS.length} rows · 6 columns detected.` });
  };

  return (
    <>
      <TopBar title="Upload & Batch Processing" subtitle="Run IE2 recommendations across a CSV of SKUs" />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <Section
          title="Need to add or update real inventory?"
          subtitle="Use Inventory & Stock. This Upload & Batch page is only for recommendation scoring."
          action={
            <Link
              to="/inventory"
              className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-[12.5px] font-semibold text-primary-foreground"
            >
              <Boxes className="h-3.5 w-3.5" /> Open Inventory & Stock
            </Link>
          }
        >
          <p className="text-[13px] text-muted-foreground">
            The inventory screen has the PostgreSQL-backed table, an <span className="font-semibold text-foreground">Add SKU</span> button,
            edit/archive actions, CSV upload, paste import, and full inventory replace mode.
          </p>
        </Section>

        {stage === 'idle' && (
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0]); }}
            onClick={() => ref.current?.click()}
            className="rounded-2xl border-2 border-dashed border-border bg-surface-raised p-16 text-center cursor-pointer hover:border-primary/40 hover:bg-accent/30 transition"
          >
            <div className="mx-auto h-14 w-14 rounded-xl bg-gradient-data flex items-center justify-center shadow-glow">
              <Upload className="h-6 w-6 text-primary-foreground" />
            </div>
            <h3 className="font-display text-[20px] font-semibold mt-4">Drop your SKU CSV here</h3>
            <p className="text-[13px] text-muted-foreground mt-2 max-w-md mx-auto">
              Required columns: <span className="font-mono text-foreground">sku_id, product_name, brand, category, retail_price_usd, cost_price_usd, current_stock</span>
            </p>
            <button className="mt-5 inline-flex items-center gap-2 h-10 px-5 rounded-md bg-foreground text-background text-[13px] font-semibold">
              Choose file
            </button>
            <input type="file" ref={ref} accept=".csv" className="hidden" onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
          </div>
        )}

        {stage !== 'idle' && (
          <Section
            title={filename}
            subtitle={`${SAMPLE_ROWS.length} rows · 6 columns · ${stage}`}
            action={
              <div className="flex items-center gap-2">
                {stage === 'preview' && <button onClick={() => setStage('mapping')} className="h-9 px-4 rounded-md bg-foreground text-background text-[12.5px] font-semibold">Continue → Mapping</button>}
                {stage === 'mapping' && <button onClick={() => { setStage('results'); toast.success('Batch complete', { description: '5 SKUs scored.' }); }} className="h-9 px-4 rounded-md bg-decision-promote text-white text-[12.5px] font-semibold">Run batch recommendation</button>}
                {stage === 'results' && <button onClick={() => setStage('idle')} className="h-9 px-4 rounded-md border border-border text-[12.5px] font-semibold">Upload another</button>}
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
                    <th className="px-4 py-3 text-right">Price</th>
                    <th className="px-4 py-3 text-center">Validation</th>
                    {stage === 'results' && <th className="px-4 py-3 text-left">Decision</th>}
                  </tr>
                </thead>
                <tbody>
                  {SAMPLE_ROWS.map((r, i) => (
                    <tr key={r.sku_id} className="border-t border-border">
                      <td className="px-4 py-2 font-mono">{r.sku_id}</td>
                      <td className="px-4 py-2 font-medium">{r.product_name}</td>
                      <td className="px-4 py-2 text-muted-foreground">{r.brand}</td>
                      <td className="px-4 py-2 text-muted-foreground">{r.category}</td>
                      <td className="px-4 py-2 text-right font-mono">{r.stock}</td>
                      <td className="px-4 py-2 text-right font-mono">${r.price}</td>
                      <td className="px-4 py-2 text-center"><Check className="h-4 w-4 text-decision-promote inline" /></td>
                      {stage === 'results' && <td className="px-4 py-2"><DecisionBadge decision={DECISIONS[i]} size="sm" /></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {stage === 'mapping' && (
              <div className="p-5 border-t border-border bg-accent/30">
                <div className="text-[12px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">Column mapping</div>
                <div className="grid md:grid-cols-3 gap-2 text-[12px]">
                  {['sku_id', 'product_name', 'brand', 'category', 'current_stock', 'retail_price_usd'].map(c => (
                    <div key={c} className="flex items-center gap-2 px-3 py-2 rounded-md bg-card border border-border">
                      <FileSpreadsheet className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-mono">{c}</span>
                      <span className="text-muted-foreground ml-auto">→ auto</span>
                      <Check className="h-3.5 w-3.5 text-decision-promote" />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Section>
        )}

        <Section title="Adapter ready for /upload/csv" subtitle="EEP service (planned · port 8000)">
          <p className="text-[13px] text-muted-foreground">
            When the EEP service exposes <code className="font-mono text-foreground">POST /upload/csv</code>, this screen will stream rows server-side.
            Today, parsing and scoring run client-side via the IE2 mock adapter.
          </p>
        </Section>
      </main>
    </>
  );
}
