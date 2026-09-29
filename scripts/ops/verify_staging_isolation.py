#!/usr/bin/env python3
"""Fail if the staging Compose stack could touch production resources.

Renders the production stack (docker-compose.yml) and the staging stack
(docker-compose.yml + docker-compose.staging.yml) with `docker compose config
--format json`, both interpolated from .env.staging so the check runs on a
staging host that has no production .env, then compares:

  * project names, container names, named volumes and networks are disjoint
  * published host ports are disjoint
  * staging containers read only .env.staging (never .env)

If a production .env exists it also refuses shared secrets (only key names are
ever printed, never values) and leftover CHANGE_ME placeholders in .env.staging.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SECRET_KEYS = (
    "POSTGRES_PASSWORD", "SECRET_KEY", "AUTH_SECRET", "AUTH_BRIDGE_SECRET", "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET", "TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY",
)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


# The production stack is rendered with production's defaults for the proxy so that
# staging's PROXY_* values (which come from .env.staging) cannot mask a real overlap.
PRODUCTION_PROXY_DEFAULTS = {"PROXY_CONTAINER_NAME": "plasma_caddy", "PROXY_HTTP_PORT": "80", "PROXY_HTTPS_PORT": "443"}


def render(root: Path, files: list[str], project: str | None, env_file: Path, env: dict[str, str] | None = None) -> dict:
    command = ["docker", "compose", "--env-file", str(env_file)]
    if project:
        command += ["-p", project]
    for name in files:
        command += ["-f", name]
    # Include profile-gated services such as pgadmin.
    command += ["--profile", "*", "config", "--format", "json"]
    done = subprocess.run(command, cwd=root, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if done.returncode != 0:
        sys.exit(f"docker compose config failed for {' '.join(files)}:\n{done.stderr.strip()}")
    return json.loads(done.stdout)


def resources(config: dict) -> dict[str, set[str]]:
    services = config.get("services", {})
    ports: set[str] = set()
    for name, service in services.items():
        if name == "caddy":
            continue  # proxy ports are compared separately: they may only clash on a shared host
        for port in service.get("ports", []) or []:
            if port.get("published"):
                ports.add(str(port["published"]))
    return {
        "containers": {s["container_name"] for s in services.values() if s.get("container_name")},
        "volumes": {v.get("name") or k for k, v in (config.get("volumes") or {}).items()},
        "networks": {n.get("name") or k for k, n in (config.get("networks") or {}).items() if not n.get("external")},
        "ports": ports,
    }


def env_file_names(service: dict) -> list[str]:
    names = []
    for item in service.get("env_file") or []:
        path = item["path"] if isinstance(item, dict) else item
        names.append(Path(path).name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--staging-env", default=".env.staging")
    parser.add_argument("--production-env", default=".env")
    parser.add_argument("--with-proxy", action="store_true", help="also include docker-compose.proxy.yml in both stacks")
    args = parser.parse_args()
    root: Path = args.root
    staging_env = root / args.staging_env
    if not staging_env.exists():
        sys.exit(f"{staging_env} not found")
    proxy = ["docker-compose.proxy.yml"] if args.with_proxy else []

    production = render(root, ["docker-compose.yml", *proxy], "plasma_production_check", staging_env, PRODUCTION_PROXY_DEFAULTS)
    staging = render(root, ["docker-compose.yml", "docker-compose.staging.yml", *proxy], None, staging_env)

    problems: list[str] = []
    if staging.get("name") != "plasma_staging":
        problems.append(f"staging project name is {staging.get('name')!r}, expected 'plasma_staging'")
    prod_resources, staging_resources = resources(production), resources(staging)
    for kind in ("containers", "volumes", "networks", "ports"):
        shared = prod_resources[kind] & staging_resources[kind]
        if shared:
            problems.append(f"staging shares {kind} with production: {sorted(shared)}")
    for kind in ("containers", "volumes", "networks"):
        unprefixed = sorted(n for n in staging_resources[kind] if "staging" not in n)
        if unprefixed:
            problems.append(f"staging {kind} without a staging prefix: {unprefixed}")
    for name, service in staging.get("services", {}).items():
        names = env_file_names(service)
        if names and names != [".env.staging"]:
            problems.append(f"service {name} reads env files {names}; only .env.staging is allowed")

    notes: list[str] = []
    if args.with_proxy:
        def proxy_ports(config: dict) -> set[str]:
            return {str(p["published"]) for p in config["services"].get("caddy", {}).get("ports", []) or [] if p.get("published")}
        clash = proxy_ports(production) & proxy_ports(staging)
        if clash:
            notes.append(
                f"proxy host ports {sorted(clash)} are the same in both stacks: fine on a dedicated staging host, "
                "but staging and production cannot share one host without changing PROXY_HTTP(S)_PORT"
            )

    staging_values = parse_env(staging_env)
    placeholders = sorted(k for k, v in staging_values.items() if "CHANGE_ME" in v)
    if placeholders:
        problems.append(f".env.staging still has CHANGE_ME placeholders: {placeholders}")

    production_env = root / args.production_env
    if production_env.exists() and production_env.resolve() != staging_env.resolve():
        production_values = parse_env(production_env)
        shared_keys = [
            key for key in SECRET_KEYS
            if staging_values.get(key) and staging_values.get(key) == production_values.get(key)
        ]
        if shared_keys:
            problems.append(f"staging reuses production secrets for: {shared_keys}")
        print(f"compared {len(SECRET_KEYS)} secret keys against {args.production_env}")
    else:
        print("production .env not present on this host; secret reuse could not be checked here")

    for note in notes:
        print(f"note: {note}")
    print(
        f"staging containers: {len(staging_resources['containers'])}, volumes: {sorted(staging_resources['volumes'])}, "
        f"networks: {sorted(staging_resources['networks'])}, host ports: {sorted(staging_resources['ports'], key=int)}"
    )
    if problems:
        print("ISOLATION CHECK FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("isolation check passed: no shared project, container, volume, network, host port, env file or secret")
    return 0


if __name__ == "__main__":
    sys.exit(main())
