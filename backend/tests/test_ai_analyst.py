"""The AI Analyst's tool-calling loop, against a mocked Claude client.

No real API calls: the loop's control flow (when to stop, how tool results
feed back, the turn cap) is what these tests verify, not model quality.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.ai.analyst import TOOL_SCHEMAS, AIAnalyst, AnalystUnavailable
from app.core.config import Settings


def settings(**overrides) -> Settings:
    base = dict(
        postgres_user="u", postgres_password="p", postgres_db="d",
        postgres_host="h", postgres_port=5432,
        anthropic_api_key="test-key", ai_analyst_max_tool_turns=4,
    )
    return Settings(**{**base, **overrides})


def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name: str, tool_input: dict, block_id: str = "tool_1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def response(stop_reason: str, content: list):
    return SimpleNamespace(stop_reason=stop_reason, content=content)


@pytest.fixture
def mock_client():
    with patch("anthropic.Anthropic") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


class TestAvailability:
    def test_refuses_to_construct_without_an_api_key(self):
        with pytest.raises(AnalystUnavailable, match="ANTHROPIC_API_KEY"):
            AIAnalyst(session=MagicMock(), settings=settings(anthropic_api_key=None))


class TestDirectAnswer:
    def test_a_question_needing_no_tools_returns_text_immediately(self, mock_client):
        mock_client.messages.create.return_value = response(
            "end_turn", [text_block("The sky is blue.")]
        )
        analyst = AIAnalyst(session=MagicMock(), settings=settings())
        answer = analyst.ask("What colour is the sky?")

        assert answer.text == "The sky is blue."
        assert answer.tools_used == []
        assert mock_client.messages.create.call_count == 1


class TestToolCallingLoop:
    def test_a_single_tool_call_then_a_final_answer(self, mock_client):
        with patch("app.ai.tools.get_portfolio", return_value={"equity": "100000"}):
            mock_client.messages.create.side_effect = [
                response(
                    "tool_use",
                    [tool_use_block("get_portfolio", {}, "t1")],
                ),
                response("end_turn", [text_block("Your equity is 100,000.")]),
            ]
            analyst = AIAnalyst(session=MagicMock(), settings=settings())
            answer = analyst.ask("What is my equity?")

        assert answer.text == "Your equity is 100,000."
        assert answer.tools_used == ["get_portfolio"]
        assert mock_client.messages.create.call_count == 2

    def test_tool_results_are_fed_back_as_a_user_message(self, mock_client):
        with patch(
            "app.ai.tools.get_risk_decisions", return_value={"decisions": []}
        ) as mocked:
            mock_client.messages.create.side_effect = [
                response(
                    "tool_use",
                    [tool_use_block("get_risk_decisions", {"action": "REJECT"}, "t1")],
                ),
                response("end_turn", [text_block("No rejections found.")]),
            ]
            analyst = AIAnalyst(session=MagicMock(), settings=settings())
            analyst.ask("Why was my trade rejected?")

        mocked.assert_called_once()
        _, kwargs = mocked.call_args
        assert kwargs["action"] == "REJECT"

        second_call_messages = mock_client.messages.create.call_args_list[1].kwargs["messages"]
        tool_result_message = second_call_messages[-1]
        assert tool_result_message["role"] == "user"
        assert tool_result_message["content"][0]["type"] == "tool_result"
        assert tool_result_message["content"][0]["tool_use_id"] == "t1"

    def test_multiple_tool_calls_in_one_turn_all_get_results(self, mock_client):
        with (
            patch("app.ai.tools.get_portfolio", return_value={"equity": "100000"}),
            patch("app.ai.tools.get_positions", return_value={"positions": []}),
        ):
            mock_client.messages.create.side_effect = [
                response(
                    "tool_use",
                    [
                        tool_use_block("get_portfolio", {}, "t1"),
                        tool_use_block("get_positions", {}, "t2"),
                    ],
                ),
                response("end_turn", [text_block("Summary.")]),
            ]
            analyst = AIAnalyst(session=MagicMock(), settings=settings())
            answer = analyst.ask("Summarise my account.")

        assert answer.tools_used == ["get_portfolio", "get_positions"]
        second_call_messages = mock_client.messages.create.call_args_list[1].kwargs["messages"]
        tool_results = second_call_messages[-1]["content"]
        assert len(tool_results) == 2
        assert {r["tool_use_id"] for r in tool_results} == {"t1", "t2"}

    def test_stops_after_the_configured_turn_cap(self, mock_client):
        with patch("app.ai.tools.get_portfolio", return_value={"equity": "100000"}):
            # Always asks for another tool call -- never converges.
            mock_client.messages.create.return_value = response(
                "tool_use", [tool_use_block("get_portfolio", {}, "t1")]
            )
            analyst = AIAnalyst(session=MagicMock(), settings=settings(ai_analyst_max_tool_turns=3))
            answer = analyst.ask("Keep going forever.")

        assert mock_client.messages.create.call_count == 3
        assert "wasn't able to finish" in answer.text

    def test_an_unknown_tool_name_raises_rather_than_silently_no_opping(self, mock_client):
        mock_client.messages.create.return_value = response(
            "tool_use", [tool_use_block("delete_everything", {}, "t1")]
        )
        analyst = AIAnalyst(session=MagicMock(), settings=settings())
        with pytest.raises(ValueError, match="unknown tool"):
            analyst.ask("Do something destructive.")


class TestErrorHandling:
    def test_a_client_error_becomes_analyst_unavailable(self, mock_client):
        mock_client.messages.create.side_effect = RuntimeError("connection refused")
        analyst = AIAnalyst(session=MagicMock(), settings=settings())
        with pytest.raises(AnalystUnavailable, match="could not reach the model"):
            analyst.ask("Anything")


class TestToolSchemaIntegrity:
    def test_every_schema_has_a_valid_json_schema_input(self):
        for schema in TOOL_SCHEMAS:
            assert schema["input_schema"]["type"] == "object"
            assert "description" in schema
            assert len(schema["description"]) > 10

    def test_schema_names_are_unique(self):
        names = [s["name"] for s in TOOL_SCHEMAS]
        assert len(names) == len(set(names))
