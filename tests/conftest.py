"""Shared pytest configuration for the settlement-core test suite."""

import os


# The production Charger fails closed when persistence and credentials are not
# configured.  Tests opt into the explicit in-memory mode before test modules
# import the FastAPI application.
os.environ.setdefault("WAYBILL_CHARGER_TEST_MODE", "1")
os.environ.setdefault("WAYBILL_CHARGER_DATABASE_URL", "sqlite+pysqlite://")
os.environ.setdefault("WAYBILL_CHARGER_DOMAIN", "ruc-demo.charger-test")
os.environ.setdefault("WAYBILL_CHARGER_ADMIN_TOKEN", "waybill-test-admin-token")
os.environ.setdefault("WAYBILL_CHARGER_TOKEN_PEPPER", "waybill-test-token-pepper")
