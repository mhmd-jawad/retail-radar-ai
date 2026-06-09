-- Migration 008: Human Validation Layer
--
-- Adds a final human-review stage AFTER the system recommendation is generated.
-- The original system recommendation (marketing.recommendations /
-- marketing.system_decision_latest) is NEVER modified — every review snapshots it
-- immutably so the data can later serve as ground-truth labels for retraining,
-- evaluation, analytics and auditing.
--
-- Idempotent and additive: applied automatically through eep.retail_db's
-- _ensure_additive_schema mechanism (ADDITIVE_SCHEMA_PATHS), so it runs on first
-- connect against the live RDS with no manual deploy step.

create schema if not exists marketing;

-- ─── Review record (current state, one per SKU) ──────────────────────────────
create table if not exists marketing.recommendation_reviews (
    id                          uuid primary key default gen_random_uuid(),
    tenant_id                   uuid not null references core.tenants(id) on delete cascade,
    sku_id                      text not null,
    variant_id                  uuid references core.sku_variants(id) on delete set null,
    recommendation_id           uuid references marketing.recommendations(id) on delete set null,
    system_decision_run_id      uuid,  -- soft reference; marketing.system_decision_runs may not exist on all deployments

    -- ── System snapshot — frozen at review time, never overwritten ───────────
    system_recommendation       text not null
        check (system_recommendation in ('HOLD','MARKDOWN','PROMOTE','CLEAR')),
    system_confidence           numeric(6,4),
    system_suggested_price_usd  numeric(12,2),
    system_suggested_discount_pct numeric(6,2),
    model_version               text,
    rule_override               text,
    fallback_used               boolean not null default false,
    requires_human_approval     boolean not null default false,

    -- ── Full context snapshot for retraining/reconstruction (no app logic) ───
    context_features            jsonb not null default '{}'::jsonb,
    model_metadata              jsonb not null default '{}'::jsonb,

    -- ── Human decision ──────────────────────────────────────────────────────
    review_action               text not null
        check (review_action in ('accept','override','reject')),
    final_decision              text
        check (final_decision is null or final_decision in ('HOLD','MARKDOWN','PROMOTE','CLEAR')),
    final_price_usd             numeric(12,2),
    final_discount_pct          numeric(6,2),
    review_note                 text,

    -- ── Derived agreement signals ───────────────────────────────────────────
    is_override                 boolean not null default false,
    agrees_with_system          boolean not null default true,

    -- ── Reviewer identity ───────────────────────────────────────────────────
    reviewer_user_id            uuid references core.app_users(id) on delete set null,
    reviewer_email              text,
    reviewer_role               text,
    reviewed_via                text not null default 'web',

    -- ── Revision / audit bookkeeping ────────────────────────────────────────
    revision                    integer not null default 1,
    reviewed_at                 timestamptz not null default now(),
    created_at                  timestamptz not null default now(),
    updated_at                  timestamptz not null default now(),

    -- One current review per SKU per tenant; history lives in the history table.
    unique (tenant_id, sku_id)
);

create index if not exists idx_rec_reviews_tenant_reviewed
    on marketing.recommendation_reviews (tenant_id, reviewed_at desc);

create index if not exists idx_rec_reviews_tenant_sku
    on marketing.recommendation_reviews (tenant_id, sku_id);

create index if not exists idx_rec_reviews_tenant_model
    on marketing.recommendation_reviews (tenant_id, model_version);

create index if not exists idx_rec_reviews_tenant_action
    on marketing.recommendation_reviews (tenant_id, review_action, reviewed_at desc);

comment on table marketing.recommendation_reviews is
    'Human validation layer: final human review of each system recommendation. '
    'System snapshot columns are frozen at review time and never overwritten.';
comment on column marketing.recommendation_reviews.context_features is
    'Snapshot of the exact features/context fed to the decision system at review time '
    '(input_context + competitor_signals + decision_payload + SHAP). Used as retraining input.';
comment on column marketing.recommendation_reviews.final_decision is
    'Human ground-truth decision. NULL only for reject-without-alternative.';

-- ─── Append-only change history (full auditability) ──────────────────────────
create table if not exists marketing.recommendation_review_history (
    id                bigserial primary key,
    review_id         uuid not null references marketing.recommendation_reviews(id) on delete cascade,
    tenant_id         uuid not null references core.tenants(id) on delete cascade,
    revision          integer not null,
    action            text not null check (action in ('created','updated')),
    before_state      jsonb,
    after_state       jsonb,
    changed_by_user_id uuid references core.app_users(id) on delete set null,
    changed_by_email  text,
    change_reason     text,
    created_at        timestamptz not null default now()
);

create index if not exists idx_rec_review_history_review
    on marketing.recommendation_review_history (review_id, revision);

create index if not exists idx_rec_review_history_tenant_created
    on marketing.recommendation_review_history (tenant_id, created_at desc);

comment on table marketing.recommendation_review_history is
    'Append-only audit trail of every create/edit applied to a recommendation review.';

-- ─── Retraining label view (ML pipelines query this directly) ────────────────
-- ground_truth_label resolves to the human decision; for an accept it is the
-- system recommendation; for a reject-without-alternative it is NULL (excluded
-- from supervised label sets but still available for analysis).
create or replace view marketing.v_recommendation_training_labels as
select
    r.id                            as review_id,
    r.tenant_id,
    r.sku_id,
    r.variant_id,
    r.context_features,
    r.system_recommendation,
    coalesce(
        r.final_decision,
        case when r.review_action = 'accept' then r.system_recommendation else null end
    )                               as ground_truth_label,
    r.review_action,
    r.is_override,
    r.agrees_with_system,
    r.final_price_usd,
    r.final_discount_pct,
    r.model_version,
    r.rule_override,
    r.fallback_used,
    r.system_confidence,
    r.reviewer_email,
    r.reviewed_at
from marketing.recommendation_reviews r;

comment on view marketing.v_recommendation_training_labels is
    'Retraining dataset: human-reviewed ground-truth labels joined with the exact '
    'context features fed to the system. Consume directly — no app reconstruction needed.';

-- ─── Analytics view (acceptance / override / agreement by model & decision) ──
create or replace view marketing.v_recommendation_review_analytics as
select
    r.tenant_id,
    coalesce(r.model_version, 'unknown') as model_version,
    r.system_recommendation,
    count(*)                                                          as total_reviews,
    count(*) filter (where r.review_action = 'accept')               as accept_count,
    count(*) filter (where r.review_action = 'override')             as override_count,
    count(*) filter (where r.review_action = 'reject')               as reject_count,
    round(avg((r.review_action = 'accept')::int)::numeric, 4)        as acceptance_rate,
    round(avg((r.is_override)::int)::numeric, 4)                     as override_rate,
    round(avg((r.agrees_with_system)::int)::numeric, 4)             as agreement_rate,
    min(r.reviewed_at)                                               as first_reviewed_at,
    max(r.reviewed_at)                                               as last_reviewed_at
from marketing.recommendation_reviews r
group by r.tenant_id, coalesce(r.model_version, 'unknown'), r.system_recommendation;

comment on view marketing.v_recommendation_review_analytics is
    'Aggregate human-vs-system agreement metrics per tenant, model version and decision class.';
