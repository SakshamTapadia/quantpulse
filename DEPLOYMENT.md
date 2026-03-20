# Deployment Guide

## Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 6 GB | 8 GB |
| CPU | 2 vCPU | 4 vCPU |
| Disk | 40 GB | 80 GB |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |

**Why so much RAM?** Kafka + ZooKeeper (~2 GB), ML training (~3 GB peak), TimescaleDB (~500 MB), 5 Python services (~200 MB each).

---

## Recommended Providers

| Provider | Plan | Cost |
|----------|------|------|
| Hetzner Cloud | CX32 (4 vCPU / 8 GB) | ~€9/mo |
| DigitalOcean | Basic (4 vCPU / 8 GB) | ~$48/mo |
| AWS | EC2 t3.large (2 vCPU / 8 GB) | ~$60/mo |
| Any VPS | 4 vCPU / 8 GB / Ubuntu | - |

---

## 1. Provision the Server

Create an Ubuntu 22.04 VM on your provider of choice. SSH in as root or a sudo user.

---

## 2. Install Docker

```bash
apt update && apt install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | tee /etc/apt/sources.list.d/docker.list
apt update && apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin git
```

---

## 3. Clone and Configure

```bash
git clone https://github.com/SakshamTapadia/quantpulse.git
cd quantpulse
cp .env.example .env
```

Edit `.env` - **change every default value**:

```bash
nano .env
```

Key values to set:

```env
# Get free keys at fred.stlouisfed.org and polygon.io
POLYGON_API_KEY=your_real_key
FRED_API_KEY=your_real_key

# Generate strong secrets
POSTGRES_PASSWORD=<run: openssl rand -base64 24>
REDIS_PASSWORD=<run: openssl rand -base64 24>
JWT_SECRET=<run: openssl rand -base64 32>

# Your server's public IP or domain
NEXT_PUBLIC_API_URL=http://YOUR_SERVER_IP:8000
NEXT_PUBLIC_WS_URL=ws://YOUR_SERVER_IP:8000
```

---

## 4. Start All Services

```bash
docker compose up --build -d
```

First build takes 10-15 minutes (pulling base images + installing Python deps). Subsequent starts are fast.

Check everything is up:

```bash
docker compose ps
```

All 14 containers should show `Up` or `Up (healthy)`.

---

## 5. Seed Data and Train Models

Open `http://YOUR_SERVER_IP:3000/dashboard/training` and run in order:

1. **Historical Backfill (5y)** - fetches 5 years of market data (~3 min)
2. **Retrain Models** - trains HMM + Transformer (~10-15 min, watch MLflow at `:5000`)
3. **Run Inference** - classifies all 15 tickers and populates the dashboard

Or trigger via API:

```bash
TOKEN=$(curl -s -X POST http://YOUR_SERVER_IP:8000/auth/token \
  -d "username=admin&password=changeme" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

curl -X POST http://YOUR_SERVER_IP:8000/trigger/backfill?years=5 -H "Authorization: Bearer $TOKEN"
# wait ~3 min, then:
curl -X POST http://YOUR_SERVER_IP:8000/train -H "Authorization: Bearer $TOKEN"
# wait ~15 min, then:
curl -X POST http://YOUR_SERVER_IP:8000/infer -H "Authorization: Bearer $TOKEN"
```

---

## 6. Service URLs

| Service | URL |
|---------|-----|
| Dashboard | `http://YOUR_SERVER_IP:3000` |
| API docs | `http://YOUR_SERVER_IP:8000/docs` |
| MLflow | `http://YOUR_SERVER_IP:5000` |
| Grafana | `http://YOUR_SERVER_IP:3001` - `admin` / your `GF_SECURITY_ADMIN_PASSWORD` |
| Prometheus | `http://YOUR_SERVER_IP:9090` |
| Kafka UI | `http://YOUR_SERVER_IP:9080` |

---

## 7. (Optional) Nginx + HTTPS

If you have a domain, install Nginx and Certbot to serve everything over HTTPS:

```bash
apt install -y nginx certbot python3-certbot-nginx
```

Example Nginx config at `/etc/nginx/sites-available/quantpulse`:

```nginx
server {
    server_name yourdomain.com;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
    }

    location /ws/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Then get a certificate:

```bash
certbot --nginx -d yourdomain.com
```

Update your `.env` to use `https://yourdomain.com` for `NEXT_PUBLIC_API_URL` and rebuild:

```bash
docker compose up --build -d frontend
```

---

## 8. Auto-restart on Reboot

All services already have `restart: unless-stopped` in docker-compose.yml. Enable Docker to start on boot:

```bash
systemctl enable docker
```

---

## 9. Updates

To pull the latest code and redeploy:

```bash
git pull
docker compose up --build -d
```

Only changed service images are rebuilt.

---

## Troubleshooting

**Services keep restarting:**
```bash
docker compose logs <service-name> --tail=50
```

**Kafka not healthy after 2 min:**
```bash
docker compose restart zookeeper kafka
```

**Out of memory during training:**
Reduce transformer batch size in `.env`:
```env
TRANSFORMER_BATCH_SIZE=64   # default 128
```

**Port already in use:**
Check what's using the port: `ss -tlnp | grep 3000`
