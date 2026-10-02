"""출하 마스터 — 고객별 출하조건(ZSHCO)·운송수단(VSART). `refs/shipping_master.csv`.

고객 1곳 = 행 1개. 규칙엔진이 `csv_choice` 로 읽는다(profiles/standard.yaml).
행이 없으면 둘 다 빈 칸이다 — 검수 표에 노랗게 뜨지만 전송은 막지 않는다.

화면은 원본 CSV 를 스프레드시트로 편다 — 고객을 고르면 그 고객 행만, 안 고르면
전체. 저장은 서버 디스크의 CSV 를 고치고 모두에게 즉시 반영되므로 브랜드와 같은
암호로 잠근다. 덮어쓰기 전 사본을 남기고, 켜져 있으면 Git 에 올린다.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from backend.app import gitsync
from ui.auth import gate
from ui.service import catalog, preview_for, settings, shipping_store
from ui.views import sheet
from ui.views.picker import customer_header, customer_picker

COLUMNS = {"고객코드": "kunnr", "고객명": "name1", "VSART": "vsart", "ZSHCO": "zshco"}
SCOPED = {"VSART": "vsart", "ZSHCO": "zshco"}      # 고객을 골랐을 때 — 나머지는 저장 때 채운다


def render() -> None:
    entry = customer_picker("shipping")

    st.title("Shipping Master")
    st.caption(
        "고객별 **Shipping Type (VSART)** 과 **Shipping Condition (ZSHCO)** 입니다. 저장하면 "
        "`refs/shipping_master.csv` 에 반영됩니다. 여기 적힌 값이 "
        "전송 행에 그대로 들어갑니다. 행이 없으면 빈 칸으로 두고 검수 표에 노랗게 표시만 "
        "합니다 (전송은 막지 않습니다)."
    )

    if entry is None:
        st.caption("왼쪽에서 고객을 고르면 그 고객 행만 봅니다. 지금은 **전체 표**입니다.")
    else:
        customer_header(entry)
        if st.button("← 전체 표", key="shipping_all"):
            st.session_state.pop("shipping_kunnr", None)
            st.rerun()
    _sheet(entry)


def _sheet(entry) -> None:
    cfg = settings()
    rows = shipping_store.load(cfg.masters_dir)
    if entry is not None:
        rows = [r for r in rows if r.kunnr == entry.kunnr]
        if not rows:
            st.warning("이 고객은 Shipping Master 에 아직 없습니다. 아래 칸에 넣고 저장하세요.", icon="⚠️")
            rows = [shipping_store.ShippingRow(kunnr=entry.kunnr)]

    heads = SCOPED if entry is not None else COLUMNS
    frame = pd.DataFrame(
        [{head: getattr(r, col) for head, col in heads.items()} for r in rows],
        columns=list(heads),
    )
    unlocked = gate(cfg.master_edit_password, what="Shipping Master")
    sheet.paste_hint()
    edited = sheet.editor(
        frame, key=f"shipping_{entry.kunnr if entry else 'all'}", unlocked=unlocked,
        column_config={
            "고객코드": st.column_config.TextColumn("고객코드", required=True, width="small"),
            "고객명": st.column_config.TextColumn("고객명", width="medium"),
            "VSART": st.column_config.TextColumn("Shipping Type (VSART)", width="small"),
            "ZSHCO": st.column_config.TextColumn("Shipping Condition (ZSHCO)", width="small"),
        },
    )
    st.caption("Shipping Type·Shipping Condition 을 둘 다 비우고 저장하면 그 고객 행을 지웁니다.")
    if st.button("저장", type="primary", key="shipping_save", disabled=not unlocked):
        _save(entry, edited, heads)


def _save(entry, edited: pd.DataFrame, heads: dict[str, str]) -> None:
    cfg = settings()
    fill = {"kunnr": entry.kunnr, "name1": entry.sap_name or entry.name} if entry else {}
    rows = [shipping_store.ShippingRow(**r) for r in sheet.records(edited, heads, fill)]
    try:
        saved = shipping_store.set_rows(
            cfg.masters_dir, rows, kunnr=entry.kunnr if entry else None,
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

    sheet.saved()
    st.success(f"저장했습니다 — {len(saved)}행.", icon="✅")
    _autopush(entry)
    catalog.clear()
    preview_for.clear()
    st.rerun()


def _autopush(entry) -> None:
    """저장 직후 자동 커밋·푸시. 꺼져 있으면 아무것도 하지 않는다."""
    cfg = settings()
    if not cfg.master_git_autopush:
        return
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    who = f"{entry.name} ({entry.kunnr})" if entry else "전체 표"
    scope = f"고객 {entry.kunnr} 의 VSART·ZSHCO" if entry else "전 고객의 VSART·ZSHCO"
    message = (
        f"rules: 출하 마스터 — {who}\n\n"
        f"Shipping Master 화면에서 저장했다. 일시: {when}\n"
        f"영향 범위: {scope}."
    )
    result = gitsync.commit_and_push(
        cfg.project_root, [cfg.masters_dir / shipping_store.FILE], message
    )
    if result.ok:
        st.caption(f"🔄 {result.detail}")
    else:
        st.warning(f"저장은 끝났습니다. Git 동기화만 실패했습니다.\n\n{result.detail}", icon="🔄")
