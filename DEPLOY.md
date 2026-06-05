# Deploying SchoolAutomaton on a server

Target setup: **Docker Compose** on a Linux server, served publicly through your **existing
Cloudflare tunnel** at `https://schoolautomaton.avercode.com`. Cloudflare terminates TLS, so the
app only listens on a local port — nothing is exposed to the internet directly.

```
Browser ──TLS──> Cloudflare ──tunnel──> cloudflared (on your server) ──> 127.0.0.1:<PORT>
                                                                          └─ nginx (frontend)
                                                                               ├─ serves the SPA
                                                                               └─ proxies /api ─> backend:8000
```

---

## 1. Prerequisites (one time)

Docker Engine + the Compose v2 plugin, and git. On Ubuntu/Debian:
```bash
curl -fsSL https://get.docker.com | sh        # installs Docker Engine + compose plugin
sudo usermod -aG docker "$USER"                # then log out/in so `docker` works without sudo
docker compose version                         # verify (v2.x)
```

## 2. Get the code
```bash
git clone https://github.com/shaman79/SchoolAutomaton.git
cd SchoolAutomaton
```

## 3. Configure + first deploy

The deploy script is **two-phase**: the first run creates `.env` (with a freshly generated
`APP_SECRET`) and stops so you can fill in the rest.

```bash
./infra/scripts/deploy.sh        # creates .env, generates APP_SECRET, prints what to edit
nano .env                        # set the values below
./infra/scripts/deploy.sh        # builds images + starts the stack
```

Set these in `.env`:

| Variable | Value |
|---|---|
| `SA_HTTP_PORT` | the local port to publish, e.g. `8080` (pick one free on the host) |
| `SA_HTTP_BIND` | leave `127.0.0.1` (local-only; the tunnel reaches it privately) |
| `SA_CORS_ORIGINS` | `https://schoolautomaton.avercode.com` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | your admin login (don't leave the placeholder) |
| `ANTHROPIC_API_KEY` | required for lesson/quiz generation |
| `REPLICATE_API_TOKEN` | required for generated illustrations |
| `APP_SECRET` | already auto-generated — leave it |

> `SA_ENV` is forced to `production` by `docker-compose.yml`, which enables a **fail-closed secret
> guard**: the backend refuses to start if `APP_SECRET` is weak/default or `ADMIN_PASSWORD` is
> `admin`. The admin account is created from `ADMIN_USERNAME`/`ADMIN_PASSWORD` on first boot.

The SQLite DB and the generated-image cache live on the Docker volume `sa-data` and survive
rebuilds/redeploys.

### Changing the port later
Edit `SA_HTTP_PORT` in `.env`, then `./infra/scripts/deploy.sh` (or `docker compose up -d`). Update
your tunnel's `service` URL to match (below).

## 4. Point your Cloudflare tunnel at it

The app is now at `http://localhost:<SA_HTTP_PORT>` on the server. Route your hostname to it.

**If your tunnel is dashboard-managed** (Zero Trust → Networks → Tunnels → your tunnel → *Public
Hostname*): add/point
- **Subdomain/Domain:** `schoolautomaton` . `avercode.com`
- **Service:** `HTTP` → `localhost:8080`  *(match `SA_HTTP_PORT`)*

**If your tunnel is config-file-managed** (`/etc/cloudflared/config.yml` or `~/.cloudflared/config.yml`):
```yaml
ingress:
  - hostname: schoolautomaton.avercode.com
    service: http://localhost:8080        # match SA_HTTP_PORT
  - service: http_status:404
```
then `cloudflared tunnel route dns <TUNNEL_NAME> schoolautomaton.avercode.com` and restart cloudflared
(`sudo systemctl restart cloudflared`).

No extra Cloudflare settings are required. (The generation progress uses SSE; Cloudflare tunnels
stream `text/event-stream` fine, and nginx is already configured with `proxy_buffering off` for
`/api`. If a network ever blocks SSE, generation still completes and the UI falls back to polling.)

## 5. Verify
```bash
curl -sf http://127.0.0.1:8080/ >/dev/null && echo "SPA OK"      # match SA_HTTP_PORT
docker compose exec backend python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/healthz').read())"
```
Then open `https://schoolautomaton.avercode.com` and sign in to the admin at
`https://schoolautomaton.avercode.com/admin/login`.

## 6. Update to a new version
```bash
./infra/scripts/update.sh        # git pull --ff-only, rebuild, recreate (data preserved), prune
```

## 7. Operations

| Task | Command |
|---|---|
| Logs (follow) | `docker compose logs -f` (or `docker compose logs -f backend`) |
| Restart | `docker compose restart` |
| Stop | `docker compose down` (keeps the `sa-data` volume) |
| Status | `docker compose ps` |
| Backup data | `docker run --rm -v schoolautomaton_sa-data:/d -v "$PWD":/b alpine tar czf /b/sa-data-backup.tgz -C /d .` |
| Rotate admin/API keys | edit `.env`, then `docker compose up -d` |

> Provider keys can also be managed at runtime from the admin **Settings** page (stored
> Fernet-encrypted); env values win at boot.
