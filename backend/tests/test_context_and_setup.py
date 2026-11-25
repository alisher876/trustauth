"""Tests for the login context builder (v0) and the factor setup."""

import sys
import types
from datetime import datetime, timezone

import pytest

from app.core.context import ClientInfo, browser_name, build_login_context, device_type
from app.core.factor_setup import register_factors
from app.factors.base import MockFactor, clear_registry, registered_factors

CHROME_WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
EDGE_WINDOWS = CHROME_WINDOWS + " Edg/131.0.0.0"
CHROME_ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
SAFARI_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"


@pytest.mark.parametrize(
    ("ua", "device", "browser"),
    [
        (CHROME_WINDOWS, "laptop", "Chrome 131"),
        (EDGE_WINDOWS, "laptop", "Edge 131"),
        (CHROME_ANDROID, "phone", "Chrome 131"),
        (SAFARI_IPHONE, "phone", "Safari 17"),
        (FIREFOX_LINUX, "laptop", "Firefox 133"),
        ("", "laptop", "unknown"),
    ],
)
def test_user_agent_parsing(ua, device, browser):
    assert device_type(ua) == device
    assert browser_name(ua) == browser


def test_build_login_context_uses_tashkent_hour_and_client_info():
    utc_midnight = datetime(2026, 11, 25, 0, 30, tzinfo=timezone.utc)  # 05:30 in Tashkent
    ctx = build_login_context("L1", CHROME_ANDROID, "203.0.113.5",
                              ClientInfo(has_camera=True, light_hint="dim"), now=utc_midnight)
    assert (ctx.device_type, ctx.hour, ctx.ip, ctx.has_camera) == ("phone", 5, "203.0.113.5", True)
    assert ctx.webauthn_supported is False
    assert ctx.condition == "phone_dim"
    assert (ctx.network, ctx.known_device) == ("unknown", False)  # safe defaults until week 4


def test_register_factors_skips_missing_mocks_and_is_idempotent(monkeypatch):
    # A fake "password mock" module that exists, and a face mock that does not.
    fake_module = types.ModuleType("fake_password_mock")

    class MockPassword(MockFactor):
        name = "password"

    fake_module.MockPassword = MockPassword
    monkeypatch.setitem(sys.modules, "fake_password_mock", fake_module)
    monkeypatch.setattr("app.core.factor_setup.MOCKS", {
        "password": ("fake_password_mock", "MockPassword"),
        "face": ("app.factors.face.mock_that_does_not_exist", "MockFace"),
    })

    clear_registry()
    assert register_factors("mock") == ["password"]
    assert register_factors("mock") == ["password"]  # second call changes nothing
    clear_registry()


def test_register_factors_does_not_hide_a_broken_mock(monkeypatch):
    # The mock file exists but itself imports something missing: that is a bug and must not be skipped.
    monkeypatch.setattr("app.core.factor_setup.MOCKS", {"password": ("app.factors.password.mock", "MockPassword")})

    def import_fails(path):
        error = ModuleNotFoundError("No module named 'numpy_typo'")
        error.name = "numpy_typo"  # the missing module is not the mock file itself
        raise error

    monkeypatch.setattr("app.core.factor_setup.importlib.import_module", import_fails)
    clear_registry()
    with pytest.raises(ModuleNotFoundError):
        register_factors("mock")


def test_register_factors_real_mode_registers_nothing_yet():
    clear_registry()
    assert register_factors("real") == []
    assert registered_factors() == {}
