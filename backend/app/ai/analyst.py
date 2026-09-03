"""The AI Analyst: a read-only assistant over the platform's own records.

Runs a manual tool-calling loop against Claude rather than the beta Tool
Runner, so the tool registry is an explicit, inspectable list this module
owns end to end -- the same list an architecture test checks contains no
write operation.

The analyst assists understanding; it does not act. There is no tool here
that places an order, changes a limit, or touches the risk engine, so it
cannot bypass the risk engine even if asked to -- there is nothing in its
tool registry that could.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.ai import tools as analyst_tools
from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT = """You are the AI Analyst for Strategic Trade Analyzer, a \
simulated trading and risk-analysis platform. You answer questions about \
this account's own portfolio, trades, risk decisions and strategy \
performance, using only the tools provided.

Rules:
- Answer only from tool results. Never invent a number, a trade, or a reason.
- You have no tool that places, cancels, or modifies a trade, and no tool \
that changes a risk limit. If asked to do any of these, say plainly that \
you can only analyse and explain -- you cannot act.
- When explaining a rejected trade, quote the actual reasons from the \
risk decision's checks, not a general explanation of risk management.
- Be concise. Lead with the direct answer, then the supporting numbers.
- All trading here is simulated (paper or exchange testnet). Never imply \
real money is at risk.
"""

#: The read-only tool registry. An architecture test asserts every entry's
#: name appears in app.ai.tools' __all__ (never app.trading, app.brokers, or
#: anything that constructs an Order or RiskDecision), and that this list
#: never grows a tool whose name suggests a write.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_portfolio",
        "description": (
            "Current balances, positions, exposure and P&L. Use for "
            "questions about overall account state, e.g. 'why did my "
            "portfolio lose money today?'"
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_positions",
        "description": (
            "Open positions ranked by notional exposure, with unrealised P&L. "
            "Use for 'what are my riskiest positions?'"
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_risk_decisions",
        "description": (
            "Recent risk decisions with the full per-check breakdown: what "
            "was observed, what the limit was, and why. Use for 'why was my "
            "BTC trade rejected?' (pass action='REJECT')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "e.g. BTCUSDT, optional"},
                "action": {
                    "type": "string",
                    "enum": ["APPROVE", "REDUCE", "REJECT"],
                    "description": "filter to one verdict, optional",
                },
                "limit": {"type": "integer", "default": 10},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_strategy_performance",
        "description": (
            "Every registered strategy's signal counts and attributed "
            "realised P&L, sorted best first. Use for 'which strategy "
            "performed best?'"
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_trades",
        "description": "Recent orders and how many fills each has.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "optional"},
                "limit": {"type": "integer", "default": 20},
            },
            "additionalProperties": False,
        },
    },
]


class AnalystUnavailable(RuntimeError):
    """No API key configured, or the model could not be reached."""


@dataclass
class AnalystAnswer:
    text: str
    tools_used: list[str] = field(default_factory=list)


class AIAnalyst:
    """Wraps the Claude client and the tool-calling loop for one question."""

    def __init__(self, session: Session, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise AnalystUnavailable(
                "ANTHROPIC_API_KEY is not set; the AI Analyst is disabled"
            )
        self.session = session
        self.settings = settings

        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def ask(self, question: str) -> AnalystAnswer:
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        tools_used: list[str] = []

        for _ in range(self.settings.ai_analyst_max_tool_turns):
            try:
                response = self._client.messages.create(
                    model=self.settings.ai_analyst_model,
                    max_tokens=1500,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_SCHEMAS,
                    messages=messages,
                )
            except Exception as exc:  # noqa: BLE001 - normalised for the caller
                log.warning("ai_analyst.request_failed", error=str(exc))
                raise AnalystUnavailable(f"could not reach the model: {exc}") from exc

            if response.stop_reason != "tool_use":
                text = "".join(
                    block.text for block in response.content if block.type == "text"
                )
                return AnalystAnswer(text=text or "(no answer produced)", tools_used=tools_used)

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tools_used.append(block.name)
                result = self._run_tool(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        log.warning("ai_analyst.max_turns_reached", question=question)
        return AnalystAnswer(
            text="I wasn't able to finish researching this within the allotted "
            "number of tool calls. Try asking a narrower question.",
            tools_used=tools_used,
        )

    def _run_tool(self, name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Dispatch to the read-only tool implementation.

        Every branch here is one of app.ai.tools' exported functions -- there
        is no default/fallback case that could be pointed at something else.
        """
        if name == "get_portfolio":
            return analyst_tools.get_portfolio(self.session, self.settings)
        if name == "get_positions":
            return analyst_tools.get_positions(self.session, self.settings)
        if name == "get_risk_decisions":
            return analyst_tools.get_risk_decisions(
                self.session,
                symbol=tool_input.get("symbol"),
                action=tool_input.get("action"),
                limit=tool_input.get("limit", 10),
            )
        if name == "get_strategy_performance":
            return analyst_tools.get_strategy_performance(self.session)
        if name == "get_trades":
            return analyst_tools.get_trades(
                self.session,
                symbol=tool_input.get("symbol"),
                limit=tool_input.get("limit", 20),
            )
        raise ValueError(f"unknown tool {name!r}")
