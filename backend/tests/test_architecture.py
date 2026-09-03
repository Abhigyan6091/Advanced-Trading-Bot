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


class TestStrategyIsolation:
    """Strategies propose; they cannot execute.

    This is the structural half of the "no trade bypasses risk" guarantee. If a
    strategy could import a broker or construct an Order, the risk engine would
    become advisory rather than mandatory.
    """

    FORBIDDEN = (
        "app.brokers",
        "app.db",
        "app.api",
        "app.portfolio",
        "app.execution",
        "binance",
        "sqlalchemy",
    )

    @pytest.mark.parametrize("path", modules_in("strategies"), ids=lambda p: p.name)
    def test_strategies_cannot_reach_execution(self, path):
        offending = [
            imp
            for imp in imports_of(path)
            for bad in self.FORBIDDEN
            if imp == bad or imp.startswith(bad + ".")
        ]
        assert not offending, f"{path.name} imports execution machinery: {offending}"

    @pytest.mark.parametrize("path", modules_in("strategies"), ids=lambda p: p.name)
    def test_strategies_do_not_name_order_types(self, path):
        """Not even by name: sizing and order construction are not theirs."""
        names = {
            n.id
            for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.Name)
        }
        assert not names & {"Order", "OrderRequest", "Fill", "Position"}, (
            f"{path.name} references order or position types"
        )


class TestMarketDataIsolation:
    def test_market_data_does_not_depend_on_strategies(self):
        """Data flows into strategies, never the other way around."""
        for path in modules_in("marketdata"):
            offending = [i for i in imports_of(path) if i.startswith("app.strategies")]
            assert not offending, f"{path.name} imports strategies: {offending}"


class TestRiskIsMandatory:
    """The risk engine is the only path from a signal to an order."""

    def test_risk_engine_does_not_import_execution(self):
        """It decides; it does not place. Sizing must not become submitting."""
        for path in modules_in("risk"):
            offending = [
                i
                for i in imports_of(path)
                if i.startswith(("app.brokers", "app.execution", "app.api")) or i == "binance"
            ]
            assert not offending, f"{path.name} imports execution machinery: {offending}"

    def test_only_the_risk_package_constructs_a_decision(self):
        """A RiskDecision built elsewhere would be a rubber stamp."""
        allowed = {"risk", "domain", "tests"}
        offenders = []
        for path in APP.rglob("*.py"):
            package = path.relative_to(APP).parts[0] if path.parent != APP else "app"
            if package in allowed:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "RiskDecision"
                ):
                    offenders.append(str(path.relative_to(APP)))
        assert not offenders, f"RiskDecision constructed outside the risk layer: {offenders}"


class TestSingleExecutionPath:
    """Only the trading pipeline may turn a signal into an order."""

    def test_only_the_pipeline_constructs_orders(self):
        allowed = {"trading", "domain", "brokers"}
        offenders = []
        for path in APP.rglob("*.py"):
            package = path.relative_to(APP).parts[0] if path.parent != APP else "app"
            if package in allowed:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "from_request"
                ):
                    offenders.append(str(path.relative_to(APP)))
        assert not offenders, f"orders constructed outside the pipeline: {offenders}"

    def test_the_pipeline_depends_on_the_risk_engine(self):
        """If the pipeline could execute without risk, the gate is decorative."""
        imports = imports_of(APP / "trading" / "pipeline.py")
        assert any(i.startswith("app.risk") for i in imports)

    def test_brokers_do_not_import_strategies_or_risk(self):
        """A broker executes what it is given; it does not decide."""
        for path in modules_in("brokers"):
            offending = [
                i
                for i in imports_of(path)
                if i.startswith(("app.strategies", "app.risk", "app.trading"))
            ]
            assert not offending, f"{path.name} reaches into decision logic: {offending}"


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
