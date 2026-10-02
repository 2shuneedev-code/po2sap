"""SALES ORDER 템플릿 — **전송 필드 목록과 순서의 원천** (`masters/templates/SALES ORDER.xlsx`).

템플릿은 1행이 영문 머리글, 2행이 필드 코드(전송 키)다. 열을 넣거나 빼거나 옮기면
검수 표·전송·화면이 그대로 따라온다. 필드별 속성(라벨·길이·역할 등)은 지금처럼
`_base/sap_defaults.yaml` 의 `field_specs` 에 둔다 — 템플릿은 **무엇을 어떤 순서로**만 정한다.

- 템플릿에 있고 `field_specs` 에 없는 필드: 머리글을 라벨로 쓰는 최소 스펙을 만든다.
- `field_specs` 에 있고 템플릿에 없는 필드: 전송하지 않는다 (속성만 남아 있어도 무해).
- 템플릿 파일 경로는 `sap_defaults.yaml` 의 `template:` 이 정한다. 없으면 `field_specs` 순서 그대로.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = ["TemplateError", "template_columns", "apply_template"]


class TemplateError(RuntimeError):
    pass


def template_columns(path: Path) -> list[tuple[str, str]]:
    """`[(필드 코드, 영문 머리글), ...]` — 템플릿 2행·1행, 왼쪽부터."""
    if not path.exists():
        raise TemplateError(f"SALES ORDER 템플릿이 없습니다: {path}")
    return list(_read(str(path), path.stat().st_mtime))


@lru_cache(maxsize=8)
def _read(path: str, _mtime: float) -> tuple[tuple[str, str], ...]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(min_row=1, max_row=2, values_only=True))
    finally:
        wb.close()
    if len(rows) < 2:
        raise TemplateError(f"템플릿 2행(필드 코드)이 없습니다: {path}")
    heads, codes = rows[0], rows[1]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i, raw in enumerate(codes):
        code = str(raw or "").strip()
        if not code:
            continue
        if code in seen:
            raise TemplateError(f"템플릿에 같은 필드 코드가 두 번 있습니다: {code}")
        seen.add(code)
        head = str((heads[i] if i < len(heads) else "") or "").strip()
        out.append((code, head))
    if not out:
        raise TemplateError(f"템플릿 2행에 필드 코드가 하나도 없습니다: {path}")
    return tuple(out)


def apply_template(data: dict[str, Any], masters_dir: Path) -> dict[str, Any]:
    """병합된 마스터의 `field_specs` 를 템플릿 순서·목록으로 바꾼다.

    `fields` 도 맞춘다 — 템플릿에 없는 필드의 매핑은 버리고, 매핑이 없는 새 필드는
    빈 칸(`const ""`)으로 두되 `todo` 를 달아 `validate_masters` 가 띄우게 한다.
    """
    rel = data.get("template")
    if not rel:
        return data
    columns = template_columns(Path(masters_dir) / str(rel))
    specs = data.get("field_specs") or {}
    fields = dict(data.get("fields") or {})

    new_specs: dict[str, Any] = {}
    for code, head in columns:
        spec = dict(specs.get(code) or {"label": head or code})
        if head:
            spec["sheet"] = head
        new_specs[code] = spec
        if code not in fields:
            fields[code] = {
                "from": "const", "value": "",
                "todo": f"템플릿에 새로 생긴 필드 {code}({head}) — 매핑이 없어 빈 칸으로 보낸다",
            }
    fields = {k: v for k, v in fields.items() if k in new_specs}
    return {**data, "field_specs": new_specs, "fields": fields}
