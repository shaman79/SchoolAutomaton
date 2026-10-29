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
3. **Writes `.env`** (chmod 600), **builds** the images (`--pull`), **starts** the stack, and
   **health-gates** it the same way auto-update does (§4): `/api/v1/health` and the web app must
   answer through nginx within ~2 minutes, otherwise it rolls back to the previously running images
   (on a re-run) and exits with an error.

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
curl -fsS http://127.0.0.1:8080/api/v1/health; echo              # {"status":"ok","db":"ok",...} — match your port
curl -fsS http://127.0.0.1:8080/ >/dev/null && echo "web OK"
docker compose ps                                                # both services Up/healthy
```

## 4. Automatic updates + nightly backups

Schedule it once and the server keeps itself current and backed up:

```bash
sudo ./infra/scripts/install-auto-update.sh        # updates every 15 min + DB backup daily at 03:30
# custom update interval:  sudo ./infra/scripts/install-auto-update.sh 30
# other backup time:       sudo SA_BACKUP_TIME=02:15 ./infra/scripts/install-auto-update.sh
# remove both schedules:   sudo ./infra/scripts/install-auto-update.sh --uninstall
```
It installs systemd timers (`schoolautomaton-update`, `schoolautomaton-backup`; cron fallback). It is
idempotent — **re-run it after pulling this version** to add the backup schedule to an existing box.

Every run of `update.sh`:
1. `git pull`. If `HEAD` is the last successfully deployed commit → fast no-op (no rebuild, no
   restart). If it is a commit that already **failed** → skipped (no rebuild loop every 15 min); a
   newer commit is tried as soon as it lands.
2. Tags the running images `schoolautomaton-{backend,frontend}:previous`, then builds with `--pull`
   (base-image security updates; if the registry is unreachable it retries once from cache).
   A failed build changes nothing — the old containers keep serving.
3. If the backend image changed and `/api/v1/health` reports `active_generations > 0`, waits for the
   lessons/tests being generated (polls every 10 s, at most `SA_DEPLOY_MAX_WAIT_S`, default 600 s),
   then restarts anyway. Restarting mid-generation would lose a child's lesson.
4. `docker compose up -d`, then the **health gate**: through nginx, `GET /api/v1/health` must return
   200 `"status":"ok"` and the SPA shell plus its JS bundle must load — twice in a row — within
   `SA_DEPLOY_HEALTH_TIMEOUT_S` (default 120 s).
5. Unhealthy → container status + log tails go to the log, it **rolls back** to `:previous`, checks
   that is healthy, records the commit as bad (`.sa-deploy/bad-commit`) and **alerts** (§5).
   Healthy → records the commit (`.sa-deploy/deployed-commit`) and prunes *dangling* images only
   (`:previous` is kept for the next rollback).

Runs never overlap: update, deploy, backup and restore share one lock (`.sa-update.lock`).
`git pull` failing 4 runs in a row (~1 h) also alerts. Watch it:
```bash
tail -f logs/update.log                                   # also: journalctl -u schoolautomaton-update -f
systemctl list-timers 'schoolautomaton-*'                 # next runs
./infra/scripts/update.sh --force                         # redeploy current HEAD (also retries a bad commit)
```
Requirements: the deploy must be a **git clone** (so it can `git pull`) and the deploy user must be
in the `docker` group (the deploy script arranges this). Timers run as that user — don't run the
scripts with `sudo` (root-owned lock/log files would block later runs).

> Note: on boot the app creates missing tables and adds missing nullable columns in place (additive
> migrations in `backend/app/db/session.py`), so such releases update themselves and keep the data.
> Only destructive schema changes (renaming/dropping columns, changing types) need a manual
> migration or a fresh `sa-data`. A rollback restores the previous *images*, not the database: a
> release that changed the schema stays changed.
>
> There is no CI: `update.sh` pulls and rebuilds whatever lands on `main`, so run the tests before
> merging. The health gate catches a release that doesn't come up; it can't catch wrong behaviour.
>
> Health contract (backend): `GET /api/v1/health` → 200 `{"status":"ok","db":"ok","active_generations":N}`,
> 503 when the DB is unreachable. Until a backend with that endpoint is deployed, the gate accepts
> FastAPI's JSON 404 for it as proof that nginx → backend works.

## 5. Alerts

Set `SA_ALERT_WEBHOOK_URL` in `.env` and failed deploys, rollbacks, a stuck `git pull` and failed
backups are POSTed there as one short plain-text message (also always written to `logs/`). Without
it, alerts are only logged. The same alert is repeated at most every 6 h (`SA_ALERT_REPEAT_S`).

**ntfy (simplest, phone push):** install the ntfy app, subscribe to a hard-to-guess topic, then
```bash
echo 'SA_ALERT_WEBHOOK_URL=https://ntfy.sh/sa-alerts-<random-string>' >> .env
```
(ntfy topics are public to anyone who knows the name — use a long random one, or your own ntfy
server.) The scripts send ntfy's `Title`/`Priority`/`Tags` headers; "site may be down" is `urgent`.
Test it: `curl -d "test from $(hostname)" https://ntfy.sh/sa-alerts-<random-string>`.

**Slack / Discord** incoming webhooks need JSON, so also set the format:
```bash
SA_ALERT_WEBHOOK_URL=https://hooks.slack.com/services/…      SA_ALERT_FORMAT=slack     # {"text": …}
SA_ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/…      SA_ALERT_FORMAT=discord   # {"content": …}
```

## 6. Backups and restore

**What:** the SQLite database (`/app/data/schoolautomaton.db` on the `sa-data` volume) — learners'
profiles, progress, lessons and settings. The generated-image cache (`/app/data/cache`) is **not**
backed up: it is regenerated on demand.

**How:** `infra/scripts/backup.sh` (nightly via the timer above, or run it by hand at any time) uses
SQLite's backup API inside the backend container — a consistent copy while the app keeps writing —
runs `PRAGMA integrity_check` on the copy, gzips it and stores it **outside** the Docker volume:
```
backups/daily/schoolautomaton-YYYY-MM-DD.db.gz    newest 14 kept   (SA_BACKUP_KEEP_DAILY)
backups/weekly/schoolautomaton-YYYY-Www.db.gz     newest 8 kept    (SA_BACKUP_KEEP_WEEKLY)
```
`backups/` (or `SA_BACKUP_DIR`) is chmod 700 and gitignored. Any failure alerts (§5) and never prunes
older backups. Log: `logs/backup.log`. Two more things for a real disaster:
- **Copy backups off the machine** (e.g. `rclone`/`rsync` of `backups/` from another box) — a dead
  disk takes `./backups` with it.
- **Keep a copy of `.env`** somewhere safe: the API keys live only there (backups hold the database,
  not `.env`), and a restored DB needs the same `APP_SECRET` to read the encrypted text of
  safety-flagged requests. Changes made on the admin **Settings** page are in the database, so a
  backup carries them.

> Don't back up by tar-ing the volume while the app runs: the DB is in WAL mode, so copying the
> `.db`/`-wal`/`-shm` files independently can produce an inconsistent or corrupt copy.

**Restore** (stops the backend for a few seconds; the app shell stays up):
```bash
ls -l backups/daily backups/weekly
./infra/scripts/restore.sh backups/daily/schoolautomaton-2026-10-27.db.gz
```
It checks the file, saves a safety snapshot of the current DB to `backups/pre-restore/`, stops the
backend, writes the backup into the volume (as the app user), runs `integrity_check`, **deletes the
stale `-wal`/`-shm` files** (they belong to the old DB and would corrupt the restored one), starts the
backend and waits for `/api/v1/health`. `--yes` skips the prompt; `--skip-safety-copy` if the current
DB is too broken to copy. The same by hand:
```bash
docker compose stop backend
gunzip -c backups/daily/schoolautomaton-2026-10-27.db.gz | docker compose run --rm --no-deps -T backend \
  sh -c 'cat > /app/data/restore.tmp && rm -f /app/data/schoolautomaton.db-wal /app/data/schoolautomaton.db-shm \
         && mv /app/data/restore.tmp /app/data/schoolautomaton.db'
docker compose start backend
```

## 7. Operate manually

| Task | Command |
|---|---|
| Update now | `./infra/scripts/update.sh` (no-op if nothing new; `--force` to rebuild anyway) |
| Change settings/port | re-run `./infra/scripts/deploy.sh` (then update the tunnel port) |
| Logs | `docker compose logs -f` (or `… logs -f backend`) · deploys: `logs/update.log` |
| Restart / stop | `docker compose restart` · `docker compose down` (keeps `sa-data`) |
| Backup now | `./infra/scripts/backup.sh` |
| Restore | `./infra/scripts/restore.sh <backup.db.gz>` (§6) |
| Roll back by hand | `for s in backend frontend; do docker image tag schoolautomaton-$s:previous schoolautomaton-$s:latest; done && docker compose up -d --no-build --force-recreate` (auto-update won't redeploy the current commit; fix or revert it on `main`) |

Settings read by the ops scripts (environment or `.env`):

| Variable | Default | Meaning |
|---|---|---|
| `SA_ALERT_WEBHOOK_URL` | – | where alerts are POSTed (§5) |
| `SA_ALERT_FORMAT` | `text` | `text` (ntfy-style) · `slack` · `discord` |
| `SA_DEPLOY_MAX_WAIT_S` | `600` | max wait for in-flight generations before restarting the backend |
| `SA_DEPLOY_HEALTH_TIMEOUT_S` | `120` | how long a new release gets to become healthy |
| `SA_BACKUP_DIR` | `backups` | backup location (relative to the repo, or absolute) |
| `SA_BACKUP_KEEP_DAILY` / `_WEEKLY` | `14` / `8` | rotation |

### Settings in the app

Sign in at `/admin` → **Settings** to see the main settings the backend runs with (models, budget,
limits, timeouts, whether the API keys are set) and where each comes from: the app's default, the server's `.env` (named), or a change made on that page. It also lists
today's AI calls and cost per model, which shows which model is really answering.

The **AI models** (from the list the app was tested with) and the **daily AI budget** can be changed
there. A change applies to the next lesson at once, survives restarts and **wins over `.env`**;
**Undo** returns to the `.env` value, else the default. Everything else (limits, timeouts) is changed
in `.env` and applied with `docker compose up -d backend`. API keys stay in `.env` and are shown only
as set / not set.

> Servers installed before 2026-10-28 have `SA_MODEL_ID=claude-opus-4-8` and
> `SA_SANITIZER_MODEL_ID=claude-haiku-4-5` in `.env` (copied from the old template), which keeps the
> previous models. Switch on the Settings page, or comment the two lines out and restart the backend:
> `sed -i 's/^SA_MODEL_ID=claude-opus-4-8$/# &/; s/^SA_SANITIZER_MODEL_ID=claude-haiku-4-5$/# &/' .env && docker compose up -d backend`

## 8. Images and dependencies

Builds are reproducible: `backend/requirements*.txt` pin **exact** versions of the whole tree, the
frontend installs with `npm ci` from `package-lock.json`, and base images follow a pinned line
(`python:3.12-slim-trixie`, `node:24-alpine` = current LTS, `nginx:1.30-alpine-slim` = current stable) —
`--pull` brings their patch/security releases. The NLTK `cmudict` corpus (textstat) is baked into the
backend image. To upgrade a Python package: bump its pin, build a fresh venv from the file, run the
backend tests and `pip-audit -r backend/requirements.txt`, commit. Containers run with
`no-new-privileges`, the backend as non-root `appuser` (uid 1000), and Docker logs rotate at 3 × 10 MB.
