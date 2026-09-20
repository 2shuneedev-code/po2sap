"""Claude API 주소·프록시·CA 설정이 **실제로 클라이언트에 전달되는가**.

사내 이관에서 막히는 자리다. `.env` 에 `HTTPS_PROXY` 를 적어도 소용이 없다 —
`.env` 는 Settings 객체로만 읽히고 `os.environ` 으로 나가지 않아서 HTTP 클라이언트가
그 값을 영영 못 본다. 그래서 `LLM_PROXY` · `LLM_CA_BUNDLE` 을 명시적으로 받아
넘긴다. 그 연결이 끊기면 원인 모를 TLS/타임아웃으로 몇 시간이 날아간다.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.extraction.providers.base import LLMError

pytest.importorskip("anthropic")

from app.extraction.providers.anthropic_direct import _http_client  # noqa: E402


def test_no_proxy_means_sdk_default_client():
    """설정이 없으면 SDK 기본 클라이언트를 쓴다 — 괜히 감싸지 않는다."""
    assert _http_client(Settings(llm_provider="mock")) is None


def test_proxy_is_passed_to_the_client():
    client = _http_client(Settings(llm_provider="mock", llm_proxy="http://proxy:8080"))
    assert client is not None, "LLM_PROXY 가 클라이언트에 전달되지 않는다"


def test_ca_bundle_is_passed_to_the_client():
    """진짜 CA 번들이면 클라이언트가 만들어진다 (certifi 를 실물 대역으로 쓴다)."""
    certifi = pytest.importorskip("certifi")
    client = _http_client(Settings(llm_provider="mock", llm_ca_bundle=certifi.where()))
    assert client is not None, "LLM_CA_BUNDLE 이 클라이언트에 전달되지 않는다"


def test_malformed_ca_bundle_says_what_is_wrong(tmp_path):
    """파일은 있는데 인증서가 아니면 — 원본 SSLError 만 올라가면 원인을 못 찾는다."""
    bundle = tmp_path / "corp-ca.pem"
    bundle.write_text("이건 인증서가 아닙니다", encoding="utf-8")

    with pytest.raises(LLMError) as exc:
        _http_client(Settings(llm_provider="mock", llm_ca_bundle=str(bundle)))
    assert "PEM" in str(exc.value)


def test_missing_ca_bundle_fails_loudly(tmp_path):
    """★ 인증서가 없으면 조용히 검증을 건너뛰지 않는다.

    말없이 넘어가면 평문에 가까운 채로 도는데 아무도 모른다.
    """
    with pytest.raises(LLMError) as exc:
        _http_client(Settings(llm_provider="mock", llm_ca_bundle=str(tmp_path / "없음.pem")))
    assert "LLM_CA_BUNDLE" in str(exc.value)


# ── 주소 ─────────────────────────────────────────────────────────────
def test_base_url_defaults_to_empty():
    """비우면 SDK 기본 주소(api.anthropic.com)를 쓴다.

    `.env` 에 `LLM_BASE_URL=` 로 **빈 문자열**이 오는 경우도 같다 —
    `None` 인지가 아니라 **거짓값인지**를 본다. 코드도 `if settings.llm_base_url:`
    으로 판단한다.
    """
    assert not Settings(llm_provider="mock").llm_base_url


def test_gateway_and_anthropic_share_one_provider():
    """사내 게이트웨이와 직접 호출은 **같은 코드**다. 주소만 다르다."""
    from app.extraction.providers.factory import create_provider

    for provider in ("anthropic", "gateway"):
        settings = Settings(llm_provider=provider, llm_api_key="sk-ant-test",
                            llm_base_url="https://gw.example")
        built = create_provider(settings)
        assert type(built).__name__ == "AnthropicProvider"


def test_unknown_provider_names_the_valid_ones():
    from app.extraction.providers.factory import create_provider

    with pytest.raises(LLMError) as exc:
        create_provider(Settings(llm_provider="openai"))
    message = str(exc.value)
    assert "mock" in message and "anthropic" in message and "gateway" in message


def test_missing_key_points_at_mock_mode():
    """키 없이 시작하면 무엇을 해야 하는지 알려준다."""
    from app.extraction.providers.factory import create_provider

    with pytest.raises(LLMError) as exc:
        create_provider(Settings(llm_provider="anthropic", llm_api_key=""))
    assert "mock" in str(exc.value)


# ── 문서가 실제와 맞는가 ──────────────────────────────────────────────
def test_env_example_documents_the_keys_that_actually_work(root):
    """`.env.example` 이 먹지도 않는 키를 안내하면 이관이 막힌다."""
    text = (root / ".env.example").read_text(encoding="utf-8")
    for key in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_PROXY", "LLM_CA_BUNDLE"):
        assert f"{key}=" in text, f"{key} 안내가 없다"


def test_readme_documents_the_endpoint_setup(root):
    text = (root / "README.md").read_text(encoding="utf-8")
    assert "LLM_BASE_URL" in text
    assert "LLM_PROXY" in text, "프록시 설정이 README 에 없으면 사내에서 막힌다"
