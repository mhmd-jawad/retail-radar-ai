// Retail Radar AI - Domain models mirroring the Python analytics engine output

export type Decision = 'HOLD' | 'MARKDOWN' | 'PROMOTE' | 'CLEAR';
export type RecommendationStatus = 'pending' | 'approved' | 'edited' | 'rejected' | 'snoozed';

// ── Human Validation Layer ──────────────────────────────────────────────────
export type ReviewAction = 'accept' | 'override' | 'reject';

export interface RecommendationReview {
  id: string;
  tenant_id: string;
  sku_id: string;
  variant_id?: string | null;
  recommendation_id?: string | null;
  system_decision_run_id?: string | null;
  system_recommendation: Decision;
  system_confidence?: number | null;
  system_suggested_price_usd?: number | null;
  system_suggested_discount_pct?: number | null;
  model_version?: string | null;
  rule_override?: string | null;
  fallback_used: boolean;
  requires_human_approval: boolean;
  context_features?: Record<string, unknown> | null;
  model_metadata?: Record<string, unknown> | null;
  review_action: ReviewAction;
  final_decision?: Decision | null;
  final_price_usd?: number | null;
  final_discount_pct?: number | null;
  review_note?: string | null;
  is_override: boolean;
  agrees_with_system: boolean;
  reviewer_email?: string | null;
  reviewer_role?: string | null;
  reviewed_via?: string | null;
  revision: number;
  reviewed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  product_name?: string | null;
  brand?: string | null;
  category?: string | null;
}

export interface ReviewSubmitInput {
  action: ReviewAction;
  final_decision?: Decision | null;
  final_price_usd?: number | null;
  final_discount_pct?: number | null;
  note?: string | null;
  recommendation_id?: string | null;
}

export interface ReviewAnalyticsByDecision {
  system_recommendation: Decision;
  model_version: string;
  total_reviews: number;
  accept_count: number;
  override_count: number;
  reject_count: number;
  acceptance_rate: number | null;
  override_rate: number | null;
  agreement_rate: number | null;
}

export interface ReviewAnalyticsTrendPoint {
  week: string;
  total_reviews: number;
  acceptance_rate: number | null;
  override_rate: number | null;
}

export interface ReviewAnalytics {
  total_reviews: number;
  accept_count: number;
  override_count: number;
  reject_count: number;
  acceptance_rate: number | null;
  override_rate: number | null;
  agreement_rate: number | null;
  by_decision: ReviewAnalyticsByDecision[];
  trend: ReviewAnalyticsTrendPoint[];
  model_version?: string | null;
}
export type PricePosition = 'premium' | 'above_market' | 'at_market' | 'below_market' | 'deep_value';
export type DataMode = 'mock-report' | 'ie2-live' | 'eep-live' | 'supabase-ready';

export interface AuthUser {
  user_id: string;
  email: string;
  full_name: string;
  global_role: 'admin' | 'shop';
  tenant_id?: string | null;
  tenant_slug?: string | null;
  tenant_name?: string | null;
  member_role?: 'owner' | 'manager' | 'staff' | null;
  read_only?: boolean;
  impersonated_by_email?: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: 'bearer';
  user: AuthUser;
}

export interface CompetitorOption {
  shop_code: string;
  shop_name: string;
  is_active?: boolean;
}

export interface CompetitorRequest {
  id: string;
  tenant_id?: string;
  shop_name?: string;
  competitor_name: string;
  website_url?: string | null;
  status: 'pending' | 'approved' | 'rejected' | 'onboarded';
  requested_by_email?: string | null;
  admin_notes?: string | null;
  created_at: string;
  reviewed_at?: string | null;
}

export interface AdminTenant {
  id: string;
  name: string;
  slug: string;
  contact_email?: string | null;
  phone?: string | null;
  onboarding_status?: string | null;
  sku_count: number;
  competitor_count: number;
  created_at: string;
}

export interface AppNotification {
  id: string;
  recipient_role: 'admin' | 'shop';
  recipient_user_id?: string | null;
  tenant_id?: string | null;
  shop_name?: string | null;
  shop_slug?: string | null;
  actor_user_id?: string | null;
  actor_email?: string | null;
  actor_name?: string | null;
  type: 'competitor_request' | 'setup_help' | 'billing' | 'system' | string;
  title: string;
  message: string;
  payload: Record<string, unknown>;
  status: 'unread' | 'read' | 'resolved' | 'dismissed';
  priority: 'low' | 'normal' | 'high' | 'urgent';
  created_at: string;
  read_at?: string | null;
  resolved_at?: string | null;
}

export interface ShopProfile {
  tenant_id: string;
  tenant_slug: string;
  business_name: string;
  legal_name?: string | null;
  contact_email?: string | null;
  phone?: string | null;
  website_url?: string | null;
  address?: string | null;
  country: string;
  timezone: string;
  onboarding_status: 'pending' | 'active' | 'suspended' | 'archived';
  selected_competitors: CompetitorOption[];
  competitor_requests: CompetitorRequest[];
}

export interface ShopSignupInput {
  owner_name: string;
  email: string;
  password: string;
  shop_name: string;
  legal_name?: string | null;
  phone?: string | null;
  website_url?: string | null;
  address?: string | null;
  country?: string;
  timezone?: string;
  selected_competitor_codes: string[];
  requested_competitor_names: string[];
}

export interface ShopProfileInput {
  business_name?: string | null;
  legal_name?: string | null;
  phone?: string | null;
  website_url?: string | null;
  address?: string | null;
  country?: string | null;
  timezone?: string | null;
  selected_competitor_codes?: string[];
  requested_competitor_names?: string[];
}

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
  sku_id?: string;
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
  match_type?: string;
  match_score?: number;
  timestamp: string;
}

export interface MarketOverview {
  skus_tracked: number;
  competitor_records: number | null;
  shops_covered: number | null;
  avg_price_gap_pct: number | null;
  overpriced_skus: number | null;
  underpriced_skus: number | null;
  at_market_skus: number | null;
  data_freshness_hours: number | null;
  status?: 'connected' | 'not_connected';
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
  instagram_post: string;
  facebook_post: string;
  telegram_broadcast: string;
  cta_primary: string;
  cta_secondary: string;
  image_url: string;
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
  product_name?: string;
  brand?: string;
  category?: string;
  retail_price_usd?: number;
  cost_price_usd?: number;
  current_stock?: number;
  days_since_launch?: number;
  initial_stock?: number;
  days_since_last_discount?: number;
  days_at_current_price?: number;
  competitor_signals?: CompetitorSignals;
}

export interface IE2Result {
  sku_id?: string;
  product_name?: string;
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
  competitor_signals_used?: CompetitorSignals | null;
  input_context?: IE2Request | null;
  error?: string;
  status_code?: number;
}

export type SystemDecisionLatestStatus = 'pending' | 'syncing' | 'live' | 'error';
export type SystemDecisionRunStatus = 'queued' | 'running' | 'completed' | 'partial' | 'failed';

export interface SystemDecisionLatestItem {
  tenant_id?: string;
  sku_id: string;
  variant_id?: string | null;
  run_id?: string | null;
  status: SystemDecisionLatestStatus;
  recommendation?: Decision | null;
  confidence?: number | null;
  model_version?: string | null;
  rule_override?: string | null;
  fallback_used?: boolean;
  requires_human_approval?: boolean;
  suggested_price_usd?: number | null;
  suggested_discount_pct?: number | null;
  decision_payload?: IE2Result | null;
  input_context?: IE2Request | null;
  competitor_signals?: CompetitorSignals | null;
  error_stage?: string | null;
  error_code?: string | null;
  error_detail?: string | null;
  sync_trigger?: string | null;
  synced_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  product_name?: string | null;
  brand?: string | null;
  category?: string | null;
}

export interface SystemDecisionSummary {
  active_skus: number;
  tracked_skus: number;
  live_count: number;
  error_count: number;
  syncing_count: number;
  unsynced_count: number;
  status_counts: Record<string, number>;
}

export interface SystemDecisionRun {
  id: string;
  tenant_id?: string;
  trigger: string;
  status: SystemDecisionRunStatus;
  total_count: number;
  completed_count: number;
  failed_count: number;
  summary_error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
  already_running?: boolean;
}

export interface SystemDecisionLatestResponse {
  items: SystemDecisionLatestItem[];
  summary: SystemDecisionSummary;
  latest_run?: SystemDecisionRun | null;
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
  supplier_name?: string | null;
  notes?: string | null;
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

export type RetailInventoryMovementType =
  | 'sale'
  | 'purchase_receipt'
  | 'return'
  | 'adjustment_in'
  | 'adjustment_out'
  | 'damaged';

export interface RetailInventoryMovementInput {
  movement_type: RetailInventoryMovementType;
  quantity: number;
  unit_price_usd?: number | null;
  unit_cost_usd?: number | null;
  discount_pct?: number;
  channel?: string;
  reference_id?: string | null;
  notes?: string | null;
  sold_at?: string | null;
}

export interface RetailInventoryMovementResult {
  item: RetailInventoryItem;
  movement: {
    id: string;
    movement_type: RetailInventoryMovementType;
    quantity_delta: number;
    quantity_before: number;
    quantity_after: number;
    unit_cost_usd?: number | null;
    reference_type?: string | null;
    reference_id?: string | null;
    notes?: string | null;
    created_by: string;
    created_at: string;
  };
  sale?: {
    id: string;
    line_id: string;
    sold_at: string;
    quantity: number;
    unit_price_usd: number;
    discount_pct: number;
    total_amount_usd: number;
    channel: string;
  } | null;
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
  missing_snapshot?: boolean;
  period_month?: string | null;
  assets: {
    inventory_at_cost_usd: number;
    inventory_at_retail_usd: number;
    cash_on_hand_usd: number;
    bank_balance_usd: number;
    receivables_usd: number;
    equipment_fixtures_usd: number;
    other_assets_usd: number;
    total_usd: number;
  };
  liabilities: {
    supplier_payables_usd: number;
    rent_payable_usd: number;
    salary_payable_usd: number;
    loan_balance_usd: number;
    tax_vat_payable_usd: number;
    customer_deposits_usd: number;
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

export interface FinancialSnapshot {
  id?: string;
  period_month: string;
  currency?: 'USD';
  cash_on_hand_usd: number;
  bank_balance_usd: number;
  receivables_usd: number;
  inventory_at_cost_usd?: number;
  equipment_fixtures_usd: number;
  other_assets_usd: number;
  supplier_payables_usd: number;
  rent_payable_usd: number;
  salary_payable_usd: number;
  loan_balance_usd: number;
  tax_vat_payable_usd: number;
  customer_deposits_usd: number;
  other_liabilities_usd: number;
  monthly_sales_usd: number;
  monthly_expenses_usd: number;
  owner_draw_usd: number;
  notes?: string | null;
  total_cash_usd?: number;
  total_entered_assets_usd?: number;
  total_entered_liabilities_usd?: number;
}

export interface FinancialProgressPoint {
  period_month: string;
  total_assets_usd: number;
  total_liabilities_usd: number;
  equity_usd: number;
  cash_runway_months: number;
  inventory_pct_of_assets: number;
  debt_to_equity: number;
  monthly_sales_usd: number;
  monthly_expenses_usd: number;
  owner_draw_usd: number;
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

// ─── Admin Platform Operations Types ─────────────────────────────────────────

export interface AdminFinancialTenantScore {
  tenant_id: string;
  tenant_name: string;
  score: number;
  cash_runway_months: number;
  current_ratio: number;
  margin_pct: number;
  last_snapshot: string | null;
  status: 'healthy' | 'watch' | 'at_risk';
}

export interface AdminSnapshotCoverage {
  tenant_id: string;
  tenant_name: string;
  submitted_months: string[];
}

export interface AdminFinancialOverview {
  active_shops: number;
  shops_at_risk: number;
  avg_margin_pct: number;
  missing_snapshots_this_month: number;
  at_risk_shops: AdminFinancialTenantScore[];
  health_scores: AdminFinancialTenantScore[];
  margin_trend: { month: string; avg_margin_pct: number }[];
  snapshot_coverage: AdminSnapshotCoverage[];
}

export interface AdminCampaignTenantRow {
  tenant_id: string;
  tenant_name: string;
  total: number;
  last_30d: number;
  most_used_channel: string | null;
  last_campaign_at: string | null;
}

export interface AdminCampaignRecentItem {
  tenant_name: string;
  product_name: string;
  channel: string;
  headline: string;
  tone: string;
  confidence_pct: number;
  fallback_used: boolean;
  created_at: string;
}

export interface AdminCampaignsOverview {
  total_campaigns: number;
  last_30_days: number;
  avg_confidence_pct: number;
  fallback_rate_pct: number;
  channels_live: number;
  by_channel: Record<string, number>;
  by_decision_type: Record<string, number>;
  fallback_trend: { date: string; fallback_rate_pct: number }[];
  per_tenant: AdminCampaignTenantRow[];
  recent: AdminCampaignRecentItem[];
}

export interface AdminAssistantMessage {
  role: 'user' | 'assistant';
  content: string;
  tools_used?: string[];
}

export interface FinancialProfileInput {
  total_assets_usd: number | null;
  total_liabilities_usd: number | null;
  monthly_fixed_opex_usd: number | null;
  annual_revenue_projected_usd: number | null;
  cash_runway_months: number | null;
  breakeven_monthly_revenue_usd: number | null;
}

export interface FinancialLineItem {
  id: string;
  item_type: 'asset' | 'liability';
  label: string;
  amount_usd: number;
  sort_order: number;
}
