"""OPS-1 host safety: static checks of the compose memory profile, release and ops scripts.

Behaviour (export/import round trip, no-build refusals, streaming backup, prune keep rules)
was proven against a real Docker host; see docs/ops/PRODUCTION_READINESS.md. These tests
keep the guarantees from regressing.
"""

from __future__ import annotations

from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP_SERVICES = (
    "clamav", "backend", "frontend", "celery_worker", "worker_heavy",
    "worker_private_documents", "worker_pursuit_analysis", "celery_beat",
)
WORKERS = ("celery_worker", "worker_heavy", "worker_private_documents", "worker_pursuit_analysis")


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _profile(name: str) -> dict[str, str]:
    values = {}
    for line in (ROOT / "deploy" / "host-profiles" / f"{name}.env").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _mib(value: str) -> int:
    number, unit = re.fullmatch(r"(\d+)([mg])", value).groups()
    return int(number) * (1024 if unit == "g" else 1)


def test_every_app_service_is_limited_without_swap_and_datastores_are_protected() -> None:
    services = _compose()["services"]
    for name in APP_SERVICES:
        service = services[name]
        assert service["mem_limit"].startswith("${PLASMA_MEM_"), name
        assert service["memswap_limit"] == service["mem_limit"], name
    for name in WORKERS:
        assert services[name]["oom_score_adj"] > 0, name
        assert any("--max-memory-per-child=${PLASMA_CHILD_KB_" in arg for arg in services[name]["command"]), name
    for name, adj in (("db", -800), ("redis", -500)):
        assert "mem_limit" not in services[name], name
        assert services[name]["oom_score_adj"] == adj
    # Unchanged guarantees other suites rely on.
    assert services["db"]["ports"] == ["127.0.0.1:6543:5432"]
    assert services["pgadmin"]["profiles"] == ["tools"]
    assert services["clamav"]["environment"]["CLAMD_CONF_ConcurrentDatabaseReload"] == "no"
    assert "--max-tasks-per-child=10" in services["worker_heavy"]["command"]


def test_postgres_defaults_without_a_profile_are_postgres_own_defaults() -> None:
    command = " ".join(_compose()["services"]["db"]["command"])
    for setting in ("shared_buffers=${PG_SHARED_BUFFERS:-128MB}", "work_mem=${PG_WORK_MEM:-4MB}",
                    "maintenance_work_mem=${PG_MAINTENANCE_WORK_MEM:-64MB}",
                    "max_connections=${PG_MAX_CONNECTIONS:-100}"):
        assert setting in command


def test_profiles_define_every_variable_the_compose_file_reads() -> None:
    source = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    used = set(re.findall(r"\$\{((?:PLASMA_MEM|PLASMA_CHILD_KB|PG)_[A-Z_]+)", source))
    for name in ("4gb", "8gb"):
        profile = _profile(name)
        assert profile["HOST_PROFILE"] == name
        assert used <= set(profile), (name, used - set(profile))


def test_4gb_profile_fits_the_measured_host_and_8gb_scales_up() -> None:
    small, large = _profile("4gb"), _profile("8gb")
    assert small["PLASMA_MEM_CLAMAV"] == "1536m"          # above the ~1.3 GiB reload peak
    assert small["PURSUIT_ANALYSIS_WORKER_CONCURRENCY"] == "1"
    assert large["PURSUIT_ANALYSIS_WORKER_CONCURRENCY"] == "2"
    limits = [key for key in small if key.startswith("PLASMA_MEM_")]
    assert sum(_mib(small[key]) for key in limits) == 3296  # documented 3.22 GiB
    assert sum(_mib(large[key]) for key in limits) == 6272
    for key in limits:
        assert _mib(large[key]) >= _mib(small[key]), key
    # Per-child caps fit inside the container limit.
    for service in WORKERS:
        suffix = service.upper()
        for profile in (small, large):
            assert int(profile[f"PLASMA_CHILD_KB_{suffix}"]) // 1024 < _mib(profile[f"PLASMA_MEM_{suffix}"])


def test_pursuit_concurrency_default_is_unchanged_so_profiles_own_the_value() -> None:
    command = _compose()["services"]["worker_pursuit_analysis"]["command"]
    assert "--concurrency=${PURSUIT_ANALYSIS_WORKER_CONCURRENCY:-2}" in command


def test_release_script_refuses_builds_on_no_build_hosts_and_moves_images_as_streams() -> None:
    script = (ROOT / "scripts" / "compose-release.sh").read_text(encoding="utf-8")
    for needle in (
        'NO_BUILD="$(setting PLASMA_NO_BUILD)"', "build|--build) die", "this host does not build images",
        "--no-build", '"$DOCKER_BIN" save "${refs[@]}"', '"$DOCKER_BIN" load', "require_release_images",
        "deploy/host-profiles/$HOST_PROFILE.env", "record_release",
        "PLASMA_NO_BUILD=1 host without HOST_PROFILE",
    ):
        assert needle in script, needle


def test_backup_streams_documents_off_host_and_refuses_without_a_remote() -> None:
    script = (ROOT / "scripts" / "ops" / "backup.sh").read_text(encoding="utf-8")
    assert "BACKUP_REMOTE is not set: backups must go off-host" in script
    assert "--skip-tender-documents" in script
    assert "--local is for development only" in script
    # Documents go through the streaming path only; no archive file is written locally.
    assert 'tar -C /app -czf - "$dir" </dev/null 2>"$WORK/tar.err" | send "$name" tgz' in script
    assert 'archive "$NAME.private.tar.gz" private-data' in script
    assert ".files.tar.gz" not in script
    assert "remote checksum" in script


def test_prune_never_touches_volumes_or_prunes_the_system() -> None:
    script = (ROOT / "scripts" / "ops" / "prune_safe.sh").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "volume" not in code
    assert "system prune" not in code
    assert "image prune -f" in code and "image prune -a" not in code
    assert 'if [ "$APPLY" = "1" ]; then "$@"; else echo "  would run: $*"; fi' in code
    assert "kept_present" in code  # at least two releases actually on the host


def test_disk_report_is_read_only() -> None:
    script = (ROOT / "scripts" / "ops" / "disk_report.sh").read_text(encoding="utf-8")
    for forbidden in ("image rm", "image prune", "builder prune", "system prune", "volume rm", "volume prune", '" tag ', "rm -"):
        assert forbidden not in script, forbidden
