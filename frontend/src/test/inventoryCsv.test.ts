import { describe, expect, it } from 'vitest';
import { parseInventoryCsv } from '@/lib/inventoryCsv';

describe('parseInventoryCsv', () => {
  it('parses all CSV rows into bulk inventory payload rows', () => {
    const csv = [
      'sku_id,product_name,brand,category,current_stock,retail_price_usd,cost_price_usd',
      'CSV-001,Runner One,Nike,Footwear,10,120,60',
      'CSV-002,Runner Two,Adidas,Footwear,5,95,40',
    ].join('\n');

    const parsed = parseInventoryCsv(csv);

    expect(parsed.errors).toEqual([]);
    expect(parsed.rows).toHaveLength(2);
    expect(parsed.rows.map((row) => row.sku_id)).toEqual(['CSV-001', 'CSV-002']);
    expect(parsed.rows[0]).toMatchObject({
      product_name: 'Runner One',
      current_stock: 10,
      retail_price_usd: 120,
      cost_price_usd: 60,
    });
  });

  it('supports common CSV header aliases from shop exports', () => {
    const csv = [
      'sku,title,brand_name,department,qty,price,cost',
      'CSV-ALIAS-001,Alias Runner,Asics,Running,7,$130.00,$70.00',
    ].join('\n');

    const parsed = parseInventoryCsv(csv);

    expect(parsed.errors).toEqual([]);
    expect(parsed.rows[0]).toMatchObject({
      sku_id: 'CSV-ALIAS-001',
      product_name: 'Alias Runner',
      brand: 'Asics',
      category: 'Running',
      current_stock: 7,
      retail_price_usd: 130,
      cost_price_usd: 70,
    });
  });

  it('rejects rows that are not model-ready for inventory import', () => {
    const csv = [
      'sku_id,product_name,brand,category,current_stock,retail_price_usd,cost_price_usd',
      'CSV-BAD-001,Missing Retail,Nike,Footwear,10,,60',
      'CSV-BAD-002,Cost Above Retail,Adidas,Footwear,5,95,120',
    ].join('\n');

    const parsed = parseInventoryCsv(csv);

    expect(parsed.rows).toEqual([]);
    expect(parsed.errors).toContain('Row 2: retail_price_usd is required and must be greater than 0.');
    expect(parsed.errors).toContain('Row 3: cost_price_usd must be lower than retail_price_usd.');
  });
});
