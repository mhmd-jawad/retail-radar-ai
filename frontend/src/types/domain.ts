// Retail Radar AI - Domain models mirroring the Python analytics engine output
// and IE2/EEP service contracts.

export type Decision = 'HOLD' | 'MARKDOWN' | 'PROMOTE' | 'CLEAR';
export type RecommendationStatus = 'pending' | 'approved' | 'edited' | 'rejected' | 'snoozed';
export type PricePosition = 'premium' | 'above_market' | 'at_market' | 'below_market' | 'deep_value';
export type DataMode = 'mock-report' | 'ie2-live' | 'eep-live' | 'supabase-ready';

export interface InventoryMetrics {
  total_skus: number;
  total_units: number;
  inventory_value_at_cost_usd: number;
  inventory_value_at_retail_usd: number;
  blended_margin_pct: number;
  median_days_of_supply: number;
  critical_stockouts: number;
  dead_stock_skus: number;
  excess_stock_skus: number;
  healthy_skus: number;
}

export interface SkuAnalysis {
  sku_id: string;
  product_name: string;
  brand: string;
  category: string;
  current_stock: number;
  initial_stock: number;
  retail_price_usd: number;
  cost_price_usd: number;
  margin_pct: number;
  days_of_supply: number;
  days_since_launch: number;
  days_since_last_discount: number;
  days_at_current_price: number;
  velocity_units_per_day: number;
  health: 'critical' | 'healthy' | 'excess' | 'dead';
  decision: Decision;
}

export interface CategorySummary {
  [category: string]: {
    skus: number;
    units: number;
    value_usd: number;
    avg_margin_pct: number;
    median_dos: number;
    health_score: number;
  };
}

export interface Alert {
  id: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  title: string;
  detail: string;
  category?: string;
  sku_id?: string;
  created_at: string;
}

export interface CompetitorSignals {
  competitor_min_price: number;
  competitor_avg_price: number;
  price_gap_pct: number;
  competitors_on_sale_count: number;
  competitors_out_of_stock_count: number;
  num_competitors_tracked: number;
  cheapest_competitor_name: string;
  price_trend_direction: 'up' | 'down' | 'flat';
  data_freshness_hours: number;
  confidence_score: number;
  fallback_used: boolean;
  fallback_reason?: string;
  timestamp: string;
}

export interface MarketOverview {
  skus_tracked: number;
  competitor_records: number;
  shops_covered: number;
  avg_price_gap_pct: number;
  overpriced_skus: number;
  underpriced_skus: number;
  at_market_skus: number;
  data_freshness_hours: number;
}

export interface SkuPositioning {
  sku_id: string;
  product_name: string;
  brand: string;
  category: string;
  our_price_usd: number;
  market_min_usd: number;
  market_avg_usd: number;
  price_gap_pct: number;
  position: PricePosition;
  competitors_count: number;
  competitors_on_sale: number;
  cheapest_shop: string;
}

export interface BrandSummary {
  [brand: string]: { skus: number; avg_gap_pct: number; position: PricePosition; coverage: number };
}

export interface CompetitorOpportunity {
  sku_id: string;
  product_name: string;
  brand: string;
  type: 'undercut' | 'raise' | 'match' | 'promote';
  current_price_usd: number;
  suggested_price_usd: number;
  est_uplift_usd: number;
  rationale: string;
}

export interface BalanceSheetHealth {
  current_ratio: number;
  inventory_pct_of_assets: number;
  inventory_concentration_top5_pct: number;
  total_assets_usd: number;
  liabilities_usd: number;
  equity_usd: number;
}

export interface CashflowHealth {
  cash_runway_months: number;
  monthly_burn_usd: number;
  monthly_cash_in_usd: number;
  cash_on_hand_usd: number;
  lollar_exposure_pct: number;
  series: { month: string; in: number; out: number; net: number }[];
}

export interface Profitability {
  blended_margin_pct: number;
  breakeven_revenue_usd: number;
  annual_revenue_projection_usd: number;
  opex_coverage_ratio: number;
}

export interface SocialPostResult {
  platform: string;
  success: boolean;
  post_id?: string;
  post_url?: string;
  error?: string;
}

export interface CampaignCreative {
  headline: string;
  subheadline: string;
  ad_copy_short: string;
  ad_copy_long: string;
  instagram_post: string;   // maps from instagram_caption
  facebook_post: string;
  whatsapp_broadcast: string;
  cta_primary: string;
  cta_secondary: string;
  image_url: string;        // from ImgBB / Replicate
  tone_used: 'urgent' | 'aspirational' | 'value_focused';
  generation_confidence: number;
  fallback_used: boolean;
  social_posts: SocialPostResult[];
}

export interface PromoteItem {
  sku_id: string;
  product_name: string;
  brand: string;
  category: string;
  reason: string;
  expected_lift_pct: number;
  channels: string[];
  creative?: CampaignCreative;
}

export interface MarkdownItem {
  sku_id: string;
  product_name: string;
  brand: string;
  current_price_usd: number;
  suggested_discount_pct: number;
  suggested_price_usd: number;
  margin_after_pct: number;
  reason: string;
  urgency: 'low' | 'medium' | 'high';
}

export interface ClearanceItem {
  sku_id: string;
  product_name: string;
  brand: string;
  current_stock: number;
  age_days: number;
  suggested_price_usd: number;
  recovered_cash_usd: number;
  urgency: 'medium' | 'high' | 'critical';
}

export interface HoldPricingItem {
  sku_id: string;
  product_name: string;
  brand: string;
  reason: string;
  margin_pct: number;
  velocity: number;
}

export interface SeasonalAction {
  month: string;
  action: string;
  category: string;
  detail: string;
}

export interface Directive {
  owner: 'Buying' | 'Marketing' | 'Operations' | 'Finance';
  title: string;
  detail: string;
  priority: 'high' | 'medium' | 'low';
}

export interface PromotionsSummary {
  hold_count: number;
  promote_count: number;
  markdown_count: number;
  clearance_count: number;
}

export interface ReportMetadata {
  generated_at: string;
  engine_version: string;
  market: string;
  currency: string;
  data_window_days: number;
  source: string;
}

export interface Report {
  inventory: {
    metrics: InventoryMetrics;
    sku_analysis: SkuAnalysis[];
    category_summary: CategorySummary;
    alerts: Alert[];
  };
  competitor: {
    market_overview: MarketOverview;
    sku_positioning: SkuPositioning[];
    brand_summary: BrandSummary;
    category_summary: { [k: string]: { skus: number; avg_gap_pct: number } };
    opportunities: CompetitorOpportunity[];
  };
  financial: {
    balance_sheet_health: BalanceSheetHealth;
    cashflow_health: CashflowHealth;
    profitability: Profitability;
    alerts: Alert[];
  };
  promotions: {
    hold_pricing: HoldPricingItem[];
    promote: PromoteItem[];
    markdown: MarkdownItem[];
    clearance: ClearanceItem[];
    seasonal_actions: SeasonalAction[];
    directives: Directive[];
    summary: PromotionsSummary;
  };
  metadata: ReportMetadata;
}

// IE2 contracts
export interface IE2Request {
  sku_id: string;
  product_name: string;
  brand: string;
  category: string;
  retail_price_usd: number;
  cost_price_usd: number;
  current_stock: number;
  days_since_launch: number;
  initial_stock: number;
  days_since_last_discount: number;
  days_at_current_price: number;
  competitor_signals: CompetitorSignals;
}

export interface IE2Result {
  recommendation: Decision;
  confidence: number;
  explanation: string;
  shap_top5: { feature: string; impact: number; direction: 'positive' | 'negative' }[];
  rule_override?: string | null;
  fallback_used: boolean;
  suggested_discount_pct?: number;
  suggested_price_usd?: number;
  margin_after_action_pct?: number;
  model_version: string;
  processing_time_ms: number;
  requires_human_approval: boolean;
}

// EEP future
export interface EEPRecommendationPackage {
  sku_id: string;
  ie2_result: IE2Result;
  campaign_creative?: CampaignCreative;
  status: RecommendationStatus;
  reviewer?: string;
  reviewed_at?: string;
}

// Supabase future shapes
export interface ScrapeRun {
  id: string;
  shop: string;
  started_at: string;
  finished_at?: string;
  status: 'running' | 'success' | 'failed' | 'partial';
  items_scraped: number;
  valid_rows: number;
  error?: string;
}

export interface CompetitorProductLatest {
  shop: string;
  external_id: string;
  product_name: string;
  brand: string;
  price_usd: number;
  on_sale: boolean;
  in_stock: boolean;
  url: string;
  last_seen: string;
}

// Retail core inventory DB
export interface RetailInventoryItem {
  product_id: string;
  variant_id: string;
  sku_id: string;
  product_name: string;
  brand: string;
  category: string;
  current_stock: number;
  retail_price_usd: number;
  cost_price_usd: number;
  margin_pct: number;
  stock_value_usd: number;
  reorder_point: number;
  reorder_quantity: number;
  needs_reorder: boolean;
  barcode?: string | null;
  style_code?: string | null;
  color?: string | null;
  size?: string | null;
  gender_target?: string | null;
  season?: string | null;
  updated_at?: string;
}

export interface RetailInventoryInput {
  sku_id: string;
  product_name: string;
  brand: string;
  category: string;
  current_stock: number;
  retail_price_usd: number;
  cost_price_usd: number;
  barcode?: string | null;
  style_code?: string | null;
  color?: string | null;
  size?: string | null;
  gender_target?: string | null;
  season?: string | null;
  reorder_point?: number;
  reorder_quantity?: number;
  supplier_name?: string | null;
  notes?: string | null;
}

export interface RetailInventorySummary {
  total_skus: number;
  total_units: number;
  inventory_value_at_cost_usd: number;
  inventory_value_at_retail_usd: number;
  reorder_count: number;
  categories: string[];
}

export interface RetailInventoryResponse {
  items: RetailInventoryItem[];
  summary: RetailInventorySummary;
}

export interface RetailInventoryImportResult extends RetailInventoryResponse {
  imported: number;
  archived: number;
}

export interface RetailDbStatus {
  connected: boolean;
  database_url_hint: string;
  tenant: string;
  store: string;
  item_count?: number;
  schema_auto_init?: string;
  error?: string;
}

// ─── Financial Detail types (Step 2) ─────────────────────────────────────────

export interface OpExItem {
  label: string;
  amount_usd: number;
  type: 'fixed' | 'variable';
  rate_pct?: number;
}

export interface CategoryProfitability {
  category: string;
  sku_count: number;
  revenue_usd: number;
  cogs_usd: number;
  margin_pct: number;
}

export interface DetailedBalanceSheet {
  data_source: 'live-db' | 'static-file';
  generated_at: string;
  assets: {
    inventory_at_cost_usd: number;
    inventory_at_retail_usd: number;
    cash_on_hand_usd: number;
    lollar_face_usd: number;
    lollar_real_usd: number;
    other_assets_usd: number;
    total_usd: number;
  };
  liabilities: {
    supplier_payables_usd: number;
    other_usd: number;
    total_usd: number;
  };
  equity_usd: number;
  ratios: {
    current_ratio: number;
    inventory_pct_of_assets: number;
    debt_to_equity: number;
    top5_concentration_pct: number;
  };
}

export interface DetailedProfitability {
  data_source: 'live-db' | 'static-file';
  generated_at: string;
  summary: Profitability;
  for_every_100_usd: {
    cogs: number;
    marketing: number;
    payment_processing: number;
    logistics: number;
    fixed_opex: number;
    net_profit: number;
  };
  opex_breakdown: OpExItem[];
  category_breakdown: CategoryProfitability[];
  breakeven: {
    monthly_fixed_opex_usd: number;
    blended_margin_pct: number;
    result_usd: number;
    plain_english: string;
    pairs_estimate?: number;
  };
}

// Audit
export interface AuditEntry {
  id: string;
  sku_id: string;
  product_name: string;
  decision: Decision;
  status: RecommendationStatus;
  actor: string;
  before?: { price_usd: number; discount_pct?: number };
  after?: { price_usd: number; discount_pct?: number };
  notes?: string;
  timestamp: string;
}
