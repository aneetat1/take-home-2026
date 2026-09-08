import asyncio
import logging
from types import SimpleNamespace

import ai


def make_response(
    *,
    model: str = "openai/gpt-5-mini",
    input_tokens: int = 1_000,
    output_tokens: int = 500,
    reasoning_tokens: int = 300,
):
    return SimpleNamespace(
        model=model,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            output_tokens_details=SimpleNamespace(
                reasoning_tokens=reasoning_tokens
            ),
        ),
    )


def test_reasoning_tokens_are_not_charged_twice() -> None:
    record = ai._log_usage(make_response())

    assert record is not None
    assert record.reasoning_tokens == 300
    assert record.estimated_cost == (1_000 * 0.25 + 500 * 2.00) / 1_000_000


def test_unknown_model_reports_unknown_cost(caplog) -> None:
    with caplog.at_level(logging.INFO):
        record = ai._log_usage(make_response(model="provider/unknown-model"))

    assert record is not None
    assert record.input_tokens == 1_000
    assert record.output_tokens == 500
    assert record.estimated_cost is None
    assert "Cost: unknown" in caplog.text


def test_summarizes_calls_and_models() -> None:
    records = [
        ai.UsageRecord("model-a", 100, 50, 20, 0.01),
        ai.UsageRecord("model-a", 200, 80, 30, 0.02),
        ai.UsageRecord("model-b", 300, 90, 40, 0.03),
    ]

    summary = ai.summarize_usage(records)

    assert summary.calls == 3
    assert summary.input_tokens == 600
    assert summary.output_tokens == 220
    assert summary.reasoning_tokens == 90
    assert summary.estimated_cost == 0.06
    assert summary.by_model["model-a"].calls == 2
    assert summary.by_model["model-a"].estimated_cost == 0.03
    assert summary.by_model["model-b"].input_tokens == 300


def test_summary_is_unknown_when_any_call_has_unknown_price() -> None:
    summary = ai.summarize_usage(
        [
            ai.UsageRecord("known", 100, 50, 0, 0.01),
            ai.UsageRecord("unknown", 100, 50, 0, None),
        ]
    )

    assert summary.estimated_cost is None
    assert summary.by_model["known"].estimated_cost == 0.01
    assert summary.by_model["unknown"].estimated_cost is None


def test_usage_capture_is_isolated_between_async_tasks() -> None:
    async def collect(model: str) -> ai.UsageSummary:
        with ai.capture_usage() as capture:
            await asyncio.sleep(0)
            ai._log_usage(make_response(model=model))
        return capture.summary

    async def run_tasks():
        return await asyncio.gather(collect("model-a"), collect("model-b"))

    first, second = asyncio.run(run_tasks())

    assert list(first.by_model) == ["model-a"]
    assert list(second.by_model) == ["model-b"]


def test_missing_usage_is_not_recorded() -> None:
    with ai.capture_usage() as capture:
        record = ai._log_usage(SimpleNamespace(model="model-a", usage=None))

    assert record is None
    assert capture.records == []
