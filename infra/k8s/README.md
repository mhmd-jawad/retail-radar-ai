# infra/k8s — Kubernetes manifests for Retail Radar AI

Full walkthrough: [../../docs/KUBERNETES_DEPLOYMENT.md](../../docs/KUBERNETES_DEPLOYMENT.md).

## Layout
| File | What it creates |
|---|---|
| `00-namespace.yaml` | the `retail-radar` namespace |
| `00-config.yaml` | `retail-config` ConfigMap (non-secret env: service URLs, tenant, admin email, WEBHOOK_DOMAIN) |
| `10-pgbouncer.yaml` | PgBouncer ×2 in front of RDS (`pgbouncer:6432`) |
| `20-backends.yaml` | IE1 ×2, IE2 (HPA 2→3 + PDB), IE3 ×2, EEP (HPA 2→4 + PDB) |
| `30-frontend-telegram.yaml` | Frontend ×2; Telegram ×1 (starts at `replicas: 0`) |
| `40-ingress.yaml` | Traefik routes: `/api`→EEP, `/apify`+`/webhooks`→EEP, `/webhook/telegram`→Telegram, `/ie1,2,3`→IEs, `/`→SPA |
| `50-monitoring.yaml` | Prometheus + Grafana (scrapes EEP + IE2 `/metrics`) |
| `kustomization.yaml` | ties it together + pins image tags |
| `edge/Caddyfile` | **alternative** (guide Appendix D) — only if you skip the Lightsail LB and reuse the 2 GB box as the edge |

## Deploy (short form — see the guide for details)
```bash
# 1. Secrets (NOT in git):
kubectl create secret docker-registry ghcr-creds --docker-server=ghcr.io \
  --docker-username=mhmd-jawad --docker-password="$CR_PAT" -n retail-radar
kubectl create secret generic retail-secrets   --from-env-file=k8s.env       -n retail-radar
kubectl create secret generic pgbouncer-secret --from-env-file=pgbouncer.env -n retail-radar

# 2. Set the image tag in kustomization.yaml (images: newTag), then:
kubectl apply -k infra/k8s/

# 3. Watch:
kubectl -n retail-radar get pods -o wide -w
```

> The namespace is created by `00-namespace.yaml`, but the three secrets must exist
> **before** `apply -k` (pods won't start without them). Create the namespace first if
> needed: `kubectl create namespace retail-radar`.
