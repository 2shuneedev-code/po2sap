"""브랜드 매핑 — 발주서 원문 문구 → SAP 브랜드 코드(ZBRAND).

SAP 이 주는 것은 `코드 → 이름` 뿐이고 **원문 키는 어디에도 없다.** 사람이 채운다.
그래서 이 화면은 `brand_master.csv` 를 읽기만 하고 `brand_keys.csv` 만 쓴다.

화면은 **참조표와 같은 모양의 표 하나**다 — 1행 = 매핑 1건. 브랜드마다 칸을
따로 여는 것보다, 지금 뭐가 어디에 걸려 있는지 한눈에 보인다.
**행 순서가 곧 판정 우선순위다** (SCHEMA §4.5).

저장 전 검증은 서버가 한다 — 그 고객에 없는 코드, 다른 코드가 이미 쓰는 문구는
거부된다. 인증·승인 흐름은 범위 밖이고(사내망), 변경 이력은 CSV 의 Git 이력이 남긴다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.service import MasterError, brand_store, catalog, preview_for, settings
from ui.views.picker import customer_header, customer_picker
from ui.views.rules import rule_preview

MATCHES = ["contains", "equals"]
COLS = ["브랜드코드", "브랜드명", "원문 문구", "비교", "비고"]


def render() -> None:
    entry = customer_picker("brands")

    st.title("브랜드 매핑")
    st.caption(
        "발주서에 적힌 문구를 SAP 브랜드 코드로 잇습니다. "
        "코드·이름은 SAP 원본이라 고칠 수 없고, 채우는 것은 **원문 문구**뿐입니다."
    )

    if entry is None:
        st.info("왼쪽에서 고객을 선택하세요.", icon="👈")
        return

    customer_header(entry)

    tab_keys, tab_logic = st.tabs(["매핑 표", "적용 로직"])
    with tab_keys:
        _mapping(entry)
    with tab_logic:
        _logic(entry)


def _mapping(entry) -> None:
    cfg = settings()
    brands = [b for b in brand_store.load_master(cfg.masters_dir) if b.kunnr == entry.kunnr]
    keys = [k for k in brand_store.load_keys(cfg.masters_dir) if k.kunnr == entry.kunnr]

    if not brands:
        st.warning("이 고객은 SAP 브랜드 마스터에 등록된 코드가 없습니다.", icon="⚠️")
        return

    names = {b.zbrand: b.name for b in brands}
    codes = [b.zbrand for b in brands]

    st.caption(
        "1행 = 매핑 1건. **위에서부터 순서대로** 판정하므로 행 순서가 곧 우선순위입니다. "
        "행을 추가하려면 맨 아래 빈 줄에 입력하고, 지우려면 행을 선택해 삭제하세요."
    )

    frame = pd.DataFrame(
        [
            {
                "브랜드코드": k.zbrand,
                "브랜드명": names.get(k.zbrand, "(SAP 에 없는 코드)"),
                "원문 문구": k.text,
                "비교": k.match,
                "비고": k.note,
            }
            for k in keys
        ],
        columns=COLS,
    )

    edited = st.data_editor(
        frame,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key=f"brandmap_{entry.kunnr}",
        column_config={
            "브랜드코드": st.column_config.SelectboxColumn(
                "코드", options=codes, required=True, width="small",
                help="이 고객에게 SAP 이 등록한 브랜드 코드만 고를 수 있습니다",
            ),
            "브랜드명": st.column_config.TextColumn(
                "브랜드명 (SAP)", disabled=True, width="medium",
                help="SAP 원본입니다. 저장할 때 코드로 다시 채워집니다",
            ),
            "원문 문구": st.column_config.TextColumn(
                "발주서 원문 문구", required=True, width="medium",
                help="발주서에 실제로 찍히는 글자",
            ),
            "비교": st.column_config.SelectboxColumn(
                "비교", options=MATCHES, default="contains", width="small",
                help="contains = 포함 · equals = 완전일치",
            ),
            "비고": st.column_config.TextColumn("비고", help="왜 이렇게 뒀는지"),
        },
    )

    left, right = st.columns([1, 4])
    if left.button("저장", type="primary", key=f"save_{entry.kunnr}"):
        _save(entry.kunnr, keys, edited)
    right.caption(f"현재 {len(keys)}건 · 브랜드 {entry.mapped_count}/{entry.brand_count} 매핑됨")

    _unmapped(brands, keys, names)


def _unmapped(brands, keys, names: dict) -> None:
    mapped = {k.zbrand for k in keys}
    rest = [b for b in brands if b.zbrand not in mapped]
    if not rest:
        st.success("이 고객의 브랜드가 모두 매핑되어 있습니다.", icon="✅")
        return
    with st.expander(f"아직 매핑 안 된 브랜드 ({len(rest)})"):
        st.caption("발주서에서 이 브랜드 문구를 만나면 판정이 실패합니다. 위 표에 추가하세요.")
        st.dataframe(
            pd.DataFrame([{"코드": b.zbrand, "브랜드명": b.name} for b in rest]),
            width="stretch", hide_index=True,
        )


def group_for_save(kunnr: str, before, records: list[dict]) -> dict[str, list]:
    """표의 행들을 **코드별 묶음**으로 만든다.

    `set_keys` 는 (고객, 코드) 한 묶음을 통째로 교체한다. 그래서 표에서 사라진
    코드는 **빈 묶음으로 명시해 지워야** 한다 — 안 그러면 화면에서 지운 매핑이
    파일에 남아 조용히 계속 판정된다. 화면에는 없는데 발주서는 그 문구로 계속
    판정되는 상태가 가장 나쁘다.

    화면에서 떼어놨다 — 순수 함수라 테스트가 잡을 수 있다.
    """
    grouped: dict[str, list] = {}
    for record in records:
        code = str(record.get("브랜드코드") or "").strip()
        text = str(record.get("원문 문구") or "").strip()
        if not code or not text:
            continue                       # 빈 줄은 없는 것으로 본다
        grouped.setdefault(code, []).append(
            brand_store.BrandKey(
                kunnr=kunnr, zbrand=code,
                match=str(record.get("비교") or "contains"),
                text=text, note=str(record.get("비고") or ""),
            )
        )

    for code in {k.zbrand for k in before} - set(grouped):
        grouped[code] = []
    return grouped


def _save(kunnr: str, before, edited: pd.DataFrame) -> None:
    grouped = group_for_save(kunnr, before, edited.to_dict("records"))

    if not grouped:
        st.info("바뀐 내용이 없습니다.")
        return

    cfg = settings()
    saved = failed = 0
    for code, rows in grouped.items():
        try:
            brand_store.set_keys(cfg.masters_dir, kunnr, code, rows)
            saved += 1
        except (brand_store.BrandError, MasterError, ValueError) as exc:
            # 거부 사유를 그대로 보여준다. 그 코드의 파일 내용은 바뀌지 않았다.
            st.error(f"`{code}` — {exc}", icon="🚫")
            failed += 1

    if failed:
        st.warning(
            f"{saved}개 코드는 저장했고 {failed}개는 거부됐습니다. "
            "거부된 코드는 이전 값 그대로입니다.",
            icon="⚠️",
        )
    else:
        st.success(f"저장했습니다 — 코드 {saved}개.", icon="✅")

    catalog.clear()
    preview_for.clear()
    st.rerun()


def _logic(entry) -> None:
    if not entry.configured:
        st.info(
            "이 고객은 **전용 규칙이 없어 공용 설정으로 읽습니다.** 아래는 그 공용 "
            "설정입니다. 문서 양식을 아는 규칙을 만들려면 `masters/customers/` 에 "
            "파일을 추가하세요 (서식: `_template.yaml`).",
            icon="ℹ️",
        )
    try:
        rule_preview(preview_for(entry.parse_code))
    except (MasterError, ValueError) as exc:
        st.error(f"규칙을 읽지 못했습니다: {exc}")
