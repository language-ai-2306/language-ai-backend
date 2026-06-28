"""Unit tests for app/services/config_service.py."""

import pytest
from sqlalchemy.orm import Session

from app.models.app_config import AppConfig
from app.services import config_service


@pytest.fixture()
def cfg_db(db: Session) -> Session:
    """DB session pre-seeded with a small config set."""
    rows = [
        AppConfig(key="count",    value="42",    value_type="int",   description="an int",   is_editable=True),
        AppConfig(key="ratio",    value="3.14",  value_type="float", description="a float",  is_editable=True),
        AppConfig(key="enabled",  value="true",  value_type="bool",  description="a bool",   is_editable=True),
        AppConfig(key="label",    value="hello", value_type="str",   description="a string", is_editable=True),
        AppConfig(key="readonly", value="fixed", value_type="str",   description="ro",       is_editable=False),
        AppConfig(key="bad_int",  value="oops",  value_type="int",   description="corrupt",  is_editable=True),
    ]
    db.add_all(rows)
    db.commit()
    return db


# ── get ───────────────────────────────────────────────────────────────────────

class TestGet:
    def test_found(self, cfg_db):
        assert config_service.get("label", cfg_db) == "hello"

    def test_not_found_returns_default(self, cfg_db):
        assert config_service.get("missing", cfg_db, default="fallback") == "fallback"

    def test_not_found_empty_string_default(self, cfg_db):
        assert config_service.get("missing", cfg_db) == ""


# ── get_int ───────────────────────────────────────────────────────────────────

class TestGetInt:
    def test_returns_integer(self, cfg_db):
        assert config_service.get_int("count", cfg_db) == 42

    def test_missing_key_returns_default(self, cfg_db):
        assert config_service.get_int("missing", cfg_db, default=99) == 99

    def test_corrupt_value_returns_default(self, cfg_db):
        assert config_service.get_int("bad_int", cfg_db, default=0) == 0


# ── get_float ─────────────────────────────────────────────────────────────────

class TestGetFloat:
    def test_returns_float(self, cfg_db):
        result = config_service.get_float("ratio", cfg_db)
        assert abs(result - 3.14) < 0.001

    def test_missing_returns_default(self, cfg_db):
        assert config_service.get_float("missing", cfg_db, default=1.5) == 1.5


# ── get_bool ──────────────────────────────────────────────────────────────────

class TestGetBool:
    @pytest.mark.parametrize("value,expected", [
        ("true",  True),
        ("True",  True),
        ("TRUE",  True),
        ("1",     True),
        ("yes",   True),
        ("false", False),
        ("0",     False),
        ("no",    False),
    ])
    def test_various_truthy_falsy(self, db: Session, value, expected):
        db.add(AppConfig(key="flag", value=value, value_type="bool", description="", is_editable=True))
        db.commit()
        assert config_service.get_bool("flag", db) == expected

    def test_missing_returns_default(self, cfg_db):
        assert config_service.get_bool("missing", cfg_db, default=True) is True


# ── set_value ─────────────────────────────────────────────────────────────────

class TestSetValue:
    def test_updates_value_in_db(self, cfg_db):
        config_service.set_value("count", "99", cfg_db)
        assert config_service.get_int("count", cfg_db) == 99

    def test_returns_updated_row(self, cfg_db):
        row = config_service.set_value("label", "world", cfg_db)
        assert row.value == "world"
        assert row.key == "label"

    def test_missing_key_raises_key_error(self, cfg_db):
        with pytest.raises(KeyError, match="not found"):
            config_service.set_value("nonexistent", "x", cfg_db)

    def test_readonly_raises_permission_error(self, cfg_db):
        with pytest.raises(PermissionError, match="read-only"):
            config_service.set_value("readonly", "new", cfg_db)

    def test_invalid_int_raises_value_error(self, cfg_db):
        with pytest.raises(ValueError, match="int"):
            config_service.set_value("count", "not-a-number", cfg_db)

    def test_invalid_bool_raises_value_error(self, cfg_db):
        with pytest.raises(ValueError, match="bool"):
            config_service.set_value("enabled", "maybe", cfg_db)

    def test_valid_bool_accepted(self, cfg_db):
        row = config_service.set_value("enabled", "false", cfg_db)
        assert row.value == "false"
