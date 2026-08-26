from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = ROOT.parent / "frontend"


def read_backend(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_frontend(path: str) -> str:
    return (FRONTEND_ROOT / path).read_text(encoding="utf-8")


class ReleaseAdminRepairTests(unittest.TestCase):
    def test_safe_version_health_endpoint_reports_release_and_alembic(self) -> None:
        main = read_backend("app/main.py")
        release = read_backend("app/core/release.py")
        celery_app = read_backend("app/core/celery_app.py")

        self.assertIn('"/api/v1/health/version"', main)
        self.assertIn('"/api/v1/health/version/internal"', main)
        self.assertIn("Depends(require_admin)", main)
        self.assertIn("release_metadata_with_database", main)
        self.assertIn("plasma_release_identity", celery_app)
        self.assertIn("public_release_metadata", celery_app)
        self.assertIn("PLASMA_BUILD_SHA", release)
        self.assertIn("PLASMA_BUILD_TIME", release)
        self.assertIn("alembic_revision", release)
        self.assertIn("alembic_head", release)
        self.assertNotIn("hostname", release)
        self.assertNotIn("PLASMA_ADMIN_EMAILS", release)

    def test_frontend_defaults_to_same_origin_api_without_localhost_target(self) -> None:
        api = read_frontend("lib/api.ts")
        dockerfile = read_frontend("Dockerfile")
        next_config = read_frontend("next.config.ts")
        auth_config = read_frontend("auth.ts")
        auth_route = read_frontend("app/api/auth/[...nextauth]/route.ts")
        proxy = read_frontend("lib/documentProxy.ts")
        backend_resolver = read_frontend("lib/backendApiBase.ts")
        middleware = read_frontend("middleware.ts")

        self.assertIn("const apiBaseUrl = '/api/v1';", api)
        self.assertIn("ARG NEXT_PUBLIC_API_URL=/api/v1", dockerfile)
        self.assertIn("http://backend:8000/api/v1", next_config)
        self.assertIn("resolveBackendApiBase", auth_config)
        self.assertIn("import { handlers } from '@/auth';", auth_route)
        self.assertIn("resolveBackendApiBase", proxy)
        self.assertIn("PUBLIC_EXACT_PATHS = ['/api/v1/health/version']", middleware)
        self.assertNotIn(
            "localhost:8000",
            api + dockerfile + next_config + auth_config + auth_route + proxy + backend_resolver,
        )

    def test_auth_module_split_and_document_proxy_preserve_security_contract(self) -> None:
        auth_config = read_frontend("auth.ts")
        auth_route = read_frontend("app/api/auth/[...nextauth]/route.ts")
        proxy = read_frontend("lib/documentProxy.ts")

        self.assertIn("export const { handlers, auth } = NextAuth({", auth_config)
        self.assertIn("secret: process.env.AUTH_SECRET", auth_config)
        self.assertEqual(
            auth_route.strip(),
            "import { handlers } from '@/auth';\n\nexport const { GET, POST } = handlers;",
        )
        self.assertIn('import { auth } from "@/auth";', proxy)
        self.assertIn("const session = await auth();", proxy)
        self.assertIn("if (!accessToken)", proxy)
        self.assertNotIn("if (session)", proxy)
        self.assertNotIn("if (!session)", proxy)
        self.assertIn('{ detail: "Unauthorized" }, { status: 401 }', proxy)
        self.assertIn(
            "`${backendApiBase}/tenders/documents/${id}/download`",
            proxy,
        )
        self.assertNotIn("request.url", proxy)
        self.assertNotIn("new URL", proxy)
        self.assertNotIn("console.log", proxy)
        self.assertNotIn("console.error(accessToken", proxy)

    def test_compose_release_builds_have_real_identity_inputs(self) -> None:
        compose = (ROOT.parent / "docker-compose.yml").read_text(encoding="utf-8")
        script = (ROOT.parent / "scripts/compose-release.sh").read_text(encoding="utf-8")

        self.assertIn("FRONTEND_NEXT_PUBLIC_API_URL:-/api/v1", compose)
        self.assertIn("PLASMA_SERVICE_NAME: backend", compose)
        self.assertIn("PLASMA_SERVICE_NAME: worker_heavy", compose)
        self.assertIn("git rev-parse HEAD", script)
        self.assertIn('date -u +"%Y-%m-%dT%H:%M:%SZ"', script)

    def test_admin_repair_migration_adds_session_version_and_activity_log(self) -> None:
        migration = read_backend("alembic/versions/20260706_0001_release_identity_admin_repair.py")
        user_model = read_backend("app/models/user.py")
        audit_model = read_backend("app/models/audit.py")

        self.assertIn("20260706_0001_release_identity_admin_repair", migration)
        self.assertIn("down_revision", migration)
        self.assertIn('"auth_version"', migration)
        self.assertIn('"admin_activity_events"', migration)
        self.assertIn("auth_version", user_model)
        self.assertIn("class AdminActivityEvent", audit_model)

    def test_auth_reconciliation_bumps_sessions_and_records_activity(self) -> None:
        auth = read_backend("app/api/endpoints/auth.py")
        security = read_backend("app/core/security.py")
        admin = read_backend("app/api/endpoints/admin.py")

        self.assertIn("record_admin_activity", auth)
        self.assertIn("auth_allowlist_reconciled", auth)
        self.assertIn("bump_auth_version(user)", auth)
        self.assertIn('"auth_version"', auth)
        self.assertIn("Fresh authentication required", security)
        self.assertIn("bump_auth_version(user)", admin)
        self.assertIn("recent_events", admin)

    def test_admin_management_command_requires_allowlist_and_google_identity(self) -> None:
        command = read_backend("app/cli/admin_management.py")

        self.assertIn("inspect", command)
        self.assertIn("promote", command)
        self.assertIn("--google-id", command)
        self.assertIn("google_id_mismatch", command)
        self.assertIn("email_not_in_PLASMA_ADMIN_EMAILS", command)
        self.assertIn("schema_not_migrated", command)
        self.assertIn("admin_promoted", command)
        self.assertNotIn("haqqulzoda@gmail.com", command)


if __name__ == "__main__":
    unittest.main()
