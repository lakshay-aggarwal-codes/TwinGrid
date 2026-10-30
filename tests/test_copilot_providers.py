"""CP-1: provider configuration. No network, no FastAPI. The Task 24 tests (test_copilot_llm.py) stay unchanged."""

from __future__ import annotations

from src.copilot import llm, providers
from src.copilot.providers import ProviderConfig, active_providers, load_providers

ON = {"COPILOT_LLM_ENABLED": "true"}


def test_the_files_cp1_assumes_exist():
    # Repo drift guard: fail loudly if the Task 24 seams CP-1 builds on are missing.
    for name in ("LlmSettings", "load_settings", "_call_provider", "enhance", "validate", "SYSTEM_POLICY"):
        assert hasattr(llm, name), f"src/copilot/llm.py lost {name}"


def test_off_means_no_providers_even_with_a_list():
    assert load_providers({}) == []
    assert load_providers({"COPILOT_LLM_ENABLED": "false", "COPILOT_LLM_PROVIDERS": "a,b"}) == []
    assert load_providers({"COPILOT_LLM_ENABLED": "maybe"}) == []


def test_legacy_variables_map_to_one_provider_named_default():
    env = {**ON, "COPILOT_LLM_BASE_URL": "http://x/v1/", "COPILOT_LLM_MODEL": "m", "COPILOT_LLM_API_KEY": "k1"}
    (p,) = load_providers(env)
    assert p.name == "default" and p.base_url == "http://x/v1" and p.model == "m" and p.api_key == "k1"
    assert p.enabled and p.configured and not p.local and p.data_policy == "cloud"
    assert p.key_secret == "COPILOT_LLM_API_KEY"
    assert "k1" not in repr(p)


def test_legacy_enabled_but_missing_url_is_one_unconfigured_provider():
    (p,) = load_providers(ON)
    assert p.name == "default" and not p.configured
    assert active_providers([p]) == []


def test_ordered_providers_with_per_provider_variables():
    env = {
        **ON,
        "COPILOT_LLM_PROVIDERS": " Ollama, groq ,open-router",
        "COPILOT_LLM_OLLAMA_BASE_URL": "http://localhost:11434/v1",
        "COPILOT_LLM_OLLAMA_MODEL": "llama3.2",
        "COPILOT_LLM_OLLAMA_LOCAL": "true",
        "COPILOT_LLM_OLLAMA_TIMEOUT_S": "30",
        "COPILOT_LLM_GROQ_BASE_URL": "https://api.groq.example/v1",
        "COPILOT_LLM_GROQ_MODEL": "g-1",
        "COPILOT_LLM_GROQ_API_KEY": "gk",
        "COPILOT_LLM_OPEN_ROUTER_BASE_URL": "https://or.example/v1",
        "COPILOT_LLM_OPEN_ROUTER_MODEL": "o-1:free",
    }
    ps = load_providers(env)
    assert [p.name for p in ps] == ["ollama", "groq", "open-router"]
    ollama, groq, orr = ps
    assert ollama.local and ollama.data_policy == "local" and ollama.timeout_s == 30.0 and ollama.api_key is None
    assert not groq.local and groq.data_policy == "cloud" and groq.api_key == "gk" and groq.timeout_s == 10.0
    assert groq.key_secret == "COPILOT_LLM_GROQ_API_KEY"
    assert orr.key_secret == "COPILOT_LLM_OPEN_ROUTER_API_KEY" and orr.model == "o-1:free"


def test_one_providers_key_is_never_used_for_another():
    env = {
        **ON,
        "COPILOT_LLM_PROVIDERS": "a,b",
        "COPILOT_LLM_API_KEY": "legacy",
        "COPILOT_LLM_A_API_KEY": "ka",
        "COPILOT_LLM_A_BASE_URL": "http://a/v1",
        "COPILOT_LLM_A_MODEL": "m",
        "COPILOT_LLM_B_BASE_URL": "http://b/v1",
        "COPILOT_LLM_B_MODEL": "m",
    }
    a, b = load_providers(env)
    assert a.api_key == "ka" and b.api_key is None


def test_global_timeout_and_tokens_are_the_fallback_per_provider_values_win():
    env = {
        **ON,
        "COPILOT_LLM_PROVIDERS": "a,b",
        "COPILOT_LLM_TIMEOUT_S": "7",
        "COPILOT_LLM_MAX_OUTPUT_TOKENS": "123",
        "COPILOT_LLM_B_TIMEOUT_S": "20",
        "COPILOT_LLM_B_MAX_OUTPUT_TOKENS": "999",
    }
    a, b = load_providers(env)
    assert (a.timeout_s, a.max_output_tokens) == (7.0, 123)
    assert (b.timeout_s, b.max_output_tokens) == (20.0, 999)


def test_bad_values_fall_back_to_defaults_and_never_raise():
    env = {
        **ON,
        "COPILOT_LLM_PROVIDERS": "a",
        "COPILOT_LLM_TIMEOUT_S": "banana",
        "COPILOT_LLM_MAX_OUTPUT_TOKENS": "999999",
        "COPILOT_LLM_A_TIMEOUT_S": "-5",
        "COPILOT_LLM_A_MAX_OUTPUT_TOKENS": "nan",
        "COPILOT_LLM_A_ENABLED": "perhaps",
        "COPILOT_LLM_A_LOCAL": "??",
    }
    (a,) = load_providers(env)
    assert a.timeout_s == 10.0 and a.max_output_tokens == 400 and a.enabled and not a.local


def test_bad_names_are_dropped_duplicates_collapsed_and_the_list_is_capped():
    assert providers.parse_names("a, A, b,, bad name,../x,-lead,ok_1") == ["a", "b", "ok_1"]
    assert providers.parse_names("") == [] and providers.parse_names(None) == []
    many = ",".join(f"p{i}" for i in range(20))
    assert len(providers.parse_names(many)) == providers.MAX_PROVIDERS


def test_list_with_only_bad_names_gives_no_providers_not_a_crash():
    assert load_providers({**ON, "COPILOT_LLM_PROVIDERS": "bad name,../x"}) == []


def test_disabled_providers_are_listed_but_skipped():
    env = {
        **ON,
        "COPILOT_LLM_PROVIDERS": "a,b,c",
        "COPILOT_LLM_A_BASE_URL": "http://a/v1",
        "COPILOT_LLM_A_MODEL": "m",
        "COPILOT_LLM_A_ENABLED": "false",
        "COPILOT_LLM_B_BASE_URL": "http://b/v1",
        "COPILOT_LLM_B_MODEL": "m",
        "COPILOT_LLM_C_BASE_URL": "http://c/v1",  # no model: half configured
    }
    ps = load_providers(env)
    assert [p.name for p in ps] == ["a", "b", "c"] and not ps[0].enabled
    assert [p.name for p in active_providers(ps)] == ["b"]


def test_data_policy_follows_the_local_flag_and_cannot_be_forged():
    base = {**ON, "COPILOT_LLM_PROVIDERS": "x"}
    cloud_claims_local = load_providers({**base, "COPILOT_LLM_X_DATA_POLICY": "local"})[0]
    assert cloud_claims_local.data_policy == "cloud"
    local_claims_cloud = load_providers({**base, "COPILOT_LLM_X_LOCAL": "1", "COPILOT_LLM_X_DATA_POLICY": "cloud"})[0]
    assert local_claims_cloud.data_policy == "local" and local_claims_cloud.local
    assert load_providers({**base, "COPILOT_LLM_X_DATA_POLICY": "???"})[0].data_policy == "cloud"


def test_default_can_be_listed_explicitly_and_uses_the_legacy_names():
    env = {
        **ON,
        "COPILOT_LLM_PROVIDERS": "default,b",
        "COPILOT_LLM_BASE_URL": "http://d/v1",
        "COPILOT_LLM_MODEL": "dm",
        "COPILOT_LLM_B_BASE_URL": "http://b/v1",
        "COPILOT_LLM_B_MODEL": "bm",
    }
    d, b = load_providers(env)
    assert d.name == "default" and d.model == "dm" and b.model == "bm"


def test_secret_comes_from_read_secret_file_when_using_the_real_environment(monkeypatch, tmp_path):
    keyfile = tmp_path / "gk"
    keyfile.write_text("file-key\n", encoding="utf-8")
    monkeypatch.setenv("COPILOT_LLM_ENABLED", "yes")
    monkeypatch.setenv("COPILOT_LLM_PROVIDERS", "groq")
    monkeypatch.setenv("COPILOT_LLM_GROQ_BASE_URL", "http://g/v1")
    monkeypatch.setenv("COPILOT_LLM_GROQ_MODEL", "m")
    monkeypatch.setenv("COPILOT_LLM_GROQ_API_KEY_FILE", str(keyfile))
    monkeypatch.delenv("COPILOT_LLM_GROQ_API_KEY", raising=False)
    (p,) = load_providers()
    assert p.api_key == "file-key" and "file-key" not in repr(p)


# ----------------------------------------------------------------------------- llm.load_settings still behaves as in Task 24


def test_load_settings_picks_the_first_usable_provider():
    env = {
        **ON,
        "COPILOT_LLM_PROVIDERS": "a,b,c",
        "COPILOT_LLM_A_BASE_URL": "http://a/v1",  # no model: not usable
        "COPILOT_LLM_B_BASE_URL": "http://b/v1",
        "COPILOT_LLM_B_MODEL": "bm",
        "COPILOT_LLM_C_BASE_URL": "http://c/v1",
        "COPILOT_LLM_C_MODEL": "cm",
    }
    s = llm.load_settings(env)
    assert s.configured and s.name == "b" and s.model == "bm"


def test_load_settings_with_nothing_usable_is_enabled_but_unconfigured():
    s = llm.load_settings({**ON, "COPILOT_LLM_PROVIDERS": "a", "COPILOT_LLM_A_BASE_URL": "http://a/v1"})
    assert s.enabled and not s.configured
    s2 = llm.load_settings({**ON, "COPILOT_LLM_PROVIDERS": "a", "COPILOT_LLM_A_ENABLED": "false"})
    assert s2.enabled and not s2.configured
    assert llm.load_settings({**ON, "COPILOT_LLM_PROVIDERS": "bad name"}).enabled


def test_load_settings_legacy_result_is_unchanged_from_task_24():
    env = {**ON, "COPILOT_LLM_BASE_URL": "http://x/v1/", "COPILOT_LLM_MODEL": "m", "COPILOT_LLM_TIMEOUT_S": "banana"}
    assert llm.load_settings(env) == llm.LlmSettings(
        enabled=True, base_url="http://x/v1", model="m", timeout_s=10.0, max_output_tokens=400
    )
    assert llm.load_settings({}) == llm.LlmSettings()


def test_settings_from_provider_round_trip_hides_the_key():
    cfg = ProviderConfig(name="g", base_url="http://g/v1", model="m", api_key="secret-k", local=True)
    s = llm.settings_from_provider(cfg)
    assert s.name == "g" and s.local and s.configured and s.api_key == "secret-k" and "secret-k" not in repr(s)
