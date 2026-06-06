import { useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { Upload, FileSpreadsheet, Check, Boxes, AlertTriangle, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import { fmtPct } from '@/lib/format';
import { recommendBatch } from '@/lib/adapter';
import type { IE2Request, IE2Result } from '@/types/domain';

type BatchRow = IE2Request & {
  row_number: number;
};

export default function UploadBatch() {
  const [stage, setStage] = useState<'idle' | 'preview' | 'mapping' | 'results'>('idle');
  const [filename, setFilename] = useState('');
  const [rows, setRows] = useState<BatchRow[]>([]);
  const [results, setResults] = useState<IE2Result[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const ref = useRef<HTMLInputElement>(null);

  const resultBySku = useMemo(() => new Map(results.map((result) => [result.sku_id, result])), [results]);

  const onFile = async (f: File) => {
    try {
      const parsed = parseCsv(await f.text());
      setFilename(f.name);
      setRows(parsed);
      setResults([]);
      setStage('preview');
      toast.success('CSV parsed', { description: `${parsed.length} rows ready for live prediction.` });
    } catch (error: any) {
      toast.error('CSV parse failed', { description: error?.message || 'Please check the file format.' });
    }
  };

  const runBatch = async () => {
    if (!rows.length) return;
    setIsRunning(true);
    try {
      const payload = rows.map(({ row_number: _rowNumber, ...row }) => row);
      const scored = await recommendBatch(payload);
      setResults(scored);
      setStage('results');
      const errors = scored.filter((result) => result.error).length;
      toast.success('Batch complete', {
        description: errors ? `${scored.length - errors} scored, ${errors} need review.` : `${scored.length} SKUs scored.`,
      });
    } catch (error: any) {
      toast.error('Batch failed', { description: error?.message || 'EEP batch recommendation failed.' });
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <>
      <TopBar title="Upload & Batch Processing" subtitle="Run live system recommendations across a CSV of SKUs" />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <Section
          title="Need to add or update real inventory?"
          subtitle="Use Inventory & Stock. This page scores recommendation decisions through EEP."
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
            In EEP live mode, <span className="font-mono text-foreground">sku_id</span> is enough for RDS-backed scoring.
            Extra columns such as product, price, cost, and stock are accepted for diagnostics and non-authenticated development mode.
          </p>
        </Section>

        {stage === 'idle' && (
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files[0]) void onFile(e.dataTransfer.files[0]); }}
            onClick={() => ref.current?.click()}
            className="rounded-2xl border-2 border-dashed border-border bg-surface-raised p-16 text-center cursor-pointer hover:border-primary/40 hover:bg-accent/30 transition"
          >
            <div className="mx-auto h-14 w-14 rounded-xl bg-gradient-data flex items-center justify-center shadow-glow">
              <Upload className="h-6 w-6 text-primary-foreground" />
            </div>
            <h3 className="font-display text-[20px] font-semibold mt-4">Drop your SKU CSV here</h3>
            <p className="text-[13px] text-muted-foreground mt-2 max-w-md mx-auto">
              Minimum column: <span className="font-mono text-foreground">sku_id</span>. Optional columns:
              <span className="font-mono text-foreground"> product_name, brand, category, retail_price_usd, cost_price_usd, current_stock</span>.
            </p>
            <button className="mt-5 inline-flex items-center gap-2 h-10 px-5 rounded-md bg-foreground text-background text-[13px] font-semibold">
              Choose file
            </button>
            <input type="file" ref={ref} accept=".csv" className="hidden" onChange={(e) => e.target.files?.[0] && void onFile(e.target.files[0])} />
          </div>
        )}

        {stage !== 'idle' && (
          <Section
            title={filename}
            subtitle={`${rows.length} rows · ${stage}`}
            action={
              <div className="flex items-center gap-2">
                {stage === 'preview' && <button onClick={() => setStage('mapping')} className="h-9 px-4 rounded-md bg-foreground text-background text-[12.5px] font-semibold">Continue to mapping</button>}
                {stage === 'mapping' && (
                  <button
                    onClick={() => void runBatch()}
                    disabled={isRunning}
                    className="h-9 px-4 rounded-md bg-decision-promote text-white text-[12.5px] font-semibold inline-flex items-center gap-2 disabled:opacity-60"
                  >
                    {isRunning && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    Run live recommendations
                  </button>
                )}
                {stage === 'results' && <button onClick={() => { setStage('idle'); setRows([]); setResults([]); }} className="h-9 px-4 rounded-md border border-border text-[12.5px] font-semibold">Upload another</button>}
              </div>
            }
            bodyClassName="p-0"
          >
            <div className="overflow-x-auto scrollbar-thin">
              <table className="w-full text-[12.5px]">
                <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left">Row</th>
                    <th className="px-4 py-3 text-left">SKU</th>
                    <th className="px-4 py-3 text-left">Product</th>
                    <th className="px-4 py-3 text-left">Brand</th>
                    <th className="px-4 py-3 text-right">Stock</th>
                    <th className="px-4 py-3 text-right">Price</th>
                    <th className="px-4 py-3 text-center">Validation</th>
                    {stage === 'results' && <th className="px-4 py-3 text-left">System Decision</th>}
                    {stage === 'results' && <th className="px-4 py-3 text-left">Confidence</th>}
                    {stage === 'results' && <th className="px-4 py-3 text-left">Model</th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const result = resultBySku.get(row.sku_id);
                    return (
                      <tr key={`${row.row_number}-${row.sku_id}`} className="border-t border-border">
                        <td className="px-4 py-2 text-muted-foreground font-mono">{row.row_number}</td>
                        <td className="px-4 py-2 font-mono">{row.sku_id}</td>
                        <td className="px-4 py-2 font-medium">{row.product_name || '-'}</td>
                        <td className="px-4 py-2 text-muted-foreground">{row.brand || '-'}</td>
                        <td className="px-4 py-2 text-right font-mono">{row.current_stock ?? '-'}</td>
                        <td className="px-4 py-2 text-right font-mono">{row.retail_price_usd != null ? `$${row.retail_price_usd}` : '-'}</td>
                        <td className="px-4 py-2 text-center">
                          {result?.error ? <AlertTriangle className="h-4 w-4 text-decision-clear inline" /> : <Check className="h-4 w-4 text-decision-promote inline" />}
                        </td>
                        {stage === 'results' && (
                          <td className="px-4 py-2">
                            {result ? <DecisionBadge decision={result.recommendation} size="sm" /> : '-'}
                            {result?.error && <div className="text-[11px] text-decision-clear mt-1 max-w-xs">{result.error}</div>}
                          </td>
                        )}
                        {stage === 'results' && <td className="px-4 py-2 font-mono">{result ? fmtPct(result.confidence * 100, 0) : '-'}</td>}
                        {stage === 'results' && <td className="px-4 py-2 text-[11px] text-muted-foreground max-w-[220px] truncate">{result?.model_version || '-'}</td>}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {stage === 'mapping' && (
              <div className="p-5 border-t border-border bg-accent/30">
                <div className="text-[12px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">Column mapping</div>
                <div className="grid md:grid-cols-3 gap-2 text-[12px]">
                  {['sku_id', 'product_name', 'brand', 'category', 'current_stock', 'retail_price_usd'].map((column) => (
                    <div key={column} className="flex items-center gap-2 px-3 py-2 rounded-md bg-card border border-border">
                      <FileSpreadsheet className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-mono">{column}</span>
                      <span className="text-muted-foreground ml-auto">auto</span>
                      <Check className="h-3.5 w-3.5 text-decision-promote" />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Section>
        )}

        <Section title="Live prediction path" subtitle="Frontend -> EEP /recommend/batch -> IE2 system decision">
          <p className="text-[13px] text-muted-foreground">
            EEP loads RDS inventory and competitor context by SKU, then applies hard rules, the active CatBoost model,
            soft nudges, and the low-confidence HOLD fallback before returning the final recommendation.
          </p>
        </Section>
      </main>
    </>
  );
}

function parseCsv(text: string): BatchRow[] {
  const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (lines.length < 2) {
    throw new Error('CSV must include a header row and at least one SKU row.');
  }

  const headers = splitCsvLine(lines[0]).map((header) => header.trim());
  const skuIndex = headers.findIndex((header) => header.toLowerCase() === 'sku_id');
  if (skuIndex < 0) {
    throw new Error('CSV must include a sku_id column.');
  }

  return lines.slice(1).map((line, index) => {
    const values = splitCsvLine(line);
    const row = Object.fromEntries(headers.map((header, headerIndex) => [header, values[headerIndex]?.trim() ?? '']));
    const skuId = String(row.sku_id || '').trim();
    if (!skuId) {
      throw new Error(`Row ${index + 2} is missing sku_id.`);
    }

    return compactRequest({
      row_number: index + 2,
      sku_id: skuId,
      product_name: stringValue(row.product_name),
      brand: stringValue(row.brand),
      category: stringValue(row.category),
      retail_price_usd: numberValue(row.retail_price_usd ?? row.price),
      cost_price_usd: numberValue(row.cost_price_usd ?? row.cost),
      current_stock: intValue(row.current_stock ?? row.stock),
      initial_stock: intValue(row.initial_stock),
      days_since_launch: intValue(row.days_since_launch),
      days_since_last_discount: intValue(row.days_since_last_discount),
      days_at_current_price: intValue(row.days_at_current_price),
    });
  });
}

function splitCsvLine(line: string): string[] {
  const cells: string[] = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    const next = line[i + 1];

    if (char === '"' && inQuotes && next === '"') {
      current += '"';
      i += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === ',' && !inQuotes) {
      cells.push(current);
      current = '';
    } else {
      current += char;
    }
  }

  cells.push(current);
  return cells;
}

function compactRequest(row: BatchRow): BatchRow {
  return Object.fromEntries(Object.entries(row).filter(([, value]) => value !== undefined && value !== '')) as BatchRow;
}

function stringValue(value: unknown): string | undefined {
  const text = String(value ?? '').trim();
  return text || undefined;
}

function numberValue(value: unknown): number | undefined {
  const text = String(value ?? '').trim();
  if (!text) return undefined;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function intValue(value: unknown): number | undefined {
  const parsed = numberValue(value);
  return parsed == null ? undefined : Math.round(parsed);
}
