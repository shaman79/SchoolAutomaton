# Deploying SchoolAutomaton on a server

Served publicly through your existing **Cloudflare tunnel** at `https://schoolautomaton.avercode.com`.
Cloudflare terminates TLS, so the app only listens on a local port — nothing is exposed directly.

```
Browser ──TLS──> Cloudflare ──tunnel──> cloudflared (your server) ──> 127.0.0.1:<PORT>
                                                                       └─ nginx (frontend)
                                                                            ├─ serves the SPA
                                                                            └─ proxies /api ─> backend:8000
```

## 1. Deploy — one command

```bash
git clone https://github.com/shaman79/SchoolAutomaton.git
cd SchoolAutomaton
./infra/scripts/deploy.sh
```

That's it. The script:
1. **Checks the runtime** — if Docker Engine / the Compose v2 plugin is missing, it offers to install
   it (official `get.docker.com`, with your confirmation).
2. **Asks for settings** (press Enter to accept the shown default):
   - **Web port** your tunnel forwards to (default `8080`)
   - **Bind interface** (default `127.0.0.1` = tunnel-only)
   - **Public URL** (default `https://schoolautomaton.avercode.com`)
   - **Admin username / password** (it requires a real, non-default password)
   - **Anthropic API key** and **Replicate API token** (blank = skip; generation stays off until set)
   - **APP_SECRET** is generated for you.
3. **Writes `.env`** (chmod 600), **builds** the images, **starts** the stack, and **verifies** the
   backend is healthy and the web port responds.

Re-run `./infra/scripts/deploy.sh` any time to change settings (it pre-fills your current values) or
after a code update. The SQLite DB and generated-image cache live on the `sa-data` Docker volume and
survive rebuilds.

> `SA_ENV=production` is enforced, so the backend refuses to start with a weak `APP_SECRET` or an
> `admin` password — the script handles both. The admin account is created on first boot.

## 2. Point your Cloudflare tunnel at it

The script prints the exact mapping. Route `schoolautomaton.avercode.com` → `http://localhost:<PORT>`:

- **Dashboard tunnel** (Zero Trust → Networks → Tunnels → *Public Hostname*):
  `schoolautomaton.avercode.com` → Service **HTTP** → `localhost:<PORT>`.
- **Config-file tunnel** (`/etc/cloudflared/config.yml`):
  ```yaml
  ingress:
    - hostname: schoolautomaton.avercode.com
      service: http://localhost:8080      # match the port you chose
    - service: http_status:404
  ```
  then `cloudflared tunnel route dns <name> schoolautomaton.avercode.com` and
  `sudo systemctl restart cloudflared`.

No extra Cloudflare settings needed — the SPA and `/api` (incl. the SSE generation stream) share one
origin via nginx.

## 3. Verify

Open `https://schoolautomaton.avercode.com` and sign in at `…/admin/login`. Locally:
```bash
curl -fsS http://127.0.0.1:8080/ >/dev/null && echo "web OK"     # match your port
docker compose ps                                                # both services Up/healthy
```

## 4. Automatic updates (every 15 minutes)

Schedule it once and the server keeps itself current — `update.sh` pulls from git and **only rebuilds
+ restarts when there are actually new commits** (otherwise it's a fast no-op, so there's no needless
downtime), with a lock so runs never overlap.

```bash
sudo ./infra/scripts/install-auto-update.sh        # every 15 min (systemd timer; cron fallback)
# custom interval:  sudo ./infra/scripts/install-auto-update.sh 30
# stop auto-updates: sudo ./infra/scripts/install-auto-update.sh --uninstall
```
Watch it:
```bash
systemctl list-timers schoolautomaton-update.timer       # next run
journalctl -u schoolautomaton-update.service -f          # live logs
```
Requirements: the deploy must be a **git clone** (so it can `git pull`) and the deploy user must be
in the `docker` group (the deploy script arranges this). Auto-update runs as that user.

> Note: schema-changing releases (rare) aren't auto-migrated — the app creates missing tables on boot
> but won't alter existing ones. For those, redeploy with a fresh `sa-data` or apply a migration.

## 5. Update / operate manually

| Task | Command |
|---|---|
| Update now | `./infra/scripts/update.sh` (no-op if nothing new; `--force` to rebuild anyway) |
| Change settings/port | re-run `./infra/scripts/deploy.sh` (then update the tunnel port) |
| Logs | `docker compose logs -f` (or `… logs -f backend`) |
| Restart / stop | `docker compose restart` · `docker compose down` (keeps `sa-data`) |
| Backup data | `docker run --rm -v schoolautomaton_sa-data:/d -v "$PWD":/b alpine tar czf /b/sa-data-backup.tgz -C /d .` |

> Provider keys can also be managed at runtime from the admin **Settings** page (stored
> Fernet-encrypted); env values win at boot.
