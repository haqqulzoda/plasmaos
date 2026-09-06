"""Release profile and test-target negative gates; no production connections."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.probe_urls import validate_probe_url
from scripts.release_test_target import assert_local_test_target


def release_settings(**changes):
    values = dict(ENVIRONMENT="release", POSTGRES_SERVER="db", POSTGRES_USER="fixture", POSTGRES_PASSWORD="fixture-only",
        POSTGRES_DB="fixture", SECRET_KEY="s"*40, AUTH_BRIDGE_SECRET="b"*40, TELEGRAM_BOT_TOKEN="fixture",
        BACKEND_CORS_ORIGINS=["https://console.example.invalid"], AUTO_CREATE_TABLES=False, DEMO_OCR_BYPASS=False,PLASMA_ENABLE_PSEUDO_LOCALE=False)
    values.update(changes)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("change", [{"AUTO_CREATE_TABLES":True},{"DEMO_OCR_BYPASS":True},{"PLASMA_ENABLE_PSEUDO_LOCALE":True},
    {"BACKEND_CORS_ORIGINS":["*"]},{"BACKEND_CORS_ORIGINS":["http://example.invalid"]},{"BACKEND_CORS_ORIGINS":[]},
    {"AUTH_BRIDGE_SECRET":""},{"SECRET_KEY":"short"}])
def test_release_rejects_unsafe_configuration(change):
    with pytest.raises(ValidationError): release_settings(**change)


def test_release_accepts_explicit_safe_origins_and_secrets():
    assert release_settings().ENVIRONMENT == "release"


@pytest.mark.parametrize("url", ["http://127.0.0.1", "https://169.254.169.254/latest/meta-data", "file:///etc/passwd",
    "https://example.invalid", "https://etender.uzex.uz.evil.invalid", "https://etender.uzex.uz@127.0.0.1", "https://etender.uzex.uz:8000"])
def test_operator_probe_rejects_untrusted_destinations_without_dns(url):
    with patch("app.core.probe_urls.socket.getaddrinfo", side_effect=AssertionError("No DNS for rejected URL")):
        with pytest.raises(ValueError): validate_probe_url(url)


def test_operator_probe_rejects_private_dns_answer():
    with patch("app.core.probe_urls.socket.getaddrinfo", return_value=[(2,1,6,"",("127.0.0.1",443))]):
        with pytest.raises(ValueError): validate_probe_url("https://etender.uzex.uz/lot/123")


@pytest.mark.parametrize("change", [{"POSTGRES_SERVER":"db.production.invalid"},{"POSTGRES_DB":"plasma_ai"},{"PLASMA_RELEASE_TEST_CONFIRM":""},{"ENVIRONMENT":"production"}])
def test_gates_reject_production_targets_before_importing_database(change):
    values = {"POSTGRES_SERVER":"127.0.0.1","POSTGRES_DB":"plasma_s05b4b_release_fixture","PLASMA_RELEASE_TEST_CONFIRM":"DISPOSABLE_LOCAL_ONLY","ENVIRONMENT":"test"}
    values.update(change)
    with patch.dict(os.environ, values):
        with pytest.raises(RuntimeError): assert_local_test_target()


def test_tracked_compose_has_no_database_publish_or_literal_admin_password():
    import yaml
    root = Path(__file__).resolve().parents[1]
    source = (root / "docker-compose.yml").read_text()
    compose = yaml.safe_load(source)
    assert "ports" not in compose["services"]["db"]
    assert compose["services"]["pgadmin"]["profiles"] == ["development"]
    for name in ("POSTGRES_PASSWORD",):
        assert compose["services"]["db"]["environment"][name].startswith("${")
    assert compose["services"]["pgadmin"]["environment"]["PGADMIN_DEFAULT_PASSWORD"].startswith("${")
    assert "plasma_secure_dev_pass_2026" not in source
    assert "Samadov772." not in source


def test_python_constraints_are_exact_stable_and_cover_installed_requirements():
    from importlib.metadata import version
    from packaging.requirements import Requirement
    from packaging.version import Version
    source = Path(__file__).with_name("constraints.txt").read_text()
    for line in source.splitlines():
        if not line or line.startswith("#"): continue
        requirement = Requirement(line)
        specs = list(requirement.specifier)
        assert len(specs) == 1 and specs[0].operator == "=="
        assert not Version(specs[0].version).is_prerelease
        assert version(requirement.name) == specs[0].version


def test_probe_redirects_and_subresources_are_rechecked():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.core.probe_urls import guard_probe_context
    context = Mock()
    guard_probe_context(context)
    callback = context.route.call_args.args[1]
    with patch('app.core.probe_urls.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]):
        for url, allowed in [('https://etender.uzex.uz/lot/1',True),('http://127.0.0.1/private',False),('https://169.254.169.254/latest',False),('https://untrusted.invalid',False)]:
            route = Mock(request=SimpleNamespace(url=url))
            callback(route)
            assert route.continue_.called is allowed
            assert route.abort.called is not allowed
