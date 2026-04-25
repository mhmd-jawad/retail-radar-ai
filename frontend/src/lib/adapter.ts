// Adapter layer: 4 modes
//   1) mock-report    — local seeded report.json shape
//   2) ie2-live       — http://localhost:8002 (recommendation only)
//   3) eep-live       — http://localhost:8000 (report + ops + recommend)
//   4) supabase-ready — future tables (scrape_runs, competitor_product_snapshots, competitor_products_latest)
//
// UI components consume frontend domain models only. Any API contract
// differences are normalized here so the screens do not need to care.

import type {
  Report,
  IE2Request,
  IE2Result,
  ScrapeRun,
  CompetitorProductLatest,
  DataMode,
  RetailDbStatus,
  RetailInventoryImportResult,
  RetailInventoryInput,
  RetailInventoryItem,
  RetailInventoryResponse,
} from '@/types/domain';
import { MOCK_REPORT, MOCK_SCRAPE_RUNS, MOCK_COMPETITOR_LATEST } from '@/data/mockReport';
import { useSettings } from '@/store/settings';

function settings() {
  const s = useSettings.getState();
  return { mode: s.mode, ie2: s.ie2BaseUrl, base: s.apiBaseUrl, key: s.apiKey };
}

export async function fetchReport(): Promise<Report> {
  const { mode, base } = settings();
  if (mode === 'eep-live') {
    const r = await fetch(`${base}/report`);
    if (!r.ok) throw new Error(`EEP /report ${r.status}`);
    return r.json();
  }
  await wait(180);
  return MOCK_REPORT;
}

export async function fetchScrapeRuns(): Promise<ScrapeRun[]> {
  const { mode, base } = settings();
  if (mode === 'eep-live') {
    const r = await fetch(`${base}/ops/scrape-runs`);
    if (!r.ok) throw new Error(`EEP /ops/scrape-runs ${r.status}`);
    return r.json();
  }
  await wait(120);
  return MOCK_SCRAPE_RUNS;
}

export async function fetchCompetitorLatest(): Promise<CompetitorProductLatest[]> {
  const { mode, base } = settings();
  if (mode === 'eep-live') {
    const r = await fetch(`${base}/ops/competitor-latest?limit=50`);
    if (!r.ok) throw new Error(`EEP /ops/competitor-latest ${r.status}`);
    return r.json();
  }
  await wait(120);
  return MOCK_COMPETITOR_LATEST;
}

export async function fetchRetailDbStatus(): Promise<RetailDbStatus> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/db/status`);
  if (!r.ok) throw new Error(`EEP /inventory/db/status ${r.status}`);
  return r.json();
}

export async function fetchRetailInventory(search = ''): Promise<RetailInventoryResponse> {
  const { base } = settings();
  const params = new URLSearchParams();
  if (search.trim()) params.set('search', search.trim());
  params.set('limit', '1000');
  const r = await fetch(`${base}/inventory/items?${params.toString()}`);
  if (!r.ok) throw new Error(await apiError(r, 'EEP /inventory/items'));
  return r.json();
}

export async function createRetailInventoryItem(payload: RetailInventoryInput): Promise<RetailInventoryItem> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/items`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /inventory/items'));
  return r.json();
}

export async function updateRetailInventoryItem(skuId: string, payload: RetailInventoryInput): Promise<RetailInventoryItem> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/items/${encodeURIComponent(skuId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await apiError(r, `EEP /inventory/items/${skuId}`));
  return r.json();
}

export async function archiveRetailInventoryItem(skuId: string): Promise<RetailInventoryItem> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/items/${encodeURIComponent(skuId)}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(await apiError(r, `EEP /inventory/items/${skuId}`));
  return r.json();
}

export async function importRetailInventory(
  items: RetailInventoryInput[],
  mode: 'upsert' | 'replace',
): Promise<RetailInventoryImportResult> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, items }),
  });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /inventory/import'));
  return r.json();
}

export async function recommend(req: IE2Request): Promise<IE2Result> {
  const { mode, ie2, base, key } = settings();
  const normalizedReq = normalizeRequest(req);

  if (mode === 'ie2-live') {
    const r = await fetch(`${ie2}/recommend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
      body: JSON.stringify(normalizedReq),
    });
    if (!r.ok) throw new Error(`IE2 /recommend ${r.status}`);
    return normalizeRecommendation(await r.json());
  }

  if (mode === 'eep-live') {
    const r = await fetch(`${base}/recommend/${encodeURIComponent(req.sku_id)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
      body: JSON.stringify(normalizedReq),
    });
    if (!r.ok) throw new Error(`EEP /recommend ${r.status}`);
    return normalizeRecommendation(await r.json());
  }

  return mockRecommend(req);
}

export async function pingIE2(): Promise<{ ok: boolean; latency_ms: number; detail?: string }> {
  const { ie2, key } = settings();
  const t0 = performance.now();
  try {
    const r = await fetch(`${ie2}/health`, { headers: { 'X-API-Key': key } });
    return { ok: r.ok, latency_ms: Math.round(performance.now() - t0), detail: r.ok ? 'healthy' : `HTTP ${r.status}` };
  } catch (e: any) {
    return { ok: false, latency_ms: Math.round(performance.now() - t0), detail: e?.message || 'unreachable' };
  }
}

function normalizeRequest(req: IE2Request): any {
  const gap = Number(req.competitor_signals?.price_gap_pct ?? 0);
  const trend = String(req.competitor_signals?.price_trend_direction ?? 'flat').toLowerCase();
  return {
    ...req,
    competitor_signals: {
      ...req.competitor_signals,
      price_gap_pct: Math.abs(gap) > 1 ? gap / 100 : gap,
      price_trend_direction:
        trend === 'up' ? 'RISING' as any :
        trend === 'down' ? 'FALLING' as any :
        'STABLE' as any,
    },
  };
}

function normalizeRecommendation(payload: any): IE2Result {
  const shapTop5 = Array.isArray(payload?.shap_top5) ? payload.shap_top5.map((item: any) => ({
    feature: item.feature ?? item.feature_name ?? 'feature',
    impact: Number(item.impact ?? item.shap_value ?? 0),
    direction: item.direction === 'positive' || item.direction === 'increases_probability' ? 'positive' : 'negative',
  })) : [];

  return {
    recommendation: payload?.recommendation,
    confidence: Number(payload?.confidence ?? 0),
    explanation: payload?.explanation ?? '',
    shap_top5: shapTop5,
    rule_override: typeof payload?.rule_override === 'string'
      ? payload.rule_override
      : payload?.rule_override?.rule_id ?? null,
    fallback_used: Boolean(payload?.fallback_used),
    suggested_discount_pct: payload?.suggested_discount_pct,
    suggested_price_usd: payload?.suggested_price_usd,
    margin_after_action_pct: payload?.margin_after_action_pct,
    model_version: payload?.model_version ?? 'unknown',
    processing_time_ms: Number(payload?.processing_time_ms ?? 0),
    requires_human_approval: Boolean(payload?.requires_human_approval ?? true),
  };
}

// ---------- mock recommendation engine (matches IE2 result shape) ----------
function mockRecommend(req: IE2Request): IE2Result {
  const margin = ((req.retail_price_usd - req.cost_price_usd) / req.retail_price_usd) * 100;
  const dos = req.current_stock / Math.max(0.1, req.initial_stock / Math.max(1, req.days_since_launch));
  const gap = req.competitor_signals.price_gap_pct;
  let recommendation: IE2Result['recommendation'] = 'HOLD';
  let suggested_discount_pct: number | undefined;
  let suggested_price_usd: number | undefined;
  let rule_override: string | null = null;

  if (dos > 180 && margin < 35) { recommendation = 'CLEAR'; suggested_discount_pct = 35; rule_override = 'dead_stock_margin_floor_breach'; }
  else if (dos > 90 || gap > 15) { recommendation = 'MARKDOWN'; suggested_discount_pct = Math.min(25, Math.max(8, Math.round(gap > 0 ? gap : 12))); }
  else if (dos < 45 && margin >= 45 && gap < 5) { recommendation = 'PROMOTE'; }
  else { recommendation = 'HOLD'; }

  if (suggested_discount_pct) {
    suggested_price_usd = round(req.retail_price_usd * (1 - suggested_discount_pct / 100), 2);
  }
  const marginAfter = suggested_price_usd
    ? round(((suggested_price_usd - req.cost_price_usd) / suggested_price_usd) * 100, 1)
    : round(margin, 1);

  return {
    recommendation, confidence: round(0.72 + Math.random() * 0.22, 2),
    explanation: explain(recommendation, dos, gap, margin),
    shap_top5: [
      { feature: 'days_of_supply', impact: clamp((dos - 60) / 100, -1, 1), direction: dos > 60 ? 'positive' : 'negative' },
      { feature: 'competitor_price_gap_pct', impact: clamp(gap / 30, -1, 1), direction: gap > 0 ? 'positive' : 'negative' },
      { feature: 'margin_pct', impact: clamp((margin - 40) / 40, -1, 1), direction: margin > 40 ? 'negative' : 'positive' },
      { feature: 'competitors_on_sale_count', impact: req.competitor_signals.competitors_on_sale_count / 5, direction: 'positive' },
      { feature: 'days_since_last_discount', impact: clamp(req.days_since_last_discount / 200, 0, 1), direction: 'positive' },
    ],
    rule_override, fallback_used: false,
    suggested_discount_pct, suggested_price_usd, margin_after_action_pct: marginAfter,
    model_version: 'ie2-mock-1.4.0', processing_time_ms: 38 + Math.floor(Math.random() * 80),
    requires_human_approval: true,
  };
}

function explain(d: string, dos: number, gap: number, margin: number) {
  if (d === 'CLEAR') return `Dead stock signal — DOS ${dos.toFixed(0)} with margin floor at risk. Recover cash before lead-time refresh.`;
  if (d === 'MARKDOWN') return `Excess inventory or competitor undercut (${gap.toFixed(1)}%). Apply controlled discount; protects >=35% margin floor.`;
  if (d === 'PROMOTE') return `Healthy margin (${margin.toFixed(0)}%) and below-market pricing. Demand window favorable — push visibility.`;
  return `Within healthy DOS band and competitive position. Hold price, monitor weekly.`;
}

function round(n: number, d: number) { return Math.round(n * 10 ** d) / 10 ** d; }
function clamp(n: number, a: number, b: number) { return Math.max(a, Math.min(b, n)); }
function wait(ms: number) { return new Promise((r) => setTimeout(r, ms)); }

async function apiError(response: Response, label: string) {
  try {
    const payload = await response.json();
    return `${label} ${response.status}: ${payload.detail || response.statusText}`;
  } catch {
    return `${label} ${response.status}: ${response.statusText}`;
  }
}

// Supabase-ready stubs (future)
export const supabaseRepo = {
  async listScrapeRuns(): Promise<ScrapeRun[]> {
    return MOCK_SCRAPE_RUNS;
  },
  async listCompetitorLatest(): Promise<CompetitorProductLatest[]> {
    return MOCK_COMPETITOR_LATEST;
  },
  async insertSnapshot(_snap: unknown): Promise<void> {
  },
};

export function modeLabel(m: DataMode) {
  return ({ 'mock-report': 'Mock Report', 'ie2-live': 'IE2 Live', 'eep-live': 'EEP Live', 'supabase-ready': 'Supabase' } as const)[m];
}
