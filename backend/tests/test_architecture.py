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


class TestMLIsolation:
    """The adverse-outcome model assists the risk score; it cannot trade.

    Structurally identical guarantee to strategy isolation: if app.ml could
    reach a broker or construct an Order, "the model assists but never
    executes" would be a comment, not a fact a test can fail on.
    """

    FORBIDDEN = ("app.brokers", "app.trading", "app.api", "binance")

    @pytest.mark.parametrize("path", modules_in("ml"), ids=lambda p: p.name)
    def test_ml_cannot_reach_execution(self, path):
        offending = [
            imp
            for imp in imports_of(path)
            for bad in self.FORBIDDEN
            if imp == bad or imp.startswith(bad + ".")
        ]
        assert not offending, f"{path.name} imports execution machinery: {offending}"

    @pytest.mark.parametrize("path", modules_in("ml"), ids=lambda p: p.name)
    def test_ml_does_not_construct_orders_or_decisions(self, path):
        """It contributes one score to the engine; it authorises nothing."""
        names = {
            n.id for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Name)
        }
        assert not names & {"Order", "OrderRequest", "RiskDecision"}, (
            f"{path.name} references order or decision types"
        )

    def test_the_ml_check_is_never_in_the_default_checks_tuple(self):
        """Absence by default: the model only ever appends, and only when a
        caller explicitly loads one and passes it to RiskEngine.
        """
        from app.risk.checks import DEFAULT_CHECKS
        from app.risk.engine import MLAdverseOutcomeCheck

        assert not any(isinstance(c, MLAdverseOutcomeCheck) for c in DEFAULT_CHECKS)

    def test_a_fresh_engine_with_no_model_behaves_identically_to_one_with_none_explicit(self):
        from app.risk import RiskEngine

        implicit = RiskEngine()
        explicit = RiskEngine(ml_model=None)
        assert implicit.checks == explicit.checks


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

    def test_no_layer_mints_its_own_risk_decision(self):
        """A RiskDecision authored outside the risk engine is a rubber stamp.

        The persistence layer is exempt: reading a stored decision back is
        rehydration, not authorship, and the round trip has to reconstruct the
        object somewhere. Every layer that could otherwise fabricate an
        authorisation for itself is covered.
        """
        banned = {"trading", "brokers", "api", "services", "strategies", "portfolio", "backtest"}
        offenders = []
        for path in APP.rglob("*.py"):
            package = path.relative_to(APP).parts[0] if path.parent != APP else "app"
            if package not in banned:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "RiskDecision"
                ):
                    offenders.append(str(path.relative_to(APP)))
        assert not offenders, f"RiskDecision constructed outside the risk layer: {offenders}"

    def test_the_repository_only_rehydrates_persisted_decisions(self):
        """The one exemption is narrow: a classmethod that reads a stored row."""
        source = (APP / "db" / "repositories.py").read_text()
        tree = ast.parse(source)

        constructing_functions = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == "RiskDecision"
                    ):
                        constructing_functions.add(node.name)

        assert constructing_functions == {"to_domain"}, (
            "RiskDecision may only be reconstructed in the repository's "
            f"to_domain rehydrator, not in {sorted(constructing_functions)}"
        )


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
