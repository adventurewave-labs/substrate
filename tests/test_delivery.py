"""Delivery rendering + sink contract — fake transport, never the network."""

import pytest

from substrate.signals.delivery import PendingEvent, SlackWebhookSink, render_slack_message


def _event(event_type="job_change"):
    return PendingEvent(
        event_id="evt-1",
        event_type=event_type,
        person_name="Ada Lovelace",
        old_state={"org_name": "Acme", "title": "VP Engineering", "position_id": "pos1"},
        new_state={"org_name": "Beta", "title": "CTO", "position_id": "pos2"},
        detected_at="2026-11-16 09:00 UTC",
    )


class RecordingSink:
    def __init__(self, status: int = 200):
        self.status = status
        self.payloads: list[dict] = []

    def deliver(self, payload: dict) -> bool:
        self.payloads.append(payload)
        return 200 <= self.status < 300


def test_render_job_change_uses_stored_states_only():
    payload = render_slack_message(_event())
    text = payload["text"]
    assert "Ada Lovelace" in text
    assert "Acme" in text and "Beta" in text
    assert "VP Engineering" in text and "CTO" in text
    assert "2026-11-16" in text
    assert "👍/👎" in text  # the verdict mechanism is part of the product


def test_render_promotion_variant():
    payload = render_slack_message(_event("promotion"))
    assert "promoted" in payload["text"]


def test_unconfigured_sink_reports_not_configured():
    sink = SlackWebhookSink(webhook_url="")
    assert sink.configured is False
    assert sink.deliver({"text": "x"}) is False


def test_sink_delivers_payload_via_transport():
    sent: list[bytes] = []

    def transport(request):
        sent.append(request.data)
        return 200, b"ok"

    sink = SlackWebhookSink(webhook_url="https://hooks.example/t", transport=transport)
    assert sink.deliver({"text": "hello"}) is True
    assert b"hello" in sent[0]


def test_sink_failure_returns_false_not_raise():
    def transport(request):
        return 500, b""

    sink = SlackWebhookSink(webhook_url="https://hooks.example/t", transport=transport)
    assert sink.deliver({"text": "x"}) is False


def test_sink_propagates_exceptions_to_the_dispatcher():
    # The SINK raises (dispatcher catches); the dispatcher records type-only so a
    # webhook URL in an error message can never reach the report file. The
    # type-only assertion lives in the live dispatcher test (at-least-once path).

    def transport(request):
        raise RuntimeError("POST https://hooks.example/secret-token failed")

    sink = SlackWebhookSink(webhook_url="https://hooks.example/secret-token", transport=transport)
    with pytest.raises(RuntimeError, match="secret-token"):
        sink.deliver({"text": "x"})


def test_untrusted_text_is_mrkdwn_escaped():
    # Gate round-6: hostile or merely quirky CRM text must not ping <!channel>
    # or disguise links/bold in Slack. Everything from the event states escapes.
    import urllib.request  # noqa: F401 — documents the untrusted-input context

    event = PendingEvent(
        event_id="evt-2",
        event_type="job_change",
        person_name="<!channel> Eve *Admin*",
        old_state={"org_name": "Acme & Co <rivals>", "title": "CEO ~boss~"},
        new_state={"org_name": "Beta https://evil.example", "title": "CTO `rm -rf`"},
        detected_at="2026-11-16 09:00 UTC",
    )
    payload = render_slack_message(event)
    text = payload["text"]
    assert "<!channel>" not in text
    assert "&lt;!channel&gt;" in text
    assert "&amp;" in text
    assert "<rivals>" not in text and "&lt;rivals&gt;" in text
    assert "https://evil.example" in text  # bare URL: inert, auto-linked by Slack
    # The threat is mrkdwn link syntax <url|text> — dead after escaping.
    assert "<https://evil.example|" not in text
    assert "|click" not in text


def test_formatting_characters_render_literally():
    # Gate round-10: Slack mrkdwn has no backslash escapes — formatting chars
    # must NOT grow visible backslashes; mrkdwn control (& < >) still escapes.
    event = PendingEvent(
        event_id="evt-3",
        event_type="job_change",
        person_name="Grace *Hopper_",
        old_state={"org_name": "Acme & Co", "title": "R&D ~lead~"},
        new_state={"org_name": "Beta <division>", "title": "CTO"},
        detected_at="2026-11-16 09:00 UTC",
    )
    payload = render_slack_message(event)
    text = payload["text"]
    assert "\\*" not in text and "\\_" not in text and "\\`" not in text and "\\~" not in text
    assert "*Hopper*" in text or "*Hopper_" in text  # chars kept, unescaped
    assert "&amp;" in text  # control char escaped
