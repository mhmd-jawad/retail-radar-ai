# Retail Radar AI — Kubernetes Deployment Guide (step-by-step)

**Audience:** you, deploying this project to the cloud with Kubernetes for the first time.
**Date:** 2026-06-07
**Plan:** keep your **existing 2 GB Lightsail box** as the public front door, add **2 new 4 GB boxes** as
a resilient k3s cluster, and run the whole app across them. **New spend ≈ $48/mo** (no Load Balancer to
buy, no domain to buy — your `sslip.io` URL and Apify webhook keep working unchanged).

This guide assumes **zero Kubernetes knowledge and zero AWS-server experience.** Every server-creation
click and every command is spelled out. The Kubernetes manifests are already written for you in
[../infra/k8s/](../infra/k8s/) — you mostly fill in secrets and run a few commands.

> **Companion docs:** [full-stack-docker-deployment.md](full-stack-docker-deployment.md) (current Compose
> deploy), [aws-rds-apify-webhook.md](aws-rds-apify-webhook.md) (RDS + Apify),
> [monitoring-prometheus-grafana.md](monitoring-prometheus-grafana.md) (Grafana dashboards).

---

## Part 0 — The whole plan on one screen

```
  Apify ──HTTPS──►  BOX A  (your existing 2 GB box, sslip.io)  ──►  RDS    [webhook — UNTOUCHED]

  Browser ──HTTPS──►  Lightsail Load Balancer  (yourdomain.com, managed cert)
                                │  HTTP :30080
                        ┌───────┴────────┐
                ┌───────▼──────┐  ┌──────▼───────┐
                │ BOX B (4 GB) │  │ BOX C (4 GB) │   ← 2 NEW boxes = the cluster
                │ k3s SERVER   │  │ k3s WORKER   │
                │ +Traefik+pods│  │ +Traefik     │
                └──────────────┘  └──────────────┘
                         ╲   one Kubernetes cluster   ╱
  Each service runs 2 copies, one per node, so a node can die with no downtime:
  eep ×2 · ie1 ×2 · ie2 ×2 · ie3 ×2 · frontend ×2 · pgbouncer ×2 · prom ×1 · grafana ×1
                                │
                         pgbouncer ──TLS──► Amazon RDS  (shared with Box A's webhook)
```

| Box | What it is | Cost |
|---|---|---|
| **Box A** | Your existing 2 GB box — **left completely untouched.** Keeps running the Apify webhook on its `sslip.io` domain, fully independent of the cluster. | $12/mo (already paying) |
| **Box B** | New 4 GB. k3s **server** (control plane + etcd + runs pods). | $24/mo (new) |
| **Box C** | New 4 GB. k3s **worker** (runs pods). | $24/mo (new) |
| **Load Balancer** | Lightsail LB — public HTTPS front door for the cluster's dashboard/API. | $18/mo (new) |

**New spend ≈ $67/mo** = 2 nodes ($48) + Lightsail LB ($18) + a cheap domain for the LB's HTTPS cert
(~$1/mo). Box A, RDS, Apify, and Claude are unchanged and already in your bill. The webhook pipeline
(Apify → Box A → RDS) is **completely separate** from the cluster, exactly as you wanted.

> **Why a worker, not 2 servers?** etcd (the cluster's database) needs an **odd** number of servers.
> 1 server is correct for 2 nodes; "2 servers" would lose quorum the moment one dies. Box B is the
> server; Box C is a worker. Both run your app pods, so the app survives a node failure. (For full
> control-plane HA later, add a 3rd box as a server — Appendix C.)

---

## Part 1 — Kubernetes in 90 seconds (only what you need)

| Word | Plain meaning |
|---|---|
| **Node** | One machine (Box B or Box C). |
| **Pod** | One running copy of a service (like one running container). |
| **Deployment** | "Keep N copies of this service alive; restart/reschedule if one dies." |
| **Replica** | One of those copies. "ie2 ×2" = two copies of IE2, placed on different nodes. |
| **Service** (k8s) | A stable internal name. `http://eep:8000` reaches the EEP pods from anywhere in the cluster. |
| **Ingress** (Traefik) | The in-cluster router that maps URL paths (`/api`, `/ie2`, …) to services. |
| **Secret / ConfigMap** | Where your env vars live (secret = passwords/keys; configmap = non-secret). |
| **kubectl** | The command you run from your laptop to drive the cluster. |

You **don't** assign a service to a server. You tell Kubernetes "run 2 copies, spread across nodes," and
it places them. If a node dies, the copies on the survivor keep serving and Kubernetes recreates the lost
ones. That resilience is the whole point.

---

## Part 2 — What runs, and how many copies

| Service | Port | Copies | Public path (through Caddy→Traefik) |
|---|---|---|---|
| **EEP** (orchestrator/API) | 8000 | 2 (autoscale→4) | `/api/*`, `/apify`, `/webhooks` |
| **Frontend** (React/nginx) | 80 | 2 | `/` (everything else) |
| **IE1** market_intelligence | 8001 | 2 | internal (`/ie1/*` if needed) |
| **IE2** decision_intelligence (model) | 8002 | 2 (autoscale→3) | `/ie2/*` (health/model check) |
| **IE3** campaign_creative | 8003 | 2 | `/ie3/*` |
| **Telegram** assistant | 8004 | **0** (turn on when ready) | `/webhook/telegram` |
| **PgBouncer** (RDS pool) | 6432 | 2 | internal |
| **Prometheus / Grafana** | 9090 / 3000 | 1 each | port-forward only |

All of this is already defined in [../infra/k8s/](../infra/k8s/) — you won't hand-write any of it.

---

## Part 3 — Exact cost

| Item | Monthly |
|---|---|
| Box A — existing 2 GB (keeps the webhook, untouched) | $12.00 *(already paying)* |
| Box B — new 4 GB | **$24.00** |
| Box C — new 4 GB | **$24.00** |
| Lightsail Load Balancer (managed TLS, health checks) | **$18.00** |
| Domain for the LB cert (.com ≈ $14/yr) | **~$1.17** |
| **New spend** | **≈ $67/mo** |
| Amazon RDS (existing) | ~$13–30 *(already paying)* |
| Apify + Claude usage | your current usage *(unchanged)* |

> **Student tip:** check the GitHub Student Developer Pack / AWS credits, and RDS free tier (if your AWS
> account is < 12 months old, a `db.t4g.micro` is free for 12 months). Either can wipe out part of this.

---

## Part 4 — Pre-flight: fix these in the repo first

**Already done for you in this repo:**
- ✅ `.dockerignore` updated to drop the unused model trial files (the live model IE2 loads is kept).
- ✅ All Kubernetes manifests written in `infra/k8s/`.

**You must still do these (they involve real secret values only you should set):**

1. **Generate a real `AUTH_TOKEN_SECRET`.** Without it, [eep/auth_db.py](../eep/auth_db.py) falls back to a
   public hardcoded secret → anyone could forge a login. Run: `openssl rand -hex 32` and keep the output.
2. **Pick a strong `RETAIL_ADMIN_PASSWORD`** and a real `RETAIL_ADMIN_EMAIL` (not `admin@example.com`).
3. **Rotate the secrets that have sat in `.env`:** RDS password, `APIFY_TOKEN`, `APIFY_WEBHOOK_SECRET`.
   (If you rotate `APIFY_WEBHOOK_SECRET`, update it in the Apify webhook header too.)
4. **Generate `IE2_API_KEY`:** `openssl rand -hex 24` (IE2 logs "do not deploy without setting this").
5. **Add `ANTHROPIC_API_KEY`** (and `GRAFANA_ADMIN_PASSWORD`) — neither exists in your current `.env`.
   Without `ANTHROPIC_API_KEY`, IE3 campaign copy, EEP outcome explanations, and Telegram stay dark
   (the IE2 model recommendations still work).
6. **Buy a cheap domain (~$14/yr)** for the Lightsail Load Balancer's HTTPS certificate — the LB cannot
   issue a cert for `sslip.io`. Your Apify webhook keeps using Box A's `sslip.io`; only the new
   dashboard/API uses this domain.

You'll paste the secrets into a local `k8s.env` file in Part 9 (never committed).

---

## Part 5 — Install the tools on your laptop (Windows)

You need three things locally. Open **PowerShell** and run:

```powershell
# 1. Docker Desktop — to build the images. If not installed:
winget install Docker.DockerDesktop
# (then launch Docker Desktop once so the engine is running)

# 2. kubectl — to control the cluster:
winget install Kubernetes.kubectl
kubectl version --client      # confirm it prints a version

# 3. Git & GitHub CLI you already have. OpenSSH (for SSH to servers) ships with Windows 11.
```

That's it — `kubectl` has Kustomize built in (`kubectl apply -k`), so no separate install.

---

## Part 6 — Build & push the 6 images to GitHub (GHCR)

Kubernetes pulls images from a registry; it does not build them. We use **GitHub Container Registry**
(free). Run from the **repo root** with Docker Desktop running:

```powershell
# Log in to GHCR (create a GitHub token with write:packages at github.com/settings/tokens)
$env:CR_PAT = "ghp_xxx_your_token"
$env:CR_PAT | docker login ghcr.io -u mhmd-jawad --password-stdin

$TAG = (git rev-parse --short HEAD)        # an immutable version tag
$REG = "ghcr.io/mhmd-jawad"

# EEP — INSTALL_IE2=false keeps EEP light (model lives only in the IE2 pods).
docker build -f eep/Dockerfile --build-arg INSTALL_IE2=false -t "$REG/retail-radar-eep:$TAG" .

docker build -f services/market_intelligence/Dockerfile  -t "$REG/retail-radar-ie1:$TAG" .
docker build -f services/decision_intelligence/Dockerfile -t "$REG/retail-radar-ie2:$TAG" .
docker build -f services/campaign_creative/Dockerfile     -t "$REG/retail-radar-ie3:$TAG" .
docker build -f services/telegram_assistant/Dockerfile    -t "$REG/retail-radar-telegram:$TAG" .

# Frontend — VITE_API_BASE_URL=/api matches the ingress routing in 40-ingress.yaml.
docker build -f frontend/Dockerfile `
  --build-arg VITE_DATA_MODE=eep-live `
  --build-arg VITE_API_BASE_URL=/api `
  --build-arg VITE_IE1_BASE_URL=/ie1 `
  --build-arg VITE_IE2_BASE_URL=/ie2 `
  --build-arg VITE_IE3_BASE_URL=/ie3 `
  --build-arg VITE_API_KEY= `
  --build-arg VITE_GRAFANA_URL= `
  -t "$REG/retail-radar-frontend:$TAG" .

# Push all six
foreach ($svc in "eep","ie1","ie2","ie3","telegram","frontend") { docker push "$REG/retail-radar-$svc`:$TAG" }

# Remember $TAG — you'll put it in infra/k8s/kustomization.yaml in Part 10.
echo "Built and pushed tag: $TAG"
```

Then on GitHub, set each package to **Private** (github.com → your profile → Packages → each → Settings).

> If you build on an Apple-Silicon Mac instead, add `--platform linux/amd64` to every `docker build`.

---

## Part 7 — Create the two servers on AWS Lightsail (click by click)

You'll create **two** instances. Do all of this in the AWS Lightsail console.

### 7.1 Create Box B
1. Go to **https://lightsail.aws.amazon.com** → **Instances** → **Create instance**.
2. **Region:** click "Change Region" and pick **Frankfurt (eu-central-1)** — the **same region as your
   existing box and your RDS** (this is required so they share a private network).
3. **Pick your instance image:**
   - Platform: **Linux/Unix**
   - Blueprint: click **"OS Only"** → **Ubuntu 24.04 LTS**.
4. **SSH key pair:** leave the default (or "Create new" and download the `.pem` — you can also use the
   browser SSH button later, so a key is optional).
5. **Choose your instance plan:** pick the **$24 USD / month** tier (**4 GB RAM, 2 vCPUs, 80 GB SSD**).
   *(Do not pick 2 GB — IE2's model needs ~1.5 GB and won't fit alongside k3s on 2 GB.)*
6. **Name it `rr-node-1`.** Click **Create instance.**

### 7.2 Create Box C
Repeat 7.1 exactly, name it **`rr-node-2`**, same region, same Ubuntu 24.04, same $24 plan.

### 7.3 Note the IP addresses
Open each instance's page. Write down, for **both** nodes:
- **Public IP** (changes if you stop/start — fine, only used for SSH/kubectl).
- **Private IP** (starts with `172.x`) — used for node-to-node traffic.

You now have, e.g.: `rr-node-1` public `B.B.B.B` / private `172.26.x.1`, and `rr-node-2` public `C.C.C.C` /
private `172.26.x.2`. (Box A is untouched and not part of the cluster.)

### 7.4 Open the firewall ports (each new node's **Networking** tab → IPv4 Firewall → Add rule)

On **`rr-node-1`** add:
| Application | Protocol | Port | Restrict to |
|---|---|---|---|
| SSH | TCP | 22 | **Your IP** |
| Custom | TCP | 6443 | **Your IP** + `rr-node-2` private IP *(Kubernetes API)* |
| Custom | UDP | 8472 | `rr-node-2` private IP *(pod network)* |
| Custom | TCP | 10250 | `rr-node-2` private IP *(metrics)* |
| Custom | TCP | 30080 | the **Lightsail Load Balancer** *(Traefik entrypoint)* |

On **`rr-node-2`** add:
| Application | Protocol | Port | Restrict to |
|---|---|---|---|
| SSH | TCP | 22 | **Your IP** |
| Custom | UDP | 8472 | `rr-node-1` private IP |
| Custom | TCP | 10250 | `rr-node-1` private IP |
| Custom | TCP | 30080 | the **Lightsail Load Balancer** |

> The Lightsail Load Balancer reaches the instances over the Lightsail network when you attach them
> (Part 11); if 30080 ever shows unhealthy, allow port 30080 (Any IPv4) on both nodes — it's an internal
> HTTP port, not your public entry.
> Lightsail's "Restrict to IP address" takes one source. If a port needs two sources (e.g. 6443), add the
> rule twice — once per source IP. If restricting is fiddly, the private-only ports (8472/10250/30080)
> can be left open for a project, but keep **22 and 6443 restricted to your IP**.

### 7.5 Confirm RDS reachability
Your existing Box A already talks to RDS, which means Lightsail↔RDS VPC peering is on for this region —
so the new nodes can reach RDS too. We'll verify with a real test in Part 12. (If it ever fails: Lightsail
console → **Account → Advanced → VPC peering** must be enabled for eu-central-1, and the RDS security
group must allow the Lightsail private range.)

---

## Part 8 — Install k3s on the two nodes

**SSH into Box B (`rr-node-1`)** — use the orange terminal icon on its Lightsail page (browser SSH), or
`ssh -i your-key.pem ubuntu@B.B.B.B` from PowerShell.

### 8.1 (Both nodes) add a small swap file — safety net for the model
Run on **rr-node-1** and again on **rr-node-2**:
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 8.2 On rr-node-1 — install the k3s **server**
Replace `<NODE1_PRIVATE_IP>` and `<NODE1_PUBLIC_IP>` with rr-node-1's IPs:
```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--cluster-init --disable servicelb \
  --node-ip <NODE1_PRIVATE_IP> --tls-san <NODE1_PUBLIC_IP>" sh -

# Wait ~30s, then grab the join token (copy the whole line):
sudo cat /var/lib/rancher/k3s/server/node-token
```

### 8.3 On rr-node-2 — join as a **worker**
Replace the token and IPs:
```bash
curl -sfL https://get.k3s.io | K3S_URL="https://<NODE1_PRIVATE_IP>:6443" \
  K3S_TOKEN="<token from 8.2>" INSTALL_K3S_EXEC="--node-ip <NODE2_PRIVATE_IP>" sh -
```

### 8.4 Back on rr-node-1 — confirm both nodes joined
```bash
sudo k3s kubectl get nodes
# Expect: rr-node-1  Ready  control-plane,etcd,master   |   rr-node-2  Ready  <none>
```

### 8.5 Expose Traefik on a fixed port (30080) so Box A's Caddy can reach it
On **rr-node-1**, create this file:
```bash
sudo tee /var/lib/rancher/k3s/server/manifests/traefik-config.yaml >/dev/null <<'EOF'
apiVersion: helm.cattle.io/v1
kind: HelmChartConfig
metadata: { name: traefik, namespace: kube-system }
spec:
  valuesContent: |-
    deployment:
      replicas: 2
    service:
      type: NodePort
    ports:
      web:
        nodePort: 30080
EOF
# k3s applies it automatically within a minute. Verify:
sudo k3s kubectl -n kube-system get svc traefik   # PORT(S) should show 80:30080/TCP
```
Because 30080 is a **NodePort**, it answers on **both** nodes regardless of where Traefik runs.

### 8.6 Get the kubeconfig onto your laptop
On rr-node-1: `sudo cat /etc/rancher/k3s/k3s.yaml` → copy the whole output.
On your laptop, save it to `C:\Users\Administrator\.kube\config`, and change the line
`server: https://127.0.0.1:6443` to `server: https://<NODE1_PUBLIC_IP>:6443`.
Test from PowerShell:
```powershell
kubectl get nodes      # should list both nodes as Ready
```
✅ Your laptop now controls the cluster. Everything below runs from your laptop.

---

## Part 9 — Create the secrets and config

### 9.1 Make two local, git-ignored files
Create `k8s.env` (app secrets — use the values you generated in Part 4):
```dotenv
AUTH_TOKEN_SECRET=<openssl rand -hex 32 output>
RETAIL_ADMIN_PASSWORD=<a strong password>
APIFY_TOKEN=<rotated>
APIFY_WEBHOOK_SECRET=<rotated — must match the Apify webhook header>
IE2_API_KEY=<openssl rand -hex 24 output>
GRAFANA_ADMIN_PASSWORD=<a strong password>
ANTHROPIC_API_KEY=<your key>
OPENROUTER_API_KEY=
GEMINI_API_KEY=
REPLICATE_API_KEY=
IMGBB_API_KEY=
FB_PAGE_ACCESS_TOKEN=
FB_PAGE_ID=
IG_USER_ID=
META_APP_ID=
META_APP_SECRET=
TELEGRAM_BOT_TOKEN=
RETAILER_CHAT_ID=
TELEGRAM_WEBHOOK_SECRET=
# DATABASE_URL points at PgBouncer, NOT RDS directly. Use your RDS user + the ROTATED password.
DATABASE_URL=postgresql://<rds_user>:<rotated_rds_pw>@pgbouncer:6432/retail_radar?sslmode=disable
```
Create `pgbouncer.env` (the real RDS connection — your endpoint is already known):
```dotenv
DB_HOST=retail-radar-db.cbyyqyueehc2.eu-central-1.rds.amazonaws.com
DB_PORT=5432
DB_NAME=retail_radar
DB_USER=<rds master user>
DB_PASSWORD=<rotated rds password>
```

### 9.2 Edit two values in the committed config
Open [../infra/k8s/00-config.yaml](../infra/k8s/00-config.yaml) and set:
- `RETAIL_ADMIN_EMAIL` → your real email.
- `WEBHOOK_DOMAIN` → your **LB domain** (e.g. `yourdomain.com`, from Part 11).
- (`RETAIL_AUTO_INIT_DB` is already `false` — correct, your RDS already has the schema.)

### 9.3 Create the three secrets in the cluster (from PowerShell)
```powershell
kubectl create namespace retail-radar

kubectl create secret docker-registry ghcr-creds `
  --docker-server=ghcr.io --docker-username=mhmd-jawad --docker-password=$env:CR_PAT -n retail-radar

kubectl create secret generic retail-secrets   --from-env-file=k8s.env       -n retail-radar
kubectl create secret generic pgbouncer-secret --from-env-file=pgbouncer.env -n retail-radar
```

---

## Part 10 — Deploy everything

### 10.1 Pin your image tag
Open [../infra/k8s/kustomization.yaml](../infra/k8s/kustomization.yaml) and replace every `newTag: latest`
with the `$TAG` from Part 6 (the git short SHA).

### 10.2 Apply
```powershell
kubectl apply -k infra/k8s/
kubectl -n retail-radar get pods -o wide -w     # Ctrl-C when ie1/ie2/ie3/eep/frontend/pgbouncer are READY
```
You should see two of each app pod, landing on **different nodes** (watch the NODE column). `telegram`
shows `0/0` — that's intentional (Part 12.6 turns it on). `prometheus`/`grafana` show 1 each.

> **If a pod is stuck:** `kubectl -n retail-radar describe pod <name>` and read the Events at the bottom
> (usually a missing secret value or, for `ImagePullBackOff`, a registry/tag/private-package issue).

---

## Part 11 — Put a Lightsail Load Balancer in front of the cluster

**Box A: do nothing.** It keeps running your webhook on `sslip.io`, completely independent. This part
creates a managed Load Balancer that gives the cluster its own public HTTPS front door.

### 11.1 Create the load balancer
1. Lightsail console → **Networking** → **Create load balancer.**
2. Same **region (Frankfurt)**. Name it `rr-lb`. Create.
3. **Target instances** tab → **Attach** `rr-node-1` and `rr-node-2`. Lightsail opens the path to the
   instances automatically (this is why 30080 is allowed from the LB in Part 7.4).
4. **Health checking** → set the path to **`/api/health`** (the LB hits Traefik on each node → `/api`
   strips → EEP `/health` → 200). Unhealthy nodes drop out of rotation.

### 11.2 Attach HTTPS with your domain
1. In the LB → **Inbound traffic / Certificates** → **Create certificate** for your domain
   (`yourdomain.com`). Lightsail shows DNS validation records.
2. Add those records at your registrar (or in a free **Lightsail DNS zone**: Networking → Create DNS
   zone → add the validation records). Wait for the cert to verify (minutes).
3. Point `yourdomain.com` at the LB: in your DNS, **CNAME** `yourdomain.com` → the LB's default DNS name
   (shown on the LB page), or use a Lightsail DNS zone "A record / assignment" to the LB.
4. On the LB, enable the **HTTPS (443)** listener with that certificate and turn on **HTTP→HTTPS
   redirect**. The LB forwards to the instance **HTTP port 30080**.

### 11.3 Tell EEP its public domain
You already set `WEBHOOK_DOMAIN: "yourdomain.com"` in `00-config.yaml` (Part 9.2). If you change it after
deploying: `kubectl apply -k infra/k8s/` then `kubectl -n retail-radar rollout restart deploy/eep`.

Now: **browser → `https://yourdomain.com` (Lightsail LB, TLS) → node:30080 → Traefik → the right pod.**
The Apify webhook is untouched — it still posts to Box A's `sslip.io`.

> **No-LB alternative (saves $18 + the domain):** instead of the LB, reuse a Caddy on Box A as the edge —
> see [../infra/k8s/edge/Caddyfile](../infra/k8s/edge/Caddyfile) and Appendix D. You chose the LB, so skip
> that unless you want to cut cost later.

---

## Part 12 — Verify everything works

### 12.1 Pods and autoscalers
```powershell
kubectl -n retail-radar get pods -o wide     # 2 of each app, on different nodes; prom/grafana 1 each
kubectl -n retail-radar get hpa              # eep and ie2 show CPU targets (not <unknown>)
```

### 12.2 Internal wiring (from inside the cluster)
```powershell
kubectl -n retail-radar run probe --rm -it --image=curlimages/curl --restart=Never -- `
  sh -c "curl -s http://eep:8000/health; echo; curl -s http://ie2:8002/health; echo; curl -s http://ie1:8001/health"
```
Each should return an OK/health JSON.

### 12.3 Database through PgBouncer
```powershell
kubectl -n retail-radar run dbtest --rm -it --image=postgres:16 --restart=Never -- `
  psql "postgresql://<rds_user>:<rotated_pw>@pgbouncer:6432/retail_radar?sslmode=disable" -c "select count(*) from intel.competitor_prices;"
```
A row count proves app→PgBouncer→RDS works end to end.

### 12.4 Public access through Caddy (Box A)
```powershell
curl https://<your-domain>/api/health     # → EEP health, 200
curl https://<your-domain>/               # → the dashboard HTML
```
Open `https://<your-domain>` in a browser, log in with your admin email/password, and confirm the
dashboard loads with live data.

### 12.5 Apify pipeline
Trigger an Apify run (or wait for the schedule). Confirm new rows land in RDS and the dashboard's
data-source banner shows fresh data. (Apify hits the same URL → Caddy → Traefik `/apify` → EEP.)

### 12.6 (Optional) turn on Telegram
Only if you have a bot. Put `TELEGRAM_BOT_TOKEN`, `RETAILER_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET` in
`k8s.env`, re-create the secret (Part 13 shows the one-liner), then:
```powershell
kubectl -n retail-radar scale deploy/telegram --replicas=1
# Register the webhook with Telegram:
#   https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-domain>/webhook/telegram&secret_token=<TELEGRAM_WEBHOOK_SECRET>
```

### 12.7 Prove high availability — reboot the worker
```powershell
# In Lightsail, reboot rr-node-2 (the worker). Then watch:
kubectl get nodes                             # rr-node-2 goes NotReady…
kubectl -n retail-radar get pods -o wide -w   # rr-node-1 keeps serving its copies
curl https://<your-domain>/api/health         # stays 200 the whole time
```
When rr-node-2 comes back, its pods reschedule. That's the resilience you built.

### 12.8 Dashboards
```powershell
kubectl -n retail-radar port-forward svc/grafana 3001:3000      # http://localhost:3001 (admin / GRAFANA_ADMIN_PASSWORD)
```
Add Prometheus datasource `http://prometheus:9090`, import the JSON from
[../infra/monitoring/grafana/dashboards/](../infra/monitoring/grafana/dashboards/).

---

## Part 13 — Day-to-day operations

```powershell
kubectl -n retail-radar logs -f deploy/eep              # tail logs
kubectl -n retail-radar get pods -o wide                # what's running where
kubectl top pods -n retail-radar                        # live CPU/RAM

# Ship a new version: build+push a new $TAG (Part 6), bump newTag in kustomization.yaml, then:
kubectl apply -k infra/k8s/
kubectl -n retail-radar rollout status deploy/eep
kubectl -n retail-radar rollout undo deploy/eep         # roll back if needed

# Rotate a secret, then restart the pods that use it:
kubectl -n retail-radar create secret generic retail-secrets --from-env-file=k8s.env `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n retail-radar rollout restart deploy/eep deploy/ie2 deploy/ie1 deploy/ie3
```
**Backups:** turn on **automated RDS snapshots** (daily) in the RDS console — that's your real data. The
cluster itself is disposable; it rebuilds from these manifests + images.

---

## Appendix A — Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Pod `ImagePullBackOff` | registry auth / wrong tag / package not private-accessible | Check `ghcr-creds`; confirm the tag in `kustomization.yaml` matches what you pushed. |
| Pod `CrashLoopBackOff` | missing required env var | `kubectl logs` it; add the value to `k8s.env`; re-create `retail-secrets`; `rollout restart`. |
| Pod `Pending` | no node has the RAM | `describe pod` → "Insufficient memory"; scale a non-critical deploy down, or add the 3rd node (Appendix C). |
| `dbtest` can't connect | RDS security group / VPC peering | Enable Lightsail VPC peering (eu-central-1); allow the Lightsail private range in the RDS security group. |
| LB targets show "unhealthy" | 30080 path/firewall | Health-check path must be `/api/health`; ensure 30080 is reachable on both nodes (Part 7.4); `curl http://<node-private-ip>:30080/api/health` from another node. |
| `https://yourdomain.com` no TLS / cert pending | DNS validation incomplete | Add the cert's validation records to your DNS; wait for the Lightsail cert to show "Valid"; ensure the domain CNAMEs to the LB. |
| HPA shows `<unknown>` | metrics-server warming up | Wait ~1 min; `kubectl top pods` should work (k3s ships metrics-server). |
| Telegram pod CrashLoops | bot token missing | Set `TELEGRAM_*` in `k8s.env`; or `kubectl scale deploy/telegram --replicas=0`. |

## Appendix B — Enabling the EEP live-evaluation metric (optional)
EEP is built `INSTALL_IE2=false`, so its `/evaluation/live-rds/metrics` endpoint is off (that's why
`50-monitoring.yaml` doesn't scrape it). You don't need it. If you ever want it, the clean way is to move
that endpoint into the IE2 pod (where the model already lives) rather than rebuilding EEP with the model.

## Appendix C — Growing to 3 nodes (full control-plane HA)
Create a 3rd 4 GB box `rr-node-3`, open the same firewall ports, then **join it as a server** (not a
worker) so etcd has a 3-member quorum:
```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--server https://<NODE1_PRIVATE_IP>:6443 \
  --disable servicelb --node-ip <NODE3_PRIVATE_IP>" K3S_TOKEN="<token>" sh -
```
Then in the Lightsail LB → **attach `rr-node-3`** as a 3rd target. No app manifest changes. New cost
becomes $72/mo nodes + $18 LB.

## Appendix D — No-LB alternative: reuse Box A's Caddy as the edge (saves $18 + the domain)
If you later want to cut the LB and domain, you can keep your `sslip.io` domain and make **Box A's Caddy**
the edge + load balancer into the cluster (this *does* change Box A, unlike the LB plan):
1. Edit [../infra/k8s/edge/Caddyfile](../infra/k8s/edge/Caddyfile): set `NODE1_PRIVATE_IP` /
   `NODE2_PRIVATE_IP` to your nodes' private IPs.
2. On both nodes, allow port **30080 from Box A's private IP** (instead of from the LB).
3. On Box A, run Caddy with that file (`--network host`, `WEBHOOK_DOMAIN=<your sslip.io>`):
   `sudo docker run -d --name caddy --restart unless-stopped --network host -e WEBHOOK_DOMAIN=... -v /opt/caddy/Caddyfile:/etc/caddy/Caddyfile:ro -v caddy_data:/data caddy:2-alpine`

Trade-off: Box A becomes the single public entry point (if it's down, the dashboard is unreachable — the
webhook on Box A is unaffected). $0 extra, but no managed-LB health/redundancy.

---

## Quick-start checklist
- [ ] **Part 4** — generate `AUTH_TOKEN_SECRET`, admin password, `IE2_API_KEY`, `GRAFANA_ADMIN_PASSWORD`; add `ANTHROPIC_API_KEY`; rotate RDS/Apify secrets; buy a domain for the LB.
- [ ] **Part 5** — install Docker Desktop + kubectl.
- [ ] **Part 6** — build & push 6 images (EEP `INSTALL_IE2=false`, frontend `VITE_API_BASE_URL=/api`); note `$TAG`; make packages private.
- [ ] **Part 7** — create `rr-node-1` + `rr-node-2` (4 GB, Frankfurt, Ubuntu 24.04); open firewall ports.
- [ ] **Part 8** — swap; k3s server on node 1; worker join on node 2; Traefik NodePort 30080; kubeconfig.
- [ ] **Part 9** — `k8s.env` + `pgbouncer.env`; edit `00-config.yaml` (LB domain); create the 3 secrets.
- [ ] **Part 10** — set image tag in `kustomization.yaml`; `kubectl apply -k infra/k8s/`.
- [ ] **Part 11** — create Lightsail LB; attach both nodes; health path `/api/health`; cert + DNS for your domain; HTTPS 443→30080. **Box A stays untouched.**
- [ ] **Part 12** — verify internal, DB, public (`https://yourdomain.com`), Apify (still on Box A); reboot-a-node HA test.
