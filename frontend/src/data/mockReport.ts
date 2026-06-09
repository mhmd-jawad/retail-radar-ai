// Seeded realistic mock data for Retail Radar AI - Lebanese sports retail.
import type {
  Report, SkuAnalysis, Decision, SkuPositioning, PromoteItem, MarkdownItem,
  ClearanceItem, HoldPricingItem, Directive, Alert, ScrapeRun, CompetitorProductLatest,
  AuditEntry, CampaignCreative,
} from '@/types/domain';

const BRANDS = ['Adidas', 'Nike', 'Puma', 'New Balance', 'Asics', 'Under Armour', 'Reebok', 'Mizuno'];
const CATEGORIES = ['Running Shoes', 'Football Boots', 'Training Apparel', 'Basketball', 'Lifestyle Sneakers', 'Accessories', 'Outdoor', 'Swim'];
const SHOPS = ['adidas_lb', 'mikesport', 'tchooz', 'shoesworld', 'citysport', 'kix', 'marka_store'];

// Deterministic PRNG
function mulberry32(seed: number) {
  return function () {
    let t = (seed += 0x6D2B79F5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rnd = mulberry32(20251);
const pick = <T,>(arr: T[]) => arr[Math.floor(rnd() * arr.length)];
const round = (n: number, d = 2) => Math.round(n * 10 ** d) / 10 ** d;

const TARGET_COUNTS: Record<Decision, number> = {
  HOLD: 86, PROMOTE: 106, MARKDOWN: 156, CLEAR: 2,
};

function decisionFromHealth(health: SkuAnalysis['health'], idx: number): Decision {
  // distribute deterministically to hit target counts roughly
  if (idx < 2) return 'CLEAR';
  if (idx < 88) return 'HOLD';
  if (idx < 194) return 'PROMOTE';
  return 'MARKDOWN';
}

function genSkus(n: number): SkuAnalysis[] {
  const skus: SkuAnalysis[] = [];
  for (let i = 0; i < n; i++) {
    const brand = pick(BRANDS);
    const cat = pick(CATEGORIES);
    const initial = 40 + Math.floor(rnd() * 260);
    const sold = Math.floor(initial * (0.2 + rnd() * 0.85));
    const current = Math.max(0, initial - sold);
    const days_since_launch = 14 + Math.floor(rnd() * 220);
    const velocity = round(Math.max(0.05, sold / Math.max(1, days_since_launch)), 2);
    const dos = round(velocity > 0 ? current / velocity : 999, 1);
    const retail = round(45 + rnd() * 220, 2);
    const cost = round(retail * (0.42 + rnd() * 0.18), 2);
    const margin = round(((retail - cost) / retail) * 100, 1);
    const health: SkuAnalysis['health'] =
      current === 0 || dos <= 21 ? 'critical' :
      dos > 180 ? 'dead' :
      dos > 90 ? 'excess' : 'healthy';
    const decision = decisionFromHealth(health, i);
    skus.push({
      sku_id: `RR-${String(10000 + i)}`,
      product_name: `${brand} ${cat.split(' ')[0]} ${['Pro', 'Elite', 'Core', 'Vector', 'Halo', 'Drift', 'Rift', 'Pulse'][i % 8]} ${22 + (i % 8)}`,
      brand, category: cat,
      current_stock: current, initial_stock: initial,
      retail_price_usd: retail, cost_price_usd: cost, margin_pct: margin,
      days_of_supply: dos, days_since_launch, velocity_units_per_day: velocity,
      days_since_last_discount: 30 + Math.floor(rnd() * 200),
      days_at_current_price: 14 + Math.floor(rnd() * 120),
      health, decision,
    });
  }
  return skus;
}

const SKUS = genSkus(350);

// Inventory aggregates
const totalUnits = SKUS.reduce((s, x) => s + x.current_stock, 0);
const valueAtCost = SKUS.reduce((s, x) => s + x.current_stock * x.cost_price_usd, 0);
const valueAtRetail = SKUS.reduce((s, x) => s + x.current_stock * x.retail_price_usd, 0);
const blendedMargin = round(((valueAtRetail - valueAtCost) / valueAtRetail) * 100, 1);
const dos = SKUS.map(s => s.days_of_supply).sort((a, b) => a - b);
const median = dos[Math.floor(dos.length / 2)];

const categorySummary: Report['inventory']['category_summary'] = {};
for (const s of SKUS) {
  const c = (categorySummary[s.category] ||= { skus: 0, units: 0, value_usd: 0, avg_margin_pct: 0, median_dos: 0, health_score: 0 });
  c.skus++; c.units += s.current_stock; c.value_usd += s.current_stock * s.cost_price_usd; c.avg_margin_pct += s.margin_pct; c.median_dos += s.days_of_supply;
}
for (const k of Object.keys(categorySummary)) {
  const c = categorySummary[k];
  c.avg_margin_pct = round(c.avg_margin_pct / c.skus, 1);
  c.median_dos = round(c.median_dos / c.skus, 1);
  c.value_usd = round(c.value_usd, 0);
  c.health_score = round(Math.max(0, 100 - Math.abs(c.median_dos - 60) * 0.6 - Math.max(0, 45 - c.avg_margin_pct) * 1.5), 0);
}

const inventoryAlerts: Alert[] = [
  { id: 'a1', severity: 'critical', title: 'Dead stock concentration in Outdoor', detail: '23 SKUs above 180 DOS — $42.1k locked at cost.', category: 'Outdoor', created_at: '2026-04-21T08:14:00Z' },
  { id: 'a2', severity: 'high', title: 'Football Boots inventory ratio elevated', detail: 'Category holds 19% of inventory value vs 12% sales share.', category: 'Football Boots', created_at: '2026-04-21T07:02:00Z' },
  { id: 'a3', severity: 'medium', title: 'Replenishment window opening for Running', detail: 'Lead time 5 weeks — May/June peak approaching.', category: 'Running Shoes', created_at: '2026-04-20T18:33:00Z' },
  { id: 'a4', severity: 'low', title: '2 SKUs flagged for clearance', detail: 'Cash recovery est. $1.8k — generator/storage overhead reduced.', created_at: '2026-04-20T11:05:00Z' },
];

// Competitor positioning
const positions: SkuPositioning[] = SKUS.slice(0, 200).map((s, i) => {
  const our = s.retail_price_usd;
  const market_avg = round(our * (0.85 + rnd() * 0.4), 2);
  const market_min = round(market_avg * (0.85 + rnd() * 0.1), 2);
  const gap = round(((our - market_avg) / market_avg) * 100, 1);
  const position: SkuPositioning['position'] =
    gap > 15 ? 'premium' : gap > 5 ? 'above_market' : gap > -5 ? 'at_market' : gap > -15 ? 'below_market' : 'deep_value';
  return {
    sku_id: s.sku_id, product_name: s.product_name, brand: s.brand, category: s.category,
    our_price_usd: our, market_min_usd: market_min, market_avg_usd: market_avg,
    price_gap_pct: gap, position,
    competitors_count: 2 + Math.floor(rnd() * 5),
    competitors_on_sale: Math.floor(rnd() * 3),
    cheapest_shop: pick(SHOPS),
  };
});
const overpriced = positions.filter(p => p.price_gap_pct > 15).length;
const underpriced = positions.filter(p => p.price_gap_pct < -10).length;

const brandSummary: Report['competitor']['brand_summary'] = {};
for (const b of BRANDS) {
  const subset = positions.filter(p => p.brand === b);
  if (!subset.length) continue;
  const avg = round(subset.reduce((s, x) => s + x.price_gap_pct, 0) / subset.length, 1);
  brandSummary[b] = {
    skus: subset.length, avg_gap_pct: avg,
    position: avg > 10 ? 'premium' : avg > 0 ? 'above_market' : avg > -10 ? 'at_market' : 'below_market',
    coverage: round(subset.length / 200, 2),
  };
}

const compCategorySummary: Report['competitor']['category_summary'] = {};
for (const c of CATEGORIES) {
  const subset = positions.filter(p => p.category === c);
  if (!subset.length) continue;
  compCategorySummary[c] = { skus: subset.length, avg_gap_pct: round(subset.reduce((s, x) => s + x.price_gap_pct, 0) / subset.length, 1) };
}

const opportunities = positions
  .filter(p => Math.abs(p.price_gap_pct) > 12)
  .slice(0, 12)
  .map(p => ({
    sku_id: p.sku_id, product_name: p.product_name, brand: p.brand,
    type: (p.price_gap_pct > 0 ? 'undercut' : 'raise') as 'undercut' | 'raise',
    current_price_usd: p.our_price_usd,
    suggested_price_usd: round(p.market_avg_usd * (p.price_gap_pct > 0 ? 0.98 : 1.05), 2),
    est_uplift_usd: round(rnd() * 1800 + 240, 0),
    rationale: p.price_gap_pct > 0
      ? `Premium of ${p.price_gap_pct}% vs market avg — ${p.cheapest_shop} undercutting.`
      : `Underpriced by ${Math.abs(p.price_gap_pct)}% — margin uplift available without losing share.`,
  }));

// Promote items with creatives
const sampleCreative: CampaignCreative = {
  headline: 'Run Beirut. Lighter, faster, all summer.',
  subheadline: 'Limited drops in store and at retailradar.lb',
  ad_copy_short: 'New season runners. Built for the Corniche grind.',
  ad_copy_long: 'From morning Corniche miles to AUB intramurals — the new running drop is engineered for Lebanese summer pavement. In-store now across Beirut, Jounieh, and Tripoli. Cash and card welcome.',
  instagram_post: '☀️ Summer pace, secured.\nNew running drop — fresh USD pricing, in stock today.\n#RetailRadar #BeirutRuns',
  facebook_post: 'Your summer running upgrade is here. Visit our Beirut, Jounieh or Tripoli locations — limited stock per size.',
  telegram_broadcast: 'Mar7aba 👋 New running drop just landed — shall we hold a pair in your size? Reply with size + city.',
  cta_primary: 'Reserve in store',
  cta_secondary: 'Message us on Telegram',
  generation_confidence: 0.86, fallback_used: false,
};

const promote: PromoteItem[] = SKUS.filter(s => s.decision === 'PROMOTE').slice(0, 30).map((s, i) => ({
  sku_id: s.sku_id, product_name: s.product_name, brand: s.brand, category: s.category,
  reason: i % 3 === 0 ? 'Healthy margin + below-market price + seasonal tailwind' : 'Strong velocity, low days-of-supply risk',
  expected_lift_pct: round(8 + rnd() * 22, 1),
  channels: ['Instagram', 'Telegram', 'In-store window'],
  creative: i < 12 ? { ...sampleCreative, headline: `${s.brand} ${s.category.split(' ')[0]} — built for Lebanese summer`, generation_confidence: round(0.7 + rnd() * 0.25, 2) } : undefined,
}));

const markdown: MarkdownItem[] = SKUS.filter(s => s.decision === 'MARKDOWN').slice(0, 40).map(s => {
  const disc = round(10 + rnd() * 25, 0);
  const newPrice = round(s.retail_price_usd * (1 - disc / 100), 2);
  const marginAfter = round(((newPrice - s.cost_price_usd) / newPrice) * 100, 1);
  return {
    sku_id: s.sku_id, product_name: s.product_name, brand: s.brand,
    current_price_usd: s.retail_price_usd, suggested_discount_pct: disc,
    suggested_price_usd: newPrice, margin_after_pct: marginAfter,
    reason: s.days_of_supply > 90 ? 'Excess DOS — clear before lead-time refresh' : 'Competitor undercut sustained 14+ days',
    urgency: marginAfter < 30 ? 'high' : marginAfter < 38 ? 'medium' : 'low',
  };
});

const clearance: ClearanceItem[] = SKUS.filter(s => s.decision === 'CLEAR').slice(0, 2).map(s => ({
  sku_id: s.sku_id, product_name: s.product_name, brand: s.brand,
  current_stock: s.current_stock, age_days: s.days_since_launch,
  suggested_price_usd: round(s.cost_price_usd * 1.05, 2),
  recovered_cash_usd: round(s.current_stock * s.cost_price_usd * 1.05, 0),
  urgency: 'critical',
}));

const hold_pricing: HoldPricingItem[] = SKUS.filter(s => s.decision === 'HOLD').slice(0, 24).map(s => ({
  sku_id: s.sku_id, product_name: s.product_name, brand: s.brand,
  reason: 'Healthy margin and DOS within 45–90 band — no signal to act.',
  margin_pct: s.margin_pct, velocity: s.velocity_units_per_day,
}));

const directives: Directive[] = [
  { owner: 'Buying', priority: 'high', title: 'Pause Outdoor reorder cycle', detail: '23 dead-stock SKUs exceed 180 DOS. Defer Outdoor PO #4421 until Q3 review.' },
  { owner: 'Marketing', priority: 'high', title: 'Launch Running summer push', detail: '12 PROMOTE SKUs ready with creatives. Schedule Instagram + WhatsApp broadcast for May 1.' },
  { owner: 'Operations', priority: 'medium', title: 'Reallocate Tripoli stock', detail: 'Move 38 units of Football Boots from Tripoli to Jounieh ahead of league season.' },
  { owner: 'Buying', priority: 'medium', title: 'Lock USD pricing on next PO', detail: 'Request a 60-day price lock from 2 suppliers to protect working capital.' },
];

const seasonal_actions: Report['promotions']['seasonal_actions'] = [
  { month: 'May', action: 'PROMOTE', category: 'Running Shoes', detail: 'Pre-summer Corniche running surge — push fresh inventory.' },
  { month: 'Jun', action: 'PROMOTE', category: 'Swim', detail: 'Beach club season — accessories and swim attach rate peaks.' },
  { month: 'Jul', action: 'HOLD', category: 'Football Boots', detail: 'Off-season — protect margin, no markdowns.' },
  { month: 'Aug', action: 'PROMOTE', category: 'Football Boots', detail: 'School league restart — back-to-school demand window opens.' },
  { month: 'Sep', action: 'PROMOTE', category: 'Training Apparel', detail: 'Gym re-engagement — bundle apparel with accessories.' },
  { month: 'Oct', action: 'MARKDOWN', category: 'Lifestyle Sneakers', detail: 'Pre-winter inventory clear before Q4 reorder cycle.' },
];


export const MOCK_REPORT: Report = {
  inventory: {
    metrics: {
      total_skus: 350, total_units: totalUnits,
      inventory_value_at_cost_usd: round(valueAtCost, 0),
      inventory_value_at_retail_usd: round(valueAtRetail, 0),
      blended_margin_pct: blendedMargin,
      median_days_of_supply: median,
      critical_stockouts: 0,
      dead_stock_skus: SKUS.filter(s => s.health === 'dead').length,
      excess_stock_skus: SKUS.filter(s => s.health === 'excess').length,
      healthy_skus: SKUS.filter(s => s.health === 'healthy').length,
    },
    sku_analysis: SKUS,
    category_summary: categorySummary,
    alerts: inventoryAlerts,
  },
  competitor: {
    market_overview: {
      skus_tracked: 200, competitor_records: null, shops_covered: null,
      avg_price_gap_pct: null, overpriced_skus: null, underpriced_skus: null,
      at_market_skus: null, data_freshness_hours: null, status: 'not_connected',
    },
    sku_positioning: positions,
    brand_summary: brandSummary,
    category_summary: compCategorySummary,
    opportunities,
  },
  promotions: {
    hold_pricing, promote, markdown, clearance, seasonal_actions, directives,
    summary: { hold_count: 86, promote_count: 106, markdown_count: 156, clearance_count: 2 },
  },
  metadata: {
    generated_at: '2026-04-22T06:30:00Z',
    engine_version: 'analytics-engine 0.9.2',
    market: 'Lebanon', currency: 'fresh USD', data_window_days: 90,
    source: 'mock-report (seeded)',
  },
};

// Scrape runs / competitor latest mock data
export const MOCK_SCRAPE_RUNS: ScrapeRun[] = SHOPS.flatMap((shop, i) => [
  {
    id: `sr-${shop}-1`, shop, started_at: '2026-04-22T05:00:00Z',
    finished_at: '2026-04-22T05:14:00Z', status: i === 5 ? 'partial' : 'success',
    items_scraped: 1240 + i * 180, valid_rows: 1180 + i * 170,
  },
  {
    id: `sr-${shop}-2`, shop, started_at: '2026-04-21T05:00:00Z',
    finished_at: '2026-04-21T05:11:00Z', status: 'success',
    items_scraped: 1210 + i * 180, valid_rows: 1175 + i * 170,
  },
]);

export const MOCK_COMPETITOR_LATEST: CompetitorProductLatest[] = SHOPS.flatMap((shop) =>
  Array.from({ length: 6 }).map((_, j) => ({
    shop, external_id: `${shop}-${1000 + j}`,
    product_name: `${pick(BRANDS)} ${pick(CATEGORIES).split(' ')[0]} ${j + 1}`,
    brand: pick(BRANDS), price_usd: round(60 + rnd() * 200, 2),
    on_sale: rnd() > 0.7, in_stock: rnd() > 0.15,
    url: `https://${shop}.lb/p/${1000 + j}`,
    last_seen: '2026-04-22T05:14:00Z',
  }))
);

export const MOCK_AUDIT: AuditEntry[] = Array.from({ length: 18 }).map((_, i) => {
  const s = SKUS[i * 7];
  const decision = (['HOLD', 'MARKDOWN', 'PROMOTE', 'CLEAR'] as Decision[])[i % 4];
  const status = (['approved', 'edited', 'rejected', 'snoozed'] as const)[i % 4];
  return {
    id: `au-${i}`, sku_id: s.sku_id, product_name: s.product_name, decision, status,
    actor: ['nadine.k', 'rami.h', 'sara.m', 'omar.j'][i % 4],
    before: { price_usd: s.retail_price_usd },
    after: decision === 'MARKDOWN' ? { price_usd: round(s.retail_price_usd * 0.85, 2), discount_pct: 15 } : { price_usd: s.retail_price_usd },
    notes: i % 3 === 0 ? 'Approved for Beirut + Jounieh stores only.' : undefined,
    timestamp: new Date(Date.now() - i * 3600_000 * 8).toISOString(),
  };
});

export { SHOPS };

