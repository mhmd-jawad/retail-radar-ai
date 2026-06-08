Architecture Overview
=====================

StylePulse AI is a microservices system with a React dashboard and a Telegram
bot as the two primary user interfaces.

Request Flow
------------

1. The shop owner opens the **React dashboard** or sends a message to the
   **Telegram assistant**.
2. Both clients call the **EEP orchestrator** (port 8000).
3. EEP fans out to **IE1** (competitor signals) and **IE2** (ML decision) in
   parallel, then optionally calls **IE3** (campaign creative) when the
   decision is ``PROMOTE``.
4. The assembled recommendation is persisted in PostgreSQL and returned to the
   client.

Offline Pipeline
----------------

The **StylePulse Engine** runs separately (on a schedule or on demand) to
process flat CSV data and produce a ``report.json`` advisory. EEP's
``frontend_bridge`` reads this report when serving the dashboard.

Data Stores
-----------

- **PostgreSQL** — retail_core schema (products, inventory, prices, recommendations),
  intel_scraping schema (competitor records), marketing schema (auth, tenants).
- **MLflow** — experiment tracking and model registry for IE2.
- **Flat files** — ``data/real/*.csv`` and ``data/reports/report.json`` for the
  StylePulse offline pipeline.

Deployment
----------

See the ``docs/`` directory for operational guides:

- ``full-stack-docker-deployment.md`` — Docker Compose local stack
- ``KUBERNETES_DEPLOYMENT.md`` — Production Kubernetes manifests
- ``monitoring-prometheus-grafana.md`` — Metrics and alerting setup
- ``aws-rds-apify-webhook.md`` — Cloud RDS and Apify integration
