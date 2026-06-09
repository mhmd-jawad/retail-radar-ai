-- Remove the retired Closed Loop / outcome tracking feature.
-- This is intentionally destructive per product direction.

alter table if exists telegram.recommendation_roadmaps
    drop column if exists outcome_snapshot_id,
    drop column if exists outcome_velocity_lift_pct,
    drop column if exists outcome_revenue_delta_usd;

drop table if exists outcome_tracking.outcome_measurements cascade;
drop table if exists outcome_tracking.decision_snapshots cascade;
drop table if exists outcome_tracking.closed_loop_notifications cascade;
drop schema if exists outcome_tracking cascade;
