import type { RetailInventoryInput } from '@/types/domain';

export interface InventoryCsvParseResult {
  rows: RetailInventoryInput[];
  errors: string[];
}

const FIELD_ALIASES: Record<keyof RetailInventoryInput, string[]> = {
  sku_id: ['sku_id', 'sku', 'item_code', 'variant_sku'],
  product_name: ['product_name', 'name', 'title', 'product'],
  brand: ['brand', 'brand_name'],
  category: ['category', 'system_category', 'department'],
  current_stock: ['current_stock', 'stock', 'quantity', 'qty', 'on_hand'],
  retail_price_usd: ['retail_price_usd', 'retail_price', 'price', 'selling_price'],
  cost_price_usd: ['cost_price_usd', 'cost_price', 'cost'],
  barcode: ['barcode', 'ean', 'upc'],
  style_code: ['style_code', 'article_code', 'model_code'],
  color: ['color', 'colour'],
  size: ['size'],
  gender_target: ['gender_target', 'gender'],
  season: ['season'],
  reorder_point: ['reorder_point', 'min_stock', 'minimum_stock'],
  reorder_quantity: ['reorder_quantity', 'reorder_qty'],
  supplier_name: ['supplier_name', 'supplier'],
  notes: ['notes', 'note'],
};

export function parseInventoryCsv(text: string): InventoryCsvParseResult {
  const records = parseCsv(text).filter((row) => row.some((cell) => cell.trim()));
  if (records.length < 2) return { rows: [], errors: ['CSV must include a header row and at least one item.'] };

  const headers = records[0].map(normalizeHeader);
  const rows: RetailInventoryInput[] = [];
  const errors: string[] = [];

  records.slice(1).forEach((record, index) => {
    const source: Record<string, string> = {};
    headers.forEach((header, i) => {
      source[header] = record[i]?.trim() ?? '';
    });

    const rowNumber = index + 2;
    const item: RetailInventoryInput = {
      sku_id: readText(source, 'sku_id'),
      product_name: readText(source, 'product_name'),
      brand: readText(source, 'brand') || 'Unknown',
      category: readText(source, 'category') || 'uncategorized',
      current_stock: readNumber(source, 'current_stock'),
      retail_price_usd: readNumber(source, 'retail_price_usd'),
      cost_price_usd: readNumber(source, 'cost_price_usd'),
      barcode: emptyToNull(readText(source, 'barcode')),
      style_code: emptyToNull(readText(source, 'style_code')),
      color: emptyToNull(readText(source, 'color')),
      size: emptyToNull(readText(source, 'size')),
      gender_target: emptyToNull(readText(source, 'gender_target')),
      season: emptyToNull(readText(source, 'season')),
      reorder_point: readNumber(source, 'reorder_point'),
      reorder_quantity: readNumber(source, 'reorder_quantity'),
      supplier_name: emptyToNull(readText(source, 'supplier_name')),
      notes: emptyToNull(readText(source, 'notes')),
    };

    if (!item.sku_id) errors.push(`Row ${rowNumber}: missing sku_id.`);
    if (!item.product_name) errors.push(`Row ${rowNumber}: missing product_name.`);
    if (item.current_stock < 0) errors.push(`Row ${rowNumber}: stock cannot be negative.`);
    if (item.retail_price_usd < 0 || item.cost_price_usd < 0) errors.push(`Row ${rowNumber}: prices cannot be negative.`);
    rows.push(item);
  });

  return { rows: errors.length ? [] : rows, errors };
}

function readText(source: Record<string, string>, field: keyof RetailInventoryInput): string {
  const alias = FIELD_ALIASES[field].find((key) => Object.prototype.hasOwnProperty.call(source, key));
  return alias ? source[alias] : '';
}

function readNumber(source: Record<string, string>, field: keyof RetailInventoryInput): number {
  const value = readText(source, field).replace(/[$,\s]/g, '');
  if (!value) return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function emptyToNull(value: string): string | null {
  return value.trim() ? value.trim() : null;
}

function normalizeHeader(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, '_');
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (char === '"' && quoted && next === '"') {
      cell += '"';
      i += 1;
      continue;
    }
    if (char === '"') {
      quoted = !quoted;
      continue;
    }
    if (char === ',' && !quoted) {
      row.push(cell);
      cell = '';
      continue;
    }
    if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && next === '\n') i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
      continue;
    }
    cell += char;
  }

  row.push(cell);
  rows.push(row);
  return rows;
}
