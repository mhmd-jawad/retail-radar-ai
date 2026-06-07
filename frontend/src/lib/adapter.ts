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
  RetailInventoryMovementInput,
  RetailInventoryMovementResult,
  RetailInventoryResponse,
  AuthResponse,
  AdminTenant,
  AppNotification,
  CampaignCreative,
  CompetitorRequest,
  CompetitorOption,
  DetailedBalanceSheet,
  DetailedProfitability,
  OutcomeSnapshot,
  DailySalesPoint,
  PortfolioAccuracy,
  ShopProfile,
  ShopProfileInput,
  ShopSignupInput,
} from '@/types/domain';
import { MOCK_SCRAPE_RUNS, MOCK_COMPETITOR_LATEST } from '@/data/mockReport';
import { useSettings } from '@/store/settings';
import { authHeader, useAuth } from '@/store/auth';

function settings() {
  const s = useSettings.getState();
  return { mode: s.mode, ie1: s.ie1BaseUrl, ie2: s.ie2BaseUrl, base: s.apiBaseUrl, key: s.apiKey };
}

function apiHeaders(extra?: Record<string, string>): Record<string, string> {
  return { ...authHeader(), ...(extra ?? {}) };
}

function hasAuthSession(): boolean {
  return Boolean(useAuth.getState().token);
}

export async function loginAccount(email: string, password: string): Promise<AuthResponse> {
  const { base } = settings();
  const r = await fetch(`${base}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /auth/login'));
  return r.json();
}

export async function signupShop(payload: ShopSignupInput): Promise<AuthResponse> {
  const { base } = settings();
  const r = await fetch(`${base}/auth/signup-shop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /auth/signup-shop'));
  return r.json();
}

export async function fetchCurrentUser(): Promise<AuthResponse['user']> {
  const { base } = settings();
  const r = await fetch(`${base}/auth/me`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /auth/me'));
  return r.json();
}

export async function logoutAccount(): Promise<void> {
  const { base } = settings();
  const r = await fetch(`${base}/auth/logout`, { method: 'POST', headers: apiHeaders() });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /auth/logout'));
}

export async function fetchAvailableCompetitors(): Promise<CompetitorOption[]> {
  const { base } = settings();
  const r = await fetch(`${base}/auth/competitors`);
  if (!r.ok) throw new Error(await apiError(r, 'EEP /auth/competitors'));
  return r.json();
}

export async function fetchShopProfile(): Promise<ShopProfile> {
  const { base } = settings();
  const r = await fetch(`${base}/shop/profile`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /shop/profile'));
  return r.json();
}

export async function updateShopProfile(payload: ShopProfileInput): Promise<ShopProfile> {
  const { base } = settings();
  const r = await fetch(`${base}/shop/profile`, {
    method: 'PUT',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /shop/profile'));
  return r.json();
}

export async function fetchAdminTenants(): Promise<AdminTenant[]> {
  const { base } = settings();
  const r = await fetch(`${base}/admin/tenants`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /admin/tenants'));
  return r.json();
}

export async function fetchAdminNotifications(status?: AppNotification['status']): Promise<AppNotification[]> {
  const { base } = settings();
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  const query = params.toString() ? `?${params.toString()}` : '';
  const r = await fetch(`${base}/admin/notifications${query}`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /admin/notifications'));
  return r.json();
}

export async function updateAdminNotificationStatus(
  id: string,
  status: AppNotification['status'],
): Promise<AppNotification> {
  const { base } = settings();
  const r = await fetch(`${base}/admin/notifications/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ status }),
  });
  if (!r.ok) throw new Error(await apiError(r, `EEP /admin/notifications/${id}`));
  return r.json();
}

export async function fetchAdminCompetitorRequests(status?: CompetitorRequest['status']): Promise<CompetitorRequest[]> {
  const { base } = settings();
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  const query = params.toString() ? `?${params.toString()}` : '';
  const r = await fetch(`${base}/admin/competitor-requests${query}`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /admin/competitor-requests'));
  return r.json();
}

export async function fetchAdminCompetitors(): Promise<CompetitorOption[]> {
  const { base } = settings();
  const r = await fetch(`${base}/admin/competitors`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /admin/competitors'));
  return r.json();
}

export async function reviewAdminCompetitorRequest(
  id: string,
  action: 'approve' | 'reject',
  adminNotes?: string,
): Promise<CompetitorRequest> {
  const { base } = settings();
  const r = await fetch(`${base}/admin/competitor-requests/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ action, admin_notes: adminNotes ?? null }),
  });
  if (!r.ok) throw new Error(await apiError(r, `EEP /admin/competitor-requests/${id}`));
  return r.json();
}

export async function updateAdminShopStatus(
  tenantId: string,
  onboardingStatus: 'pending' | 'active' | 'suspended' | 'archived',
): Promise<AdminTenant> {
  const { base } = settings();
  const r = await fetch(`${base}/admin/shops/${encodeURIComponent(tenantId)}`, {
    method: 'PATCH',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ onboarding_status: onboardingStatus }),
  });
  if (!r.ok) throw new Error(await apiError(r, `EEP /admin/shops/${tenantId}`));
  return r.json();
}

export async function impersonateShop(tenantId: string): Promise<AuthResponse> {
  const { base } = settings();
  const r = await fetch(`${base}/admin/impersonate/${encodeURIComponent(tenantId)}`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!r.ok) throw new Error(await apiError(r, `EEP /admin/impersonate/${tenantId}`));
  return r.json();
}

export async function fetchReport(): Promise<Report> {
  const { base } = settings();
  const r = await fetch(`${base}/report`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(`/report ${r.status}`);
  return r.json();
}

export async function fetchLiveReport(): Promise<Report> {
  const { base } = settings();
  const r = await fetch(`${base}/report/live`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(`/report/live ${r.status}`);
  return r.json();
}

export async function fetchScrapeRuns(): Promise<ScrapeRun[]> {
  const { mode, base } = settings();
  if (mode === 'eep-live' || hasAuthSession()) {
    const r = await fetch(`${base}/ops/scrape-runs`, { headers: apiHeaders() });
    if (!r.ok) throw new Error(`EEP /ops/scrape-runs ${r.status}`);
    return r.json();
  }
  await wait(120);
  return MOCK_SCRAPE_RUNS;
}

export async function fetchCompetitorLatest(): Promise<CompetitorProductLatest[]> {
  const { mode, base } = settings();
  if (mode === 'eep-live' || hasAuthSession()) {
    const r = await fetch(`${base}/ops/competitor-latest?limit=50`, { headers: apiHeaders() });
    if (!r.ok) throw new Error(`EEP /ops/competitor-latest ${r.status}`);
    return r.json();
  }
  await wait(120);
  return MOCK_COMPETITOR_LATEST;
}

export async function fetchRetailDbStatus(): Promise<RetailDbStatus> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/db/status`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(`EEP /inventory/db/status ${r.status}`);
  return r.json();
}

export async function fetchRetailInventory(search = ''): Promise<RetailInventoryResponse> {
  const { base } = settings();
  const params = new URLSearchParams();
  if (search.trim()) params.set('search', search.trim());
  params.set('limit', '1000');
  const r = await fetch(`${base}/inventory/items?${params.toString()}`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /inventory/items'));
  return r.json();
}

export async function createRetailInventoryItem(payload: RetailInventoryInput): Promise<RetailInventoryItem> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/items`, {
    method: 'POST',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /inventory/items'));
  return r.json();
}

export async function updateRetailInventoryItem(skuId: string, payload: RetailInventoryInput): Promise<RetailInventoryItem> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/items/${encodeURIComponent(skuId)}`, {
    method: 'PUT',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await apiError(r, `EEP /inventory/items/${skuId}`));
  return r.json();
}

export async function archiveRetailInventoryItem(skuId: string): Promise<RetailInventoryItem> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/items/${encodeURIComponent(skuId)}`, { method: 'DELETE', headers: apiHeaders() });
  if (!r.ok) throw new Error(await apiError(r, `EEP /inventory/items/${skuId}`));
  return r.json();
}

export async function recordRetailInventoryMovement(
  skuId: string,
  payload: RetailInventoryMovementInput,
): Promise<RetailInventoryMovementResult> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/items/${encodeURIComponent(skuId)}/movement`, {
    method: 'POST',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await apiError(r, `EEP /inventory/items/${skuId}/movement`));
  return r.json();
}

export async function importRetailInventory(
  items: RetailInventoryInput[],
  mode: 'upsert' | 'replace',
): Promise<RetailInventoryImportResult> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/import`, {
    method: 'POST',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ mode, items }),
  });
  if (!r.ok) throw new Error(await apiError(r, 'EEP /inventory/import'));
  return r.json();
}

/** Returns `{ ok, db_connected }`. db_connected=false means 503 (no DB) — still treat as success. */
export async function patchInventoryPrice(
  skuId: string,
  retailPriceUsd: number,
  decisionType: 'clearance' | 'markdown' | 'hold',
  notes?: string,
): Promise<{ ok: boolean; db_connected: boolean }> {
  const { base } = settings();
  const r = await fetch(`${base}/inventory/items/${encodeURIComponent(skuId)}/price`, {
    method: 'PATCH',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ retail_price_usd: retailPriceUsd, decision_type: decisionType, notes }),
  });
  if (r.status === 503 || r.status === 404) return { ok: true, db_connected: false };
  if (!r.ok) throw new Error(await apiError(r, `EEP PATCH /inventory/items/${skuId}/price`));
  return { ok: true, db_connected: true };
}

/** Record a non-price retailer decision (e.g. hold acknowledgement). */
export async function recordDecision(
  skuId: string,
  decisionType: 'clearance' | 'markdown' | 'hold' | 'promote',
  notes?: string,
): Promise<{ ok: boolean; db_connected: boolean }> {
  const { base } = settings();
  const r = await fetch(`${base}/decisions`, {
    method: 'POST',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ sku_id: skuId, decision_type: decisionType, notes }),
  });
  if (r.status === 503 || r.status === 404) return { ok: true, db_connected: false };
  if (!r.ok) throw new Error(await apiError(r, 'EEP POST /decisions'));
  return { ok: true, db_connected: true };
}

export async function recommend(req: IE2Request): Promise<IE2Result> {
  const { mode, ie2, base, key } = settings();
  const normalizedReq = normalizeRequest(req);

  if (mode === 'ie2-live' && !hasAuthSession()) {
    const r = await fetch(`${ie2}/recommend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
      body: JSON.stringify(normalizedReq),
    });
    if (!r.ok) throw new Error(`IE2 /recommend ${r.status}`);
    return normalizeRecommendation(await r.json());
  }

  if (mode === 'eep-live' || hasAuthSession()) {
    const r = await fetch(`${base}/recommend/${encodeURIComponent(req.sku_id)}`, {
      method: 'POST',
      headers: apiHeaders({ 'Content-Type': 'application/json', 'X-API-Key': key }),
      body: JSON.stringify(normalizedReq),
    });
    if (!r.ok) throw new Error(`EEP /recommend ${r.status}`);
    return normalizeRecommendation(await r.json());
  }

  return mockRecommend(req);
}

export async function recommendBatch(items: IE2Request[]): Promise<IE2Result[]> {
  if (items.length === 0) return [];

  const { mode, ie2, base, key } = settings();
  const normalizedItems = items.map(normalizeRequest);
  const chunks = chunk(normalizedItems, 50);
  const results: IE2Result[] = [];

  if (mode === 'ie2-live' && !hasAuthSession()) {
    for (const batchItems of chunks) {
      const r = await fetch(`${ie2}/recommend/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
        body: JSON.stringify({ items: batchItems }),
      });
      if (!r.ok) throw new Error(`IE2 /recommend/batch ${r.status}`);
      results.push(...(await r.json()).map(normalizeRecommendation));
    }
    return results;
  }

  if (mode === 'eep-live' || hasAuthSession()) {
    for (const batchItems of chunks) {
      const r = await fetch(`${base}/recommend/batch`, {
        method: 'POST',
        headers: apiHeaders({ 'Content-Type': 'application/json', 'X-API-Key': key }),
        body: JSON.stringify({ items: batchItems }),
      });
      if (!r.ok) throw new Error(await apiError(r, 'EEP /recommend/batch'));
      results.push(...(await r.json()).map(normalizeRecommendation));
    }
    return results;
  }

  return Promise.all(items.map(mockRecommend));
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

export async function pingIE1(): Promise<{ ok: boolean; latency_ms: number; detail?: string }> {
  const { ie1 } = settings();
  const t0 = performance.now();
  try {
    const r = await fetch(`${ie1}/health`);
    return { ok: r.ok, latency_ms: Math.round(performance.now() - t0), detail: r.ok ? 'healthy' : `HTTP ${r.status}` };
  } catch (e: any) {
    return { ok: false, latency_ms: Math.round(performance.now() - t0), detail: e?.message || 'unreachable' };
  }
}

export async function pingEEP(): Promise<{ ok: boolean; latency_ms: number; detail?: string }> {
  const { base } = settings();
  const t0 = performance.now();
  try {
    const r = await fetch(`${base}/health`, { headers: apiHeaders() });
    return { ok: r.ok, latency_ms: Math.round(performance.now() - t0), detail: r.ok ? 'healthy' : `HTTP ${r.status}` };
  } catch (e: any) {
    return { ok: false, latency_ms: Math.round(performance.now() - t0), detail: e?.message || 'unreachable' };
  }
}

export async function pingIE3(): Promise<{ ok: boolean; latency_ms: number; detail?: string }> {
  const ie3 = useSettings.getState().ie3BaseUrl;
  const t0 = performance.now();
  try {
    const r = await fetch(`${ie3}/health`);
    return { ok: r.ok, latency_ms: Math.round(performance.now() - t0), detail: r.ok ? 'healthy' : `HTTP ${r.status}` };
  } catch (e: any) {
    return { ok: false, latency_ms: Math.round(performance.now() - t0), detail: e?.message || 'unreachable' };
  }
}

/**
 * POST {ie3Base}/campaign/generate
 *
 * Sends a RecommendationResult-shaped payload to IE3 which generates copy +
 * image and publishes to Instagram & Facebook atomically in one shot.
 * Returns a CampaignCreative with social_posts reflecting publish status.
 */
export async function generateAndPublishCampaign(
  skuId: string,
  productName: string,
  ie2Result: IE2Result,
): Promise<CampaignCreative> {
  const s = useSettings.getState();
  const ie3 = s.ie3BaseUrl;

  const payload = {
    sku_id: skuId,
    product_name: productName,
    recommendation: ie2Result.recommendation,
    confidence: ie2Result.confidence,
    explanation: ie2Result.explanation,
    shap_top5: ie2Result.shap_top5,
    rule_override: ie2Result.rule_override ?? null,
    fallback_used: ie2Result.fallback_used,
    suggested_discount_pct: ie2Result.suggested_discount_pct ?? null,
    suggested_price_usd: ie2Result.suggested_price_usd ?? null,
    margin_after_action_pct: ie2Result.margin_after_action_pct ?? null,
    model_version: ie2Result.model_version,
    processing_time_ms: ie2Result.processing_time_ms,
    requires_human_approval: ie2Result.requires_human_approval,
  };

  const r = await fetch(`${ie3}/campaign/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!r.ok) throw new Error(await apiError(r, 'IE3 /campaign/generate'));

  const pkg = await r.json();

  // Normalize CampaignPackage → CampaignCreative
  return {
    headline: pkg.headline ?? '',
    subheadline: pkg.ad_copy_short ?? '',
    ad_copy_short: pkg.ad_copy_short ?? '',
    ad_copy_long: pkg.ad_copy_long ?? '',
    instagram_post: pkg.instagram_caption ?? '',
    facebook_post: pkg.facebook_post ?? '',
    whatsapp_broadcast: pkg.whatsapp_message ?? '',
    cta_primary: pkg.cta_primary ?? '',
    cta_secondary: pkg.cta_secondary ?? '',
    image_url: pkg.image_url ?? '',
    tone_used: pkg.tone_used ?? 'aspirational',
    generation_confidence: 1,
    fallback_used: pkg.fallback_used ?? false,
    social_posts: pkg.social_posts ?? [],
  };
}

function normalizeRequest(req: IE2Request): any {
  if (!req.competitor_signals) {
    return req;
  }

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
  if (payload?.error) {
    return {
      sku_id: payload?.sku_id,
      product_name: payload?.product_name,
      recommendation: 'HOLD',
      confidence: 0,
      explanation: payload.error,
      shap_top5: [],
      rule_override: null,
      fallback_used: true,
      model_version: payload?.model_version ?? 'error',
      processing_time_ms: 0,
      requires_human_approval: true,
      competitor_signals_used: payload?.competitor_signals_used ?? null,
      input_context: payload?.input_context ?? null,
      error: payload.error,
      status_code: Number(payload?.status_code ?? 500),
    };
  }

  const shapTop5 = Array.isArray(payload?.shap_top5) ? payload.shap_top5.map((item: any) => ({
    feature: item.feature ?? item.feature_name ?? 'feature',
    impact: Number(item.impact ?? item.shap_value ?? 0),
    direction: item.direction === 'positive' || item.direction === 'increases_probability' ? 'positive' : 'negative',
  })) : [];

  return {
    sku_id: payload?.sku_id,
    product_name: payload?.product_name,
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
    competitor_signals_used: payload?.competitor_signals_used ?? payload?.input_context?.competitor_signals ?? null,
    input_context: payload?.input_context ?? null,
  };
}

// ---------- mock recommendation engine (matches IE2 result shape) ----------
function mockRecommend(req: IE2Request): IE2Result {
  const retailPrice = Number(req.retail_price_usd ?? 100);
  const costPrice = Number(req.cost_price_usd ?? retailPrice * 0.55);
  const currentStock = Number(req.current_stock ?? 1);
  const initialStock = Number(req.initial_stock ?? Math.max(currentStock, 1));
  const daysSinceLaunch = Number(req.days_since_launch ?? 180);
  const competitorSignals = req.competitor_signals ?? defaultCompetitorSignals(req.sku_id);
  const margin = ((retailPrice - costPrice) / retailPrice) * 100;
  const dos = currentStock / Math.max(0.1, initialStock / Math.max(1, daysSinceLaunch));
  const gap = competitorSignals.price_gap_pct;
  let recommendation: IE2Result['recommendation'] = 'HOLD';
  let suggested_discount_pct: number | undefined;
  let suggested_price_usd: number | undefined;
  let rule_override: string | null = null;

  if (dos > 180 && margin < 35) { recommendation = 'CLEAR'; suggested_discount_pct = 35; rule_override = 'dead_stock_margin_floor_breach'; }
  else if (dos > 90 || gap > 15) { recommendation = 'MARKDOWN'; suggested_discount_pct = Math.min(25, Math.max(8, Math.round(gap > 0 ? gap : 12))); }
  else if (dos < 45 && margin >= 45 && gap < 5) { recommendation = 'PROMOTE'; }
  else { recommendation = 'HOLD'; }

  if (suggested_discount_pct) {
    suggested_price_usd = round(retailPrice * (1 - suggested_discount_pct / 100), 2);
  }
  const marginAfter = suggested_price_usd
    ? round(((suggested_price_usd - costPrice) / suggested_price_usd) * 100, 1)
    : round(margin, 1);

  return {
    recommendation, confidence: round(0.72 + Math.random() * 0.22, 2),
    sku_id: req.sku_id,
    product_name: req.product_name,
    explanation: explain(recommendation, dos, gap, margin),
    shap_top5: [
      { feature: 'days_of_supply', impact: clamp((dos - 60) / 100, -1, 1), direction: dos > 60 ? 'positive' : 'negative' },
      { feature: 'competitor_price_gap_pct', impact: clamp(gap / 30, -1, 1), direction: gap > 0 ? 'positive' : 'negative' },
      { feature: 'margin_pct', impact: clamp((margin - 40) / 40, -1, 1), direction: margin > 40 ? 'negative' : 'positive' },
      { feature: 'competitors_on_sale_count', impact: competitorSignals.competitors_on_sale_count / 5, direction: 'positive' },
      { feature: 'days_since_last_discount', impact: clamp(Number(req.days_since_last_discount ?? 999) / 200, 0, 1), direction: 'positive' },
    ],
    rule_override, fallback_used: false,
    suggested_discount_pct, suggested_price_usd, margin_after_action_pct: marginAfter,
    model_version: 'ie2-mock-1.4.0', processing_time_ms: 38 + Math.floor(Math.random() * 80),
    requires_human_approval: true,
    competitor_signals_used: competitorSignals,
    input_context: { ...req, competitor_signals: competitorSignals },
  };
}

function defaultCompetitorSignals(skuId: string) {
  return {
    sku_id: skuId,
    competitor_min_price: 0,
    competitor_avg_price: 0,
    price_gap_pct: 0,
    competitors_on_sale_count: 0,
    competitors_out_of_stock_count: 0,
    num_competitors_tracked: 0,
    cheapest_competitor_name: 'none',
    price_trend_direction: 'flat' as const,
    data_freshness_hours: 0,
    confidence_score: 0,
    fallback_used: true,
    fallback_reason: 'No live competitor signal provided.',
    match_type: 'no_match',
    match_score: 0,
    timestamp: new Date().toISOString(),
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
function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    chunks.push(items.slice(i, i + size));
  }
  return chunks;
}

async function apiError(response: Response, label: string) {
  try {
    const payload = await response.json();
    return `${label} ${response.status}: ${payload.detail || response.statusText}`;
  } catch {
    return `${label} ${response.status}: ${response.statusText}`;
  }
}

// ─── Outcome Tracking ─────────────────────────────────────────────────────────

export async function fetchOutcomes(variantId: string): Promise<OutcomeSnapshot[]> {
  const { base } = settings();
  const r = await fetch(`${base}/outcomes/${encodeURIComponent(variantId)}`, { headers: apiHeaders() });
  if (r.status === 503) return [];
  if (!r.ok) throw new Error(await apiError(r, `EEP /outcomes/${variantId}`));
  return r.json();
}

export async function fetchOutcomesBySku(skuId: string): Promise<OutcomeSnapshot[]> {
  const { base } = settings();
  const r = await fetch(`${base}/outcomes/by-sku/${encodeURIComponent(skuId)}`, { headers: apiHeaders() });
  if (r.status === 503) return [];
  if (!r.ok) throw new Error(await apiError(r, `EEP /outcomes/by-sku/${skuId}`));
  return r.json();
}

export async function triggerMeasurement(
  snapshotId: number,
  windowDays: 7 | 14,
): Promise<unknown> {
  const { base } = settings();
  const r = await fetch(`${base}/outcomes/${snapshotId}/measure`, {
    method: 'POST',
    headers: apiHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ window_days: windowDays }),
  });
  if (!r.ok) throw new Error(await apiError(r, `EEP POST /outcomes/${snapshotId}/measure`));
  return r.json();
}

export async function fetchDailySeries(snapshotId: number): Promise<DailySalesPoint[]> {
  const { base } = settings();
  const r = await fetch(`${base}/outcomes/${snapshotId}/daily-series`, { headers: apiHeaders() });
  if (r.status === 503) return [];
  if (!r.ok) throw new Error(await apiError(r, `EEP /outcomes/${snapshotId}/daily-series`));
  return r.json();
}

export async function fetchPortfolioAccuracy(decisionType?: string): Promise<PortfolioAccuracy> {
  const { base } = settings();
  const params = decisionType ? `?decision_type=${encodeURIComponent(decisionType)}` : '';
  const r = await fetch(`${base}/outcomes/portfolio/accuracy${params}`, { headers: apiHeaders() });
  if (r.status === 503) return { avg_accuracy: null, decision_count: 0, by_type: {} };
  if (!r.ok) throw new Error(await apiError(r, 'EEP /outcomes/portfolio/accuracy'));
  return r.json();
}

// ─── Financial detail fetchers ────────────────────────────────────────────────

export async function fetchDetailedBalanceSheet(): Promise<DetailedBalanceSheet> {
  const { base } = settings();
  const r = await fetch(`${base}/financial/balance-sheet`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(`/financial/balance-sheet ${r.status}`);
  return r.json();
}

export async function fetchDetailedProfitability(): Promise<DetailedProfitability> {
  const { base } = settings();
  const r = await fetch(`${base}/financial/profitability`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(`/financial/profitability ${r.status}`);
  return r.json();
}

export interface CashflowMonth { month: string; in: number; out: number; net: number }

export async function fetchCashflow(): Promise<CashflowMonth[]> {
  const { base } = settings();
  const r = await fetch(`${base}/financial/cashflow`, { headers: apiHeaders() });
  if (!r.ok) throw new Error(`/financial/cashflow ${r.status}`);
  const json = await r.json();
  // backend wraps series in { series: [...] }, unwrap if needed
  return Array.isArray(json) ? json : (json.series ?? []);
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
