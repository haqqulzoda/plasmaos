# Production host setup (one-time, owner)

Host: Hetzner 2 vCPU / 3.7 GiB, Ubuntu, checkout at `/opt/plasma-console/plasmaos`. These steps
change the host, not the stack; none of them restarts a container.

## 1. journald size cap (already applied on production; keep it on any rebuilt host)

The systemd journal (Docker's daemon log included) is capped so it can never fill the 38 GB disk:
```
prod$ sudo mkdir -p /etc/systemd/journald.conf.d
prod$ printf '[Journal]\nSystemMaxUse=300M\n' | sudo tee /etc/systemd/journald.conf.d/plasma.conf
prod$ sudo systemctl restart systemd-journald
prod$ journalctl --disk-usage
```
Expect `Archived and active journals take up … ` at most 300 M.

**Rule: before any journal vacuum, save Docker's log to a file.** The journal holds the only record
of Docker daemon events (DNS, network and restart problems, e.g. the Deploy 2 DNS loss); a vacuum
destroys it.
```
prod$ journalctl -u docker --no-pager > $HOME/docker-journal-$(date -u +%Y%m%dT%H%M%SZ).log && ls -l $HOME/docker-journal-*.log
prod$ sudo journalctl --vacuum-size=200M      # only after the file above exists
```

## 2. Operations settings file

All plasma-* units read `/etc/plasma/ops.env` (root, mode 600):
```
prod$ sudo install -d -m 700 /etc/plasma
prod$ sudo install -m 600 deploy/systemd/ops.env.example /etc/plasma/ops.env
prod$ sudo nano /etc/plasma/ops.env
```
Fill the backup lines (docs/ops/BACKUPS.md) and the Telegram lines (section 3). Never paste the
file's values into chat, tickets or logs.

## 3. Telegram alerts

1. In Telegram, talk to **@BotFather** → `/newbot` → name e.g. "Plasma Ops" → copy the token.
2. Create a group "Plasma Ops", add the bot, send any message in the group.
3. `laptop$ curl -s "https://api.telegram.org/bot<token>/getUpdates"` → the group's `"chat":{"id":-100…}`.
4. Put `OPS_TELEGRAM_BOT_TOKEN=<token>`, `OPS_TELEGRAM_CHAT_ID=<id>`, `OPS_HOST_LABEL=plasma-prod`
   in `/etc/plasma/ops.env`. Test:
   ```
   prod$ sudo bash -c 'set -a; . /etc/plasma/ops.env; set +a; scripts/ops/notify.sh "test from $(hostname)"'
   ```
   Expect the message in the group and exit 0. (Exit 3 = not configured; exit 1 = Telegram refused,
   its reason printed. The token is never printed: curl reads the URL from a config on stdin.)

## 4. Install the timers (backups, monitor)

```
prod$ sudo install -m 644 deploy/systemd/plasma-*.service deploy/systemd/plasma-*.timer /etc/systemd/system/
prod$ sudo systemctl daemon-reload
prod$ sudo systemctl enable --now plasma-monitor.timer plasma-backup-daily.timer
prod$ sudo systemctl enable --now plasma-backup-weekly.timer
prod$ systemctl list-timers 'plasma-*'
```
Expect three timers with their next run times. The units run the scripts from the checkout, so a
deploy that changes `scripts/ops/` takes effect at the next run; unit files change only when
`deploy/systemd/` changes (then repeat the `install` and `daemon-reload` lines).
Disable: `sudo systemctl disable --now plasma-monitor.timer` (or a backup timer).

## 5. The host monitor (every 5 minutes)

`scripts/ops/monitor.sh` checks: `/health/ready`; a fresh one-off container resolving `db`,
`redis`, `clamav` (the Deploy 2 DNS failure); container restarts and OOM kills since the last run
(a deploy's recreated containers are not counted) and containers not running; disk above 85 %;
the Beat heartbeat age (60 s, as `smoke.sh`); the last successful refresh of every visible
scheduled source within twice its cadence; ClamAV running and healthy.

It messages Telegram only when a check changes state (an `ALERT`, later a `RECOVERED`), at most
once per check per 30 minutes; a change inside that window is sent when it ends if it still holds.
State lives in `/var/lib/plasma-monitor`. Look at it by hand:
```
prod$ sudo bash -c 'set -a; . /etc/plasma/ops.env; set +a; MONITOR_STATE_DIR=/tmp/monitor-dry scripts/ops/monitor.sh --dry-run'
prod$ journalctl -u plasma-monitor -n 20 -o cat
```
Expect seven lines (`ready ok …`, `dns ok …`, …) and `MONITOR_RESULT … failing=0`.
Cost per run: one 128 MiB-capped container for about 2-10 s (DNS check) and one short Python
process in the backend container (source freshness).
A DNS alert reads: `a fresh container cannot resolve db. Remedy: docker restart plasma_db
plasma_redis plasma_clamav; then restart app services`.

## 6. UptimeRobot (outside view of the public URLs)

The host monitor cannot report a host that is down or unreachable; UptimeRobot can (free plan:
50 monitors, 5-minute interval).
1. https://uptimerobot.com → sign up → **Add New Monitor**.
2. Monitor 1: type **HTTP(s)**, name "Plasma app", URL `https://<APP_DOMAIN>/`, interval 5 min.
3. Monitor 2: type **Keyword**, name "Plasma API ready", URL `https://<API_DOMAIN>/health/ready`,
   keyword `"ready":true`, alert when the keyword is **not** present, interval 5 min.
4. Alert contacts: the owner's e-mail, and Telegram (My Settings → Alert Contacts → Telegram → follow
   the link to add the UptimeRobot bot to the "Plasma Ops" group).
5. Optional: a status page with both monitors.
Expect both monitors green within 5 minutes; pause them during a planned window
(Monitor → Pause) so a deploy does not page.
