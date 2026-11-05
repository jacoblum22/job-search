import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "powerbi_login", Path(__file__).resolve().parent.parent / "scripts" / "powerbi_login.py")
powerbi_login = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(powerbi_login)


def test_grants_cover_only_analytics_and_future_tables():
    stmts = powerbi_login.grant_sql()
    assert all("analytics" in s or "DATABASE" in s for s in stmts)
    assert not any("public" in s for s in stmts)
    assert any(s.startswith("ALTER DEFAULT PRIVILEGES IN SCHEMA analytics") for s in stmts)
    assert not any(w in s for s in stmts for w in ("INSERT", "UPDATE", "DELETE", "ALL PRIVILEGES"))
