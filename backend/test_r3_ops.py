"""R3 ops: DNS guard, monitor alerts, Telegram notify, backup tiers/R2, systemd units.

Scripts run against fake `docker` and `curl` binaries on PATH (as in test_ops_1_host_safety.py);
the real-host proofs are in docs/ops/BACKUPS.md and docs/ops/HOST_SETUP.md.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "scripts" / "ops"
TOKEN = "123456789:AAH-secret-telegram-token-value"

_FAKE_DOCKER = r"""#!/usr/bin/env bash
# Fake docker for monitor/DNS tests. State comes from files in $FAKE_DIR.
args="$*"
case "$1" in
  ps)
    case "$args" in
      *"com.docker.compose.service="*)
        service="$(printf '%s' "$args" | sed -n 's/.*com.docker.compose.service=\([a-z_]*\).*/\1/p')"
        grep -q " plasma_$service " "$FAKE_DIR/containers" 2>/dev/null && echo "cid_$service" ;;
      *) awk '{print $1}' "$FAKE_DIR/containers" ;;
    esac ;;
  inspect)
    case "$args" in
      *RestartCount*) shift 3; for id in "$@"; do awk -v id="$id" '$1 == id {print "/" $2, $3, $4, $5, $6, $7}' "$FAKE_DIR/containers"; done ;;
      *"{{.Image}}"*) echo sha256:backendimage ;;
      *NetworkMode*) echo plasmaos_default ;;
      *"State.Status"*) cat "$FAKE_DIR/clamav" ;;
    esac ;;
  run) cat "$FAKE_DIR/dns"; exit "$(cat "$FAKE_DIR/dns_rc")" ;;
  exec)
    case "$args" in
      *redis-cli*) cat "$FAKE_DIR/beat" ;;
      *source_freshness*) cat "$FAKE_DIR/freshness" ;;
    esac ;;
esac
exit 0
"""

_FAKE_CURL = r"""#!/usr/bin/env bash
# Fake curl: /health/ready from $FAKE_DIR/ready; Telegram sends are recorded (args + -K config).
case "$*" in
  *"-K -"*) { printf 'ARGS %s\n' "$*"; cat; printf '\n'; } >>"$FAKE_DIR/telegram"; cat "$FAKE_DIR/telegram_reply" ;;
  *) cat "$FAKE_DIR/ready" ;;
esac
"""


def _fakes(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", _FAKE_DOCKER), ("curl", _FAKE_CURL)):
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    fake = tmp_path / "fake"
    fake.mkdir()
    healthy = {
        "containers": "\n".join(
            f"id_{name} plasma_{name} id_{name} 0 false 2026-10-08T10:00:00Z running"
            for name in ("db", "redis", "backend", "celery_worker", "celery_beat", "clamav")
        ) + "\n",
        "dns": "db=172.18.0.2\nredis=172.18.0.3\nclamav=172.18.0.4\nDNS_OK\n", "dns_rc": "0",
        "ready": '{"ready":true,"dependencies":{"database":true,"redis":true}}',
        "beat": "1791500000\n",
        "freshness": "source=world_bank cadence_s=21600 last_success_age_s=3600 verdict=ok\n",
        "clamav": "running healthy\n",
        "telegram_reply": '{"ok":true,"result":{}}',
    }
    for name, value in healthy.items():
        (fake / name).write_text(value, encoding="utf-8")
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_DIR": str(fake),
            "MONITOR_STATE_DIR": str(tmp_path / "state"), "OPS_LOCAL_PROJECT": "plasmaos",
            "MONITOR_DISK_PATH": str(tmp_path), "MONITOR_DISK_PERCENT": "100",
            "OPS_TELEGRAM_BOT_TOKEN": TOKEN, "OPS_TELEGRAM_CHAT_ID": "-1001", "OPS_HOST_LABEL": "prod"}


def _monitor(env: dict[str, str], now: int) -> subprocess.CompletedProcess[str]:
    full = {**os.environ, **env, "MONITOR_NOW": str(now)}
    return subprocess.run(["bash", str(OPS / "monitor.sh"), "--target", "local"], cwd=ROOT, env=full,
                          capture_output=True, text=True, timeout=60)


def _sent(env: dict[str, str]) -> list[str]:
    path = Path(env["FAKE_DIR"]) / "telegram"
    if not path.exists():
        return []
    messages = []
    for block in path.read_text(encoding="utf-8").split("ARGS ")[1:]:
        match = re.search(r"--data-urlencode text=(.*?) --data-urlencode disable_web_page_preview", block, re.S)
        messages.append(match.group(1) if match else block)
    return messages


def _set(env: dict[str, str], name: str, value: str) -> None:
    (Path(env["FAKE_DIR"]) / name).write_text(value, encoding="utf-8")


# ---- DNS guard -----------------------------------------------------------------------------------------

def test_dns_check_runs_a_fresh_container_and_reports_ok_fail_and_unavailable(tmp_path) -> None:
    env = _fakes(tmp_path)

    def dns() -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", "-c", 'source scripts/ops/lib.sh && ops_dns_check plasmaos'], cwd=ROOT,
                              env={**os.environ, **env}, capture_output=True, text=True, timeout=30)

    ok = dns()
    assert ok.returncode == 0 and ok.stdout.strip().endswith("DNS_OK")
    _set(env, "dns", "db=UNRESOLVED (gaierror)\nredis=172.18.0.3\nclamav=172.18.0.4\nDNS_FAIL db\n")
    _set(env, "dns_rc", "1")
    failed = dns()
    assert failed.returncode == 1 and "DNS_FAIL db" in failed.stdout
    _set(env, "containers", "")
    assert dns().returncode == 2  # no backend container: cannot check
    lib = (OPS / "lib.sh").read_text(encoding="utf-8")
    assert 'run --rm --pull never --network "$network"' in lib and "--oom-score-adj 1000" in lib
    assert 'DNS_REMEDY="docker restart plasma_db plasma_redis plasma_clamav; then restart app services"' in lib
    smoke = (OPS / "smoke.sh").read_text(encoding="utf-8")
    assert 'ops_dns_check "$PROJECT"' in smoke and "Remedy: $DNS_REMEDY" in smoke


# ---- monitor ---------------------------------------------------------------------------------------------

def test_monitor_alerts_on_change_throttles_and_recovers(tmp_path) -> None:
    env = _fakes(tmp_path)
    t0 = 1_791_500_010
    first = _monitor(env, t0)
    assert first.returncode == 0, first.stderr
    assert "MONITOR_RESULT project=plasmaos checks=7 failing=0 messages=0" in first.stdout
    assert _sent(env) == []                                     # healthy start: silence

    _set(env, "dns", "db=UNRESOLVED (gaierror)\nredis=172.18.0.3\nclamav=172.18.0.4\nDNS_FAIL db redis\n")
    _set(env, "dns_rc", "1")
    _set(env, "ready", '{"detail":"database unavailable"}')
    _monitor(env, t0 + 300)
    sent = _sent(env)
    assert len(sent) == 1                                       # one message per run
    assert "ALERT dns" in sent[0] and "docker restart plasma_db plasma_redis plasma_clamav" in sent[0]
    assert "ALERT ready" in sent[0] and sent[0].startswith("[prod] ")

    _monitor(env, t0 + 600)                                     # still failing: no repeat
    assert len(_sent(env)) == 1
    _set(env, "dns", "DNS_OK\n"); _set(env, "dns_rc", "0")
    _set(env, "ready", '{"ready":true}')
    held = _monitor(env, t0 + 900)                              # recovered after 10 min: held (throttle)
    assert len(_sent(env)) == 1 and "message held" in held.stderr
    _monitor(env, t0 + 300 + 1800)                              # 30 min after the alert: recovery
    sent = _sent(env)
    assert len(sent) == 2 and "RECOVERED dns" in sent[1] and "RECOVERED ready" in sent[1]
    _monitor(env, t0 + 300 + 3600)
    assert len(_sent(env)) == 2                                 # healthy: silence again

    telegram = (Path(env["FAKE_DIR"]) / "telegram").read_text(encoding="utf-8")
    for line in telegram.splitlines():                          # the token is only in the -K config
        if line.startswith("ARGS"):
            assert TOKEN not in line


def test_monitor_reports_restarts_oom_stale_beat_stale_sources_disk_and_clamav(tmp_path) -> None:
    env = _fakes(tmp_path)
    t0 = 1_791_500_010
    _monitor(env, t0)
    containers = (Path(env["FAKE_DIR"]) / "containers").read_text(encoding="utf-8")
    containers = containers.replace("id_celery_worker 0 false 2026-10-08T10:00:00Z",
                                    "id_celery_worker 1 true 2026-10-08T12:00:00Z")
    # A redeployed backend (new id) is not a restart.
    containers = containers.replace("plasma_backend id_backend 0", "plasma_backend id_backend_new 0")
    _set(env, "containers", containers)
    _set(env, "beat", str(t0 + 300 - 400) + "\n")
    _set(env, "freshness", "source=world_bank cadence_s=21600 last_success_age_s=50000 verdict=stale\n"
                           "source=giz cadence_s=86400 last_success_age_s=-1 verdict=stale\n"
                           "source=uzex cadence_s=21600 last_success_age_s=100 verdict=ok\n")
    _set(env, "clamav", "running unhealthy\n")
    env["MONITOR_DISK_PERCENT"] = "0"
    result = _monitor(env, t0 + 300)
    message = _sent(env)[0]
    assert "plasma_celery_worker restarted (restart count 0 -> 1), OOM-killed" in message
    assert "backend" not in message.split("ALERT containers:")[1].split("\n")[0]
    assert "ALERT beat: heartbeat 400s old" in message
    assert "world_bank last success 13.9h ago (cadence 6h)" in message and "giz last success never" in message
    assert "uzex" not in message
    assert "ALERT clamav: ClamAV running unhealthy" in message and "ALERT disk:" in message
    assert "failing=5" in result.stdout

    # The restart keeps "containers" failing for one window, then it recovers by itself.
    _set(env, "containers", containers)
    assert "containers fail" in _monitor(env, t0 + 600).stdout
    assert "containers ok" in _monitor(env, t0 + 300 + 1800).stdout


def test_monitor_retries_an_undelivered_alert_and_dry_run_records_nothing(tmp_path) -> None:
    env = _fakes(tmp_path)
    t0 = 1_791_500_010
    _set(env, "ready", "connection refused")
    _set(env, "telegram_reply", '{"ok":false,"description":"Bad Request: chat not found"}')
    failed = _monitor(env, t0)
    assert failed.returncode == 1 and "chat not found" in failed.stderr and TOKEN not in failed.stderr
    _set(env, "telegram_reply", '{"ok":true}')
    assert _monitor(env, t0 + 300).returncode == 0            # not recorded as sent: sent now
    assert len(_sent(env)) == 2 and "ALERT ready" in _sent(env)[1]

    (tmp_path / "dry").mkdir()
    dry_env = _fakes(tmp_path / "dry")
    _set(dry_env, "ready", "connection refused")
    dry = subprocess.run(["bash", str(OPS / "monitor.sh"), "--target", "local", "--dry-run"], cwd=ROOT,
                         env={**os.environ, **dry_env, "MONITOR_NOW": str(t0)}, capture_output=True, text=True, timeout=60)
    assert "would send:" in dry.stdout and _sent(dry_env) == []
    assert not list(Path(dry_env["MONITOR_STATE_DIR"]).glob("check.*"))


def test_notify_needs_configuration_and_never_prints_the_token(tmp_path) -> None:
    env = _fakes(tmp_path)
    unconfigured = {key: value for key, value in {**os.environ, **env}.items() if not key.startswith("OPS_TELEGRAM")}
    result = subprocess.run(["bash", str(OPS / "notify.sh"), "backup failed"], cwd=ROOT, env=unconfigured,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 3 and "backup failed" in result.stderr
    sent = subprocess.run(["bash", str(OPS / "notify.sh"), "hello"], cwd=ROOT, env={**os.environ, **env},
                          capture_output=True, text=True, timeout=30)
    assert sent.returncode == 0 and TOKEN not in sent.stdout + sent.stderr
    config = (Path(env["FAKE_DIR"]) / "telegram").read_text(encoding="utf-8")
    assert f'url = "https://api.telegram.org/bot{TOKEN}/sendMessage"' in config  # via -K config on stdin only


# ---- backups -----------------------------------------------------------------------------------------------

_FAKE_BACKUP_DOCKER = r"""#!/usr/bin/env bash
# Fake docker for backup.sh: one stack whose db dumps a unique payload and whose backend tars $FAKE_APP.
case "$1" in
  ps) echo "cid" ;;
  exec)
    case "$*" in
      *pg_dump*) printf 'PGDMP-fake-%s-%s\n' "$(date +%s%N)" "$RANDOM" ;;
      *pg_restore*) cat >/dev/null ;;
      *"tar -C /app -czf -"*) dir="${@: -1}"; tar -C "$FAKE_APP" -czf - "$dir" ;;
    esac ;;
esac
"""


def _backup(tmp_path: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    if not bin_dir.exists():
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(_FAKE_BACKUP_DOCKER, encoding="utf-8")
        (bin_dir / "docker").chmod(0o755)
        for sub, content in (("private-data", "private upload"), ("data", "tender document")):
            (tmp_path / "app" / sub).mkdir(parents=True)
            (tmp_path / "app" / sub / "file.txt").write_text(content, encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_APP": str(tmp_path / "app"),
           "BACKUP_DIR": str(tmp_path / "local"), "BACKUP_REMOTE": f"file://{tmp_path / 'remote'}", **extra}
    return subprocess.run(["bash", str(OPS / "backup.sh"), "--target", "local", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


def _sets(directory: Path) -> list[str]:
    return sorted(path.name[: -len(".manifest")] for path in directory.glob("*.manifest")) if directory.exists() else []


def test_backup_tiers_keep_their_own_newest_sets_and_weekly_tender_documents_are_opt_in(tmp_path) -> None:
    for _ in range(3):
        result = _backup(tmp_path, "--tier", "daily", BACKUP_DAILY_KEEP="2")
        assert result.returncode == 0, result.stderr
        assert "tier=daily" in result.stdout and "tender_documents=skipped" in result.stdout
        time.sleep(1.1)  # set names carry a one-second timestamp
    daily = tmp_path / "remote" / "daily"
    assert len(_sets(daily)) == 2                                     # newest 2 kept
    assert not list(daily.glob("*.tender.tar.gz"))                    # never in a daily set
    assert "the daily tier keeps the newest 2" in result.stderr

    weekly = _backup(tmp_path, "--tier", "weekly")
    assert weekly.returncode == 0 and "tender_documents=skipped" in weekly.stdout   # off by default
    time.sleep(1.1)
    with_tender = _backup(tmp_path, "--tier", "weekly", BACKUP_WEEKLY_TENDER_DOCUMENTS="1")
    assert with_tender.returncode == 0 and "tender_documents=included" in with_tender.stdout
    assert len(_sets(tmp_path / "remote" / "weekly")) == 2 and len(_sets(daily)) == 2  # tiers are independent
    assert len(list((tmp_path / "remote" / "weekly").glob("*.tender.tar.gz"))) == 1
    manifest = next((tmp_path / "remote" / "weekly").glob("*.manifest")).read_text(encoding="utf-8")
    assert "tier=weekly" in manifest
    assert _backup(tmp_path, "--tier", "monthly").returncode != 0


def test_untiered_backup_keeps_the_runbook_behaviour(tmp_path) -> None:
    result = _backup(tmp_path, "--skip-tender-documents")
    assert result.returncode == 0, result.stderr
    assert len(_sets(tmp_path / "remote")) == 1 and "tier=none" in result.stdout


def test_r2_remote_is_configured_from_the_environment_and_never_printed(tmp_path) -> None:
    script = (
        'source scripts/ops/lib.sh; source scripts/ops/remote_lib.sh\n'
        'remote_setup r2://acct-bucket/plasma; remote_subdir daily\n'
        'echo "kind=$REMOTE_KIND rpath=$RPATH desc=$REMOTE_DESC"\n'
        'echo "endpoint=$RCLONE_CONFIG_PLASMAR2_ENDPOINT$AWS_ENDPOINT_URL"\n'
        'echo "failed: https://0123abcd.r2.cloudflarestorage.com/acct-bucket key AKIAR2KEYID secret r2-secret-value" >&2\n'
    )
    base = {**os.environ, "BACKUP_S3_ENDPOINT": "https://0123abcd.r2.cloudflarestorage.com",
            "BACKUP_S3_ACCESS_KEY_ID": "AKIAR2KEYID", "BACKUP_S3_SECRET_ACCESS_KEY": "r2-secret-value"}
    for tool, kind, rpath in (("rclone", "rclone", "plasmar2:acct-bucket/plasma/daily"), ("aws", "s3", "s3://acct-bucket/plasma/daily")):
        result = subprocess.run(["bash", "-c", script], cwd=ROOT, env={**base, "BACKUP_S3_TOOL": tool},
                                capture_output=True, text=True, timeout=30)
        assert f"kind={kind} rpath={rpath}" in result.stdout
        assert "desc=r2:<bucket>/plasma/daily via " + tool in result.stdout
        assert "endpoint=https://0123abcd.r2.cloudflarestorage.com" in result.stdout  # passed to the tool by env only
        assert result.stderr.strip() == "failed: https://<endpoint>/<bucket> key <secret> secret <secret>"
    missing = subprocess.run(["bash", "-c", script], cwd=ROOT,
                             env={**os.environ, "BACKUP_S3_ENDPOINT": "https://x"}, capture_output=True, text=True, timeout=30)
    assert missing.returncode != 0 and "BACKUP_S3_ACCESS_KEY_ID" in missing.stderr


def test_restore_drill_restores_into_staging_only_and_verifies_against_the_manifest() -> None:
    drill = (OPS / "restore_drill.sh").read_text(encoding="utf-8")
    assert "restore_to_staging.sh\" --src \"$DEST\"" in drill and "smoke.sh\" --target staging" in drill
    assert "does not match its manifest" in drill and "sha256sum -c --quiet" in drill
    assert "remote_latest_set" in drill and "--yes" in drill
    assert "production" not in drill.split("set -euo pipefail", 1)[1].replace("Production is never", "")


# ---- systemd units -------------------------------------------------------------------------------------------

def _unit(name: str) -> str:
    return (ROOT / "deploy" / "systemd" / name).read_text(encoding="utf-8")


def test_systemd_units_schedule_backups_and_monitor_and_alert_on_failure() -> None:
    daily, weekly, monitor = _unit("plasma-backup-daily.service"), _unit("plasma-backup-weekly.service"), _unit("plasma-monitor.service")
    assert "--target production --tier daily" in daily and "--target production --tier weekly" in weekly
    assert "monitor.sh --target production" in monitor
    for unit in (daily, weekly, monitor):
        assert "OnFailure=plasma-notify@%n.service" in unit
        assert "EnvironmentFile=/etc/plasma/ops.env" in unit
    assert "notify.sh --unit %i" in _unit("plasma-notify@.service")
    assert "OnCalendar=*-*-* 02:30:00 UTC" in _unit("plasma-backup-daily.timer")
    assert "OnCalendar=Sun *-*-* 03:30:00 UTC" in _unit("plasma-backup-weekly.timer")
    assert "OnUnitActiveSec=5min" in _unit("plasma-monitor.timer")
    example = _unit("ops.env.example")
    assert "BACKUP_WEEKLY_TENDER_DOCUMENTS=0" in example and "OPS_TELEGRAM_BOT_TOKEN=" in example


# ---- runbooks --------------------------------------------------------------------------------------------------

def test_every_app_stop_in_a_runbook_is_preceded_by_the_pre_stop_gate() -> None:
    stops = re.compile(r'compose-release\.sh (stop\b|rollback \$PREV_SHA|use "\$PREV_SHA"|up "\$PREV_SHA" --no-deps \$APPS)')
    checked = 0
    for path in sorted((ROOT / "docs" / "ops").glob("*.md")):
        if path.name == "RUNBOOK_TEMPLATE.md":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if stops.search(line) and not line.lstrip().startswith("#"):
                window = "\n".join(lines[max(0, index - 16):index + 1])
                assert "DNS_OK" in window, f"{path.name}:{index + 1}: no pre-stop gate before: {line.strip()}"
                checked += 1
    assert checked >= 9
    template = (ROOT / "docs" / "ops" / "RUNBOOK_TEMPLATE.md").read_text(encoding="utf-8")
    assert "print('DNS_OK')" in template and "/health/ready" in template and "oom_adj={{.HostConfig.OomScoreAdj}}" in template
    assert "docker restart plasma_db plasma_redis plasma_clamav; then restart app services" in template
