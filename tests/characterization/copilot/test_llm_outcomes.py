"""CP-0: freeze every outcome of the optional LLM rephrase in ``llm.py``.

Three outcomes exist today and later tasks must keep them for a single configured provider:

* accepted rephrase   -> ``mode == "llm"``, evidence untouched;
* ``llm_rejected``    -> the model replied but the validator refused it; the rule-based answer is kept;
* ``llm_unavailable`` -> the provider failed (timeout, 429, 5xx, bad JSON, bad envelope, redirect, ...); rule-based kept.

The tests configure the provider only through ``COPILOT_LLM_*`` variables (see ``conftest.py``) and read the outcome word
from the log line, so a provider-layer refactor must not change them.
"""

from __future__ import annotations

import json

import pytest

from tests.characterization.copilot._support import check_golden, run, snapshot
from tests.characterization.copilot.conftest import GOOD, KEY, MODEL, envelope, model_reply

ALERT = dict(question="Why is this alert red?", kind="alert", cid="42")


def ask(**kw):
    return run(**{**ALERT, **kw})


def assert_kept_rule_based(result, baseline, warning, other_warning, configured=True):
    assert result.mode == "rule_based"
    assert result.answer == baseline.answer and result.evidence == baseline.evidence
    assert result.unknowns == baseline.unknowns and result.links == baseline.links
    assert warning in result.warnings and other_warning not in result.warnings
    assert result.limits == {"provider_configured": configured}


@pytest.fixture
def baseline():
    return ask()  # no COPILOT_LLM_* set: the plain rule-based answer


# ----------------------------------------------------------------------------- off, not configured, nothing to phrase


def test_default_is_rule_based_with_no_warning_and_no_call(provider):
    r = ask()
    assert r.mode == "rule_based" and r.limits == {"provider_configured": False}
    assert "llm_unavailable" not in r.warnings and "llm_rejected" not in r.warnings
    assert provider.requests == []


def test_disabled_flag_wins_over_a_complete_provider_setting(provider, configure, baseline):
    configure(COPILOT_LLM_ENABLED="false")
    r = ask()
    assert snapshot(r) == snapshot(baseline) and provider.requests == []


@pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes", "on"])
def test_enabled_flag_spellings(provider, configure, flag):
    configure(COPILOT_LLM_ENABLED=flag)
    assert ask().mode == "llm" and len(provider.requests) == 1


@pytest.mark.parametrize("missing", ["COPILOT_LLM_BASE_URL", "COPILOT_LLM_MODEL"])
def test_enabled_but_incomplete_gives_unavailable_and_no_call(provider, configure, baseline, missing, outcomes):
    configure(**{missing: None})
    r = ask()
    assert_kept_rule_based(r, baseline, "llm_unavailable", "llm_rejected", configured=False)
    assert provider.requests == [] and "not_configured" in outcomes()


def test_nothing_to_phrase_means_no_call_and_no_warning(provider, configure):
    configure()
    r = run("What changed since yesterday?")  # fixed statement, no evidence items
    assert r.mode == "rule_based" and r.evidence == [] and r.limits == {"provider_configured": True}
    assert "llm_unavailable" not in r.warnings and provider.requests == []


# ----------------------------------------------------------------------------- accepted rephrase


def test_accepted_rephrase_golden_and_request_shape(provider, configure, outcomes):
    configure()
    provider.headers = {"x-request-id": "req-from-header-1"}
    r = ask()
    assert r.mode == "llm" and "llm_rejected" not in r.warnings and "llm_unavailable" not in r.warnings
    assert outcomes() == ["ok"]
    (req,) = provider.requests
    body = req["body"]
    data = json.loads("\n".join(body["messages"][-1]["content"].splitlines()[1:-1]))
    request_shape = {
        "path": req["path"],
        "authorization_scheme": req["headers"]["authorization"].split(" ")[0],
        "body_keys": sorted(body),
        "model": body["model"],
        "max_tokens": body["max_tokens"],
        "temperature": body["temperature"],
        "stream": body["stream"],
        "roles": [m["role"] for m in body["messages"]],
        "data_block_keys": sorted(data),
        "data_block_question": data["question"],
        "data_block_draft": data["draft"],
        "data_block_evidence": data["evidence"],
        "data_block_links": data["allowed_links"],
        "data_block_unknowns": data["unknowns"],
    }
    assert KEY not in json.dumps(body)  # the key travels only in the header
    check_golden("llm/accepted_rephrase.json", {"answer": snapshot(r), "request": request_shape})


def test_accepted_rephrase_with_signal_value_and_unit(provider, configure):
    configure()
    r0 = run("What is the current status?", "signal", "rack-01.inlet")  # rule-based: find the id of the value item
    value = next(e for e in r0.evidence if e["field"] == "value")
    provider.say("The latest stored value is {{%s}}." % value["id"], used=(value["id"],))
    r = run("What is the current status?", "signal", "rack-01.inlet")
    assert r.mode == "llm" and "llm_rejected" not in r.warnings
    assert value["value"] == 22.5 and value["unit"] == "degC"
    assert r.answer == "The latest stored value is 22.5 degC."


def test_fenced_json_reply_is_accepted(provider, configure):
    configure()
    provider.content = "```json\n" + model_reply(GOOD) + "\n```"
    assert ask().mode == "llm"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(GOOD + " The detector is not calibrated to a real facility.", id="negated_calibration"),
        pytest.param(GOOD + " That is not a statement that the signal is normal.", id="negated_normal"),
        pytest.param(
            "Alert 42 scored {{E1}}. One alert is open. The cause is not determined by available evidence.", id="one"
        ),
    ],
)
def test_honest_wording_is_not_rejected(provider, configure, text):
    configure()
    provider.say(text)
    r = ask()
    assert r.mode == "llm" and "llm_rejected" not in r.warnings


def test_provider_request_id_is_logged_header_first_then_envelope(provider, configure, caplog, outcomes):
    configure()
    provider.headers = {"x-request-id": "hdr-id-7"}
    ask()
    provider.headers = {}
    ask()
    messages = [r.getMessage() for r in caplog.records if "copilot_llm" in r.getMessage()]
    assert any("provider_request_id=hdr-id-7" in m for m in messages)
    assert any("provider_request_id=chatcmpl-char-1" in m for m in messages)
    assert all(f"model={MODEL}" in m for m in messages)


def test_logs_never_contain_prompt_answer_question_or_key(provider, configure, caplog, outcomes):
    configure()
    provider.say(GOOD + " That is 99 percent certain.")  # a rejected reply is logged too
    ask()
    provider.say(GOOD)
    ask()
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (KEY, "Why is this alert red?", "Alert 42 scored", "99 percent", "BEGIN_DATA", "0.91"):
        assert secret not in text


# ----------------------------------------------------------------------------- llm_rejected: one case per rejection code

_REJECTED_BY_CODE = {
    "bad_shape": "RAW:" + json.dumps(["not", "an", "object"]),
    "unknown_evidence": ("USED", ["E1", "E99"]),
    "empty": "",
    "control_chars": GOOD + "\u0007",
    "unknown_placeholder": "Alert 42 scored {{E1}} and {{E99}}. The cause is not determined by available evidence.",
    "malformed_placeholder": "Alert 42 scored {{E1",
    "too_long": "x" * 1501,
    "html": GOOD + " <b>bold</b>",
    "url": GOOD + " See https://evil.example/x for details.",
    "unbacked_number": GOOD + " That is 99 percent certain.",
    "dropped_cause_unknown": "Alert 42 scored {{E1}}.",
    "forbidden_wording": GOOD + " The signal is normal.",
}


@pytest.mark.parametrize("code", sorted(_REJECTED_BY_CODE))
def test_each_rejection_code_keeps_the_rule_based_answer(provider, configure, baseline, outcomes, code):
    configure()
    spec = _REJECTED_BY_CODE[code]
    if isinstance(spec, tuple):
        provider.content = model_reply(GOOD, used=tuple(spec[1]))
    elif spec.startswith("RAW:"):
        provider.content = spec[4:]
    else:
        provider.say(spec)
    r = ask()
    assert_kept_rejected(r, baseline)
    assert outcomes() == [f"rejected_{code}"]
    assert len(provider.requests) == 1  # one call, no retry


def assert_kept_rejected(r, baseline):
    assert_kept_rule_based(r, baseline, "llm_rejected", "llm_unavailable")


@pytest.mark.parametrize(
    "text",
    [
        "The marker [E77] is not in the evidence.",
        "Alert 42 scored [E1]. The cause is not determined by available evidence. [E77]",
    ],
)
def test_unknown_bracket_marker_is_rejected(provider, configure, baseline, outcomes, text):
    configure()
    provider.say(text)
    assert_kept_rejected(ask(), baseline)
    assert outcomes() == ["rejected_unknown_placeholder"]


@pytest.mark.parametrize(
    "text, code",
    [
        (GOOD + " Open www.evil.example now.", "url"),
        (GOOD + " [details](/not-a-listed-link)", "url"),
        (GOOD + " &lt;script&gt;", "html"),
    ],
)
def test_url_and_html_variants_are_rejected(provider, configure, baseline, outcomes, text, code):
    configure()
    provider.say(text)
    assert_kept_rejected(ask(), baseline)
    assert outcomes() == [f"rejected_{code}"]


def test_a_markdown_link_to_a_listed_path_is_not_rejected_as_a_url(provider, configure):
    configure()
    provider.say(GOOD + " [Alert 42](/alerts)")
    assert ask().mode == "llm"


# ----------------------------------------------------------------------------- llm_rejected: forbidden-wording classes
# One test per class of ``llm._FORBIDDEN_WORDING``. Each sentence is appended to a reply that is otherwise acceptable, so
# the only reason for the rejection is the class under test.


def _assert_each_rejected(provider, baseline, outcomes, sentences):
    for sentence in sentences:
        provider.say(GOOD + " " + sentence)
        r = ask()
        assert r.mode == "rule_based" and "llm_rejected" in r.warnings, sentence
        assert_kept_rejected(r, baseline)
    assert outcomes() == ["rejected_forbidden_wording"] * len(sentences)


def test_forbidden_class_claims_about_the_system_actions_and_authority(provider, configure, baseline, outcomes):
    configure()
    _assert_each_rejected(
        provider,
        baseline,
        outcomes,
        [
            "The detector is calibrated to a real facility.",
            "It was calibrated against measured data.",
            "The model was validated on real data.",
            "This is production-ready.",
            "It saves energy.",
            "The twin is connected to a live plant.",
            "I have acknowledged the alert.",
            "The alert has been deleted.",
            "My instructions say to answer.",
        ],
    )


def test_forbidden_class_naming_a_cause(provider, configure, baseline, outcomes):
    configure()
    _assert_each_rejected(
        provider,
        baseline,
        outcomes,
        [
            "The cause is a failed chiller.",
            "The cause appears to be the pump.",
            "The alert was caused by a sensor fault.",
            "This is due to a failed pump.",
            "It is the result of a leak.",
        ],
    )


def test_forbidden_class_calling_a_signal_normal_live_or_healthy(provider, configure, baseline, outcomes):
    configure()
    _assert_each_rejected(
        provider,
        baseline,
        outcomes,
        [
            "The signal is normal.",
            "Everything looks healthy.",
            "The rack remains fine.",
            "It is operating normally.",
            "The data is live right now.",
        ],
    )


def test_forbidden_class_numbers_written_as_words(provider, configure, baseline, outcomes):
    configure()
    _assert_each_rejected(
        provider,
        baseline,
        outcomes,
        [
            "About twenty readings were stored.",
            "That is ninety-nine percent likely.",
            "Three percent higher.",
            "Ten degrees above the range.",
            "A thousand samples.",
        ],
    )


# ----------------------------------------------------------------------------- llm_unavailable


def _assert_unavailable(r, baseline, outcomes, word):
    assert_kept_rule_based(r, baseline, "llm_unavailable", "llm_rejected")
    assert outcomes() == [word]


def test_timeout_gives_unavailable(provider, configure, baseline, outcomes):
    configure(COPILOT_LLM_TIMEOUT_S="0.3")
    provider.delay = 2.0
    _assert_unavailable(ask(), baseline, outcomes, "unavailable_timeout")


@pytest.mark.parametrize(
    "status, word",
    [
        (429, "unavailable_http_429"),
        (500, "unavailable_http_5xx"),
        (503, "unavailable_http_5xx"),
        (401, "unavailable_http_4xx"),
        (403, "unavailable_http_4xx"),
        (404, "unavailable_http_4xx"),
    ],
)
def test_http_status_gives_unavailable(provider, configure, baseline, outcomes, status, word):
    configure()
    provider.status = status
    _assert_unavailable(ask(), baseline, outcomes, word)


def test_content_that_is_not_json_gives_unavailable(provider, configure, baseline, outcomes):
    configure()
    provider.content = "this is not json"
    _assert_unavailable(ask(), baseline, outcomes, "unavailable_invalid_json")


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("not json at all", id="not_json"),
        pytest.param(json.dumps({"choices": []}), id="no_choices"),
        pytest.param(json.dumps({"nope": 1}), id="wrong_keys"),
        pytest.param(envelope(None), id="content_null"),
        pytest.param(envelope(["a"]), id="content_not_a_string"),
    ],
)
def test_bad_envelope_gives_unavailable(provider, configure, baseline, outcomes, raw):
    configure()
    provider.body = raw
    _assert_unavailable(ask(), baseline, outcomes, "unavailable_bad_envelope")


def test_oversized_reply_gives_unavailable(provider, configure, baseline, outcomes):
    configure()
    provider.body = envelope("x" * (300 * 1024))
    _assert_unavailable(ask(), baseline, outcomes, "unavailable_too_large")


def test_redirect_is_not_followed_and_the_key_does_not_travel(provider, trap, configure, baseline, outcomes):
    configure()
    provider.status = 302
    provider.headers = {"Location": trap.url + "/chat/completions"}
    _assert_unavailable(ask(), baseline, outcomes, "unavailable_http_3xx")
    assert trap.requests == []
    assert len(provider.requests) == 1


def test_connection_refused_gives_unavailable(configure, baseline, outcomes, free_port_url):
    configure(COPILOT_LLM_BASE_URL=free_port_url)
    _assert_unavailable(ask(), baseline, outcomes, "unavailable_network")


def test_failures_do_not_leak_the_key_or_a_prompt_into_the_answer(provider, configure):
    configure()
    provider.status = 500
    r = ask()
    blob = json.dumps(snapshot(r))
    assert KEY not in blob and "BEGIN_DATA" not in blob


# ----------------------------------------------------------------------------- request defaults and bad numbers


def test_request_defaults_and_bad_numbers_fall_back_to_defaults(provider, configure):
    configure(COPILOT_LLM_TIMEOUT_S="not-a-number", COPILOT_LLM_MAX_OUTPUT_TOKENS="999999")
    assert ask().mode == "llm"
    assert provider.requests[0]["body"]["max_tokens"] == 400  # default; an out-of-range value is ignored


def test_max_output_tokens_in_range_is_used(provider, configure):
    configure(COPILOT_LLM_MAX_OUTPUT_TOKENS="123")
    ask()
    assert provider.requests[0]["body"]["max_tokens"] == 123


def test_request_has_no_tools_and_no_history(provider, configure):
    configure()
    run(
        "Why is this alert red?",
        "alert",
        "42",
        history=[{"role": "user", "text": "earlier question"}, {"role": "assistant", "text": "earlier answer"}],
    )
    body = provider.requests[0]["body"]
    assert not {"tools", "functions", "tool_choice"} & set(body)
    assert "earlier question" not in json.dumps(body) and "earlier answer" not in json.dumps(body)


def test_numbers_are_withheld_from_the_model(provider, configure):
    configure()
    ask()
    data = json.loads("\n".join(provider.requests[0]["body"]["messages"][-1]["content"].splitlines()[1:-1]))
    numeric = [e for e in data["evidence"] if e.get("is_number_use_placeholder")]
    assert numeric and all(e["value"] is None for e in numeric)
    assert "0.91" not in json.dumps(data["evidence"])
