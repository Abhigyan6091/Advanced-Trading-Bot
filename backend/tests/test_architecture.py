"""Structural guarantees, enforced by inspecting the import graph.

These are the tests that keep the architecture from eroding. A layering rule
that lives only in a document gets violated; one that fails CI does not.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def imports_of(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def modules_in(package: str) -> list[pathlib.Path]:
    return sorted((APP / package).rglob("*.py"))


class TestDomainPurity:
    """The domain layer must not know how anything is stored or executed."""

    FORBIDDEN = ("app.db", "app.api", "app.brokers", "sqlalchemy", "fastapi", "binance")

    @pytest.mark.parametrize("path", modules_in("domain"), ids=lambda p: p.name)
    def test_domain_imports_no_infrastructure(self, path):
        offending = [
            imp
            for imp in imports_of(path)
            for bad in self.FORBIDDEN
            if imp == bad or imp.startswith(bad + ".")
        ]
        assert not offending, f"{path.name} imports infrastructure: {offending}"

    def test_domain_uses_no_floats_for_money(self):
        """Money fields must be Decimal. A float annotation is a bug."""
        for path in modules_in("domain"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Name):
                    assert node.annotation.id != "float", (
                        f"{path.name}: field annotated as float; use Decimal"
                    )


class TestNoLiveTrading:
    """Real-money execution must be absent, not merely switched off."""

    def test_broker_enum_has_no_live_member(self):
        from app.core.config import BrokerKind

        values = {b.value for b in BrokerKind}
        assert values == {"paper", "testnet"}
        assert not any("live" in v or "mainnet" in v for v in values)

    def test_no_production_binance_endpoint_anywhere(self):
        """A hardcoded mainnet URL is how testnet bots become live bots."""
        offenders = []
        for path in APP.rglob("*.py"):
            text = path.read_text()
            for needle in ("fapi.binance.com", "api.binance.com"):
                if needle in text:
                    offenders.append(f"{path.name}: {needle}")
        assert not offenders, f"production endpoints referenced: {offenders}"
