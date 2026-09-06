"""Mandatory loopback/disposable guard before release gates open any database."""
import os
import re


def assert_local_test_target():
    if os.environ.get("POSTGRES_SERVER") not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Release gate requires an explicitly configured loopback PostgreSQL host")
    if not re.fullmatch(r"plasma_s05b4b_[a-z0-9_]+", os.environ.get("POSTGRES_DB", "")):
        raise RuntimeError("Release gate requires a disposable plasma_s05b4b_ database")
    if os.environ.get("PLASMA_RELEASE_TEST_CONFIRM") != "DISPOSABLE_LOCAL_ONLY":
        raise RuntimeError("Set PLASMA_RELEASE_TEST_CONFIRM=DISPOSABLE_LOCAL_ONLY")
    if os.environ.get("ENVIRONMENT", "test") not in {"test", "development"}:
        raise RuntimeError("Release gates cannot use release/production service configuration")


if __name__ == "__main__":
    assert_local_test_target()
