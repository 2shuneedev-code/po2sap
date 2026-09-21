"""`scripts/pin_fixture.py` — 캐시에 쌓인 호출들을 **문서 단위 픽스처 1개**로 다시 모은다.

문서 1건이 호출 여러 번이 된 뒤에도 픽스처는 문서 단위 하나다 (design §3.5). 그래야 청크 크기를
바꿔도 미아가 되지 않는다. **실물 `backend/tests/fixtures/` 에는 쓰지 않는다** — 경로를 임시로 돌린다.
"""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest
from app.config import Settings
from app.extraction import Extractor
from app.extraction.providers import cache as llm_cache
from app.extraction.providers.base import LLMError
from app.masters.loader import load_customer
from llm_fakes import FakeProvider, lines_payload, make_doc, outline_payload


@pytest.fixture(scope="module")
def pin(root):
    path = root / "scripts" / "pin_fixture.py"
    spec = importlib.util.spec_from_file_location("pin_fixture_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_htm(tmp_path, pages_text: str, name="pin-target.htm"):
    body = "".join(f"<div>{line}</div>" for line in pages_text.split("\n"))
    path = tmp_path / name
    path.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path, masters_dir, pin, monkeypatch):
    """캐시는 임시 storage, 픽스처는 임시 폴더 — 실물 저장소를 건드리지 않는다."""
    cfg = Settings(llm_provider="mock", masters_dir=masters_dir, storage_dir=tmp_path / "st",
                   llm_max_tokens=1120, llm_max_concurrency=2)
    out = tmp_path / "fx"
    monkeypatch.setattr(pin, "get_settings", lambda: cfg)
    monkeypatch.setattr(
        llm_cache, "fixture_path",
        lambda _dir, customer, filename: out / llm_cache.fixture_name(customer, filename))
    return cfg, out


def run(pin, monkeypatch, path, *extra) -> int:
    monkeypatch.setattr(sys, "argv", ["pin_fixture.py", str(path), "--customer", "MSC", *extra])
    return pin.main()


def test_the_cached_calls_are_pinned_as_one_document_fixture(
        env, pin, monkeypatch, tmp_path, masters_dir, capsys):
    cfg, out = env
    doc, blocks = make_doc([20, 15])
    path = write_htm(tmp_path, "\n".join(doc.doc_lines[1:]))
    from app.extraction.preprocess import load_document

    real = load_document(path)
    assert real.doc_lines == doc.doc_lines                     # 합성 문서와 줄이 같다

    fake = FakeProvider(real, outline_payload(real, blocks))
    ex = Extractor(cfg, provider=fake, sleep=lambda _s: None).extract_payload(
        real, load_customer("msc", masters_dir))
    assert ex.issues == [] and len(fake.calls) > 3             # 호출이 여러 번이었다

    assert run(pin, monkeypatch, path) == 0

    fixture = out / llm_cache.fixture_name("MSC", real.filename)
    data = json.loads(fixture.read_text(encoding="utf-8"))
    shipments = data["payload"]["shipments"]
    assert [len(s["lines"]) for s in shipments] == [20, 15]    # 문서 단위 1개로 합쳐졌다
    # 병합이 붙인 배선(chunk·page·line_no)은 진짜 응답이 아니므로 들어가지 않는다
    assert all(set(item) <= {"src", "confidence", "item_code", "quantity"}
               for s in shipments for item in s["lines"])
    assert data["model"] == "fake-model"

    # 박은 뒤에는 프로바이더가 필요 없다 — 문서 단위 픽스처가 그대로 재생된다
    replay = Extractor(cfg, provider=FakeProvider(real)).parse_file(path, "MSC")
    assert replay.cached is True
    assert [len(s.lines) for s in replay.raw.shipments] == [20, 15]
    assert replay.error_count == 0


def test_a_document_with_a_hole_is_not_pinned(
        env, pin, monkeypatch, tmp_path, masters_dir, capsys):
    """구멍 난 문서를 정답처럼 고정하면 그 구멍이 영영 안 보인다."""
    cfg, out = env
    doc, blocks = make_doc([20])
    path = write_htm(tmp_path, "\n".join(doc.doc_lines[1:]))
    from app.extraction.preprocess import load_document

    real = load_document(path)
    bad = blocks[0][0] + 10

    def handler(start, end):
        if start <= bad <= end:
            raise LLMError("읽기 실패")
        return lines_payload(real, start, end)

    Extractor(cfg, provider=FakeProvider(real, outline_payload(real, blocks), handler),
              sleep=lambda _s: None).extract_payload(real, load_customer("msc", masters_dir))

    assert run(pin, monkeypatch, path) == 1
    assert not (out / llm_cache.fixture_name("MSC", real.filename)).exists()
    assert "박지 않습니다" in capsys.readouterr().out


def test_nothing_is_called_when_the_cache_is_empty(env, pin, monkeypatch, tmp_path, capsys):
    """실제 호출은 절대 하지 않는다 — 캐시에 없으면 없다고 말하고 끝낸다."""
    doc, _ = make_doc([8])
    path = write_htm(tmp_path, "\n".join(doc.doc_lines[1:]))
    assert run(pin, monkeypatch, path) == 1
    assert "캐시에 없습니다" in capsys.readouterr().out
