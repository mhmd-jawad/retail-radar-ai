# Prometheus and Grafana Monitoring

StylePulse AI uses Prometheus and Grafana as standalone observability services beside the EEP backend.

## Local Run

```powershell
Copy-Item .env.example .env
docker compose -f infra\docker-compose.eep.yml up -d --build
```

- EEP API: `http://localhost:8000`
- EEP metrics: `http://localhost:8000/metrics`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001`

Grafana defaults come from `.env`:

```env
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=change_me
```

## What Is Monitored

- EEP HTTP request count, status codes, and latency.
- Recommendation decisions by action: `HOLD`, `MARKDOWN`, `PROMOTE`, `CLEAR`.
- Competitor matching outcomes: `exact_style`, `same_model_family`, `similar_product`, `no_match`.
- Apify scraper ingest success/failure.
- IE2 `/metrics` remains available and can be scraped when IE2 runs in the same Compose network.

## Frontend Relationship

Grafana remains the monitoring UI. The React dashboard includes a Monitoring link that opens Grafana in a new tab. The business frontend does not query Prometheus directly.

## Production Note

The AWS Compose file binds Prometheus and Grafana to `127.0.0.1` only. Access them through an SSH tunnel or place them behind protected authentication before exposing them publicly.
