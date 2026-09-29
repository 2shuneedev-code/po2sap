"""출하 마스터 — 고객별 출하조건(ZSHCO)·운송수단(VSART). `refs/shipping_master.csv`.

고객 1곳 = 행 1개. 규칙엔진이 `csv_choice` 로 읽는다(profiles/standard.yaml).
행이 없으면 둘 다 빈 칸이다 — 검수 표에 노랗게 뜨지만 전송은 막지 않는다.

저장은 서버 디스크의 CSV 를 고치고 모두에게 즉시 반영되므로 브랜드와 같은
암호로 잠근다. 덮어쓰기 전 사본을 남기고, 켜져 있으면 Git 에 올린다.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from backend.app import gitsync
from ui.auth import gate
from ui.service import catalog, preview_for, settings, shipping_store
from ui.views.picker import customer_header, customer_picker


def render() -> None:
    entry = customer_picker("shipping")

    st.title("Shipping Master")
    st.caption(
        "고객별 **출하조건(ZSHCO)** 과 **운송수단(VSART)** 입니다. 여기 적힌 값이 전송 행에 "
        "그대로 들어갑니다. 행이 없으면 빈 칸으로 두고 검수 표에 노랗게 표시만 합니다 "
        "(전송은 막지 않습니다)."
    )

    if entry is None:
        st.info("왼쪽에서 고객을 선택하세요.", icon="👈")
    else:
        customer_header(entry)
        _editor(entry)

    with st.expander("전체 표", expanded=entry is None):
        _all_rows()


def _editor(entry) -> None:
    cfg = settings()
    current = shipping_store.get(cfg.masters_dir, entry.kunnr)
    if current is None:
        st.warning("이 고객은 Shipping Master 에 아직 없습니다.", icon="⚠️")

    unlocked = gate(cfg.master_edit_password, what="Shipping Master")
    with st.form(f"shipping_{entry.kunnr}"):
        left, right = st.columns(2)
        zshco = left.text_input(
            "출하조건 (ZSHCO)", value=current.zshco if current else "",
            disabled=not unlocked,
        )
        vsart = right.text_input(
            "운송수단 (VSART)", value=current.vsart if current else "",
            disabled=not unlocked,
        )
        st.caption("둘 다 비우고 저장하면 이 고객 행을 지웁니다.")
        submitted = st.form_submit_button("저장", type="primary", disabled=not unlocked)

    if submitted:
        _save(entry, zshco, vsart)


def _save(entry, zshco: str, vsart: str) -> None:
    cfg = settings()
    row = shipping_store.ShippingRow(
        kunnr=entry.kunnr, name1=entry.sap_name or entry.name, zshco=zshco, vsart=vsart,
    )
    try:
        saved = shipping_store.set_row(
            cfg.masters_dir, row,
            storage_dir=cfg.storage_dir, backup_keep=cfg.master_backup_keep,
        )
    except shipping_store.ShippingError as exc:
        st.error(f"저장하지 않았습니다 — {exc}", icon="🚫")
        return
    except OSError as exc:
        st.error(
            f"사본을 남기지 못해 저장을 멈췄습니다 — {exc}\n\n"
            f"디스크 여유와 `{cfg.storage_dir}` 쓰기 권한을 확인하세요.",
            icon="🚫",
        )
        return

    st.success("저장했습니다." if saved else "이 고객 행을 지웠습니다.", icon="✅")
    _autopush(entry)
    catalog.clear()
    preview_for.clear()
    st.rerun()


def _all_rows() -> None:
    rows = shipping_store.load(settings().masters_dir)
    if not rows:
        st.caption("등록된 고객이 없습니다.")
        return
    st.dataframe(
        pd.DataFrame([
            {"고객코드": r.kunnr, "고객명": r.name1, "ZSHCO": r.zshco, "VSART": r.vsart}
            for r in rows
        ]),
        width="stretch", hide_index=True,
    )


def _autopush(entry) -> None:
    """저장 직후 자동 커밋·푸시. 꺼져 있으면 아무것도 하지 않는다."""
    cfg = settings()
    if not cfg.master_git_autopush:
        return
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    message = (
        f"rules: 출하 마스터 — {entry.name} ({entry.kunnr})\n\n"
        f"Shipping Master 화면에서 저장했다. 일시: {when}\n"
        f"영향 범위: 고객 {entry.kunnr} 의 ZSHCO·VSART."
    )
    result = gitsync.commit_and_push(
        cfg.project_root, [cfg.masters_dir / shipping_store.FILE], message
    )
    if result.ok:
        st.caption(f"🔄 {result.detail}")
    else:
        st.warning(f"저장은 끝났습니다. Git 동기화만 실패했습니다.\n\n{result.detail}", icon="🔄")
