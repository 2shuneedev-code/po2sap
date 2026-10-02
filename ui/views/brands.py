"""Brand Master — 고객별 ZBRAND 후보. `refs/brand_master.csv` 를 직접 고친다.

ZBRAND 는 `csv_choice` 가 **고객의 후보 수**로 정한다. 1개면 자동, 여럿이면
검수 표의 드롭다운에서 사람이 고른다. 발주서 문구는 보지 않는다.

2026-09-30 부터 이 화면은 보정 파일이 아니라 원본을 스프레드시트로 고친다
(사장님 지시). 고객을 고르면 그 고객 행만, 안 고르면 파일 전체를 편다.
보정 파일(`brand_master_manual.csv`)은 판정에 여전히 합쳐지지만 화면에서는
고치지 않는다 — 행이 있으면 알려만 준다.

저장은 서버 디스크의 CSV 를 고치고 모두에게 즉시 반영되므로 암호로 잠가 둔다
(`ui/auth.py`). 덮어쓰기 전 사본을 남기고, 변경 이력은 CSV 의 Git 이력이 남긴다.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from backend.app import gitsync
from backend.app.masters import backup
from ui.auth import gate
from ui.service import MasterError, brand_store, catalog, choices_for, preview_for, settings
from ui.views import sheet
from ui.views.picker import customer_header, customer_picker
from ui.views.rules import rule_preview

COLUMNS = {"고객코드": "kunnr", "고객명": "name1", "코드": "zbrand", "브랜드명": "zbrant"}
SCOPED = {"코드": "zbrand", "브랜드명": "zbrant"}     # 고객을 골랐을 때 — 나머지는 저장 때 채운다


def render() -> None:
    entry = customer_picker("brands")

    st.title("Brand Master")
    st.caption(
        "고객별 ZBRAND 후보입니다. **후보가 1개면 자동으로 채우고, 여럿이면 검수 표에서 "
        "드롭다운으로 고릅니다.** 저장하면 `refs/brand_master.csv` 에 반영됩니다."
    )

    if entry is None:
        st.caption("왼쪽에서 고객을 고르면 그 고객 행만 봅니다. 지금은 **전체 표**입니다.")
        _sheet(None)
        return

    customer_header(entry)
    if st.button("← 전체 표", key="brands_all"):
        st.session_state.pop("brands_kunnr", None)
        st.rerun()

    tab_keys, tab_logic = st.tabs(["후보 표", "적용 로직"])
    with tab_keys:
        _sheet(entry)
    with tab_logic:
        _logic(entry)


def _sheet(entry) -> None:
    cfg = settings()
    rows = brand_store.load_sap_rows(cfg.masters_dir)
    if entry is not None:
        rows = [r for r in rows if r.kunnr == entry.kunnr]
        verdict = {0: "후보가 없어 발주서를 읽을 수 없습니다",
                   1: "자동으로 채웁니다"}.get(len(rows), "검수 표에서 고릅니다")
        st.markdown(f"**후보 {len(rows)}개** — {verdict}")

    heads = SCOPED if entry is not None else COLUMNS
    frame = pd.DataFrame(
        [{head: getattr(r, col) for head, col in heads.items()} for r in rows],
        columns=list(heads),
    )
    unlocked = gate(cfg.master_edit_password, what="Brand Master")
    sheet.paste_hint()
    edited = sheet.editor(
        frame, key=f"brand_{entry.kunnr if entry else 'all'}", unlocked=unlocked,
        column_config={
            "고객코드": st.column_config.TextColumn("고객코드", required=True, width="small"),
            "고객명": st.column_config.TextColumn("고객명", width="medium"),
            "코드": st.column_config.TextColumn("코드 (ZBRAND)", required=True, width="small"),
            "브랜드명": st.column_config.TextColumn("브랜드명", width="medium"),
        },
    )
    if st.button("저장", type="primary", key="brand_save", disabled=not unlocked):
        _save(entry, edited, heads)

    _overlay_notice(entry)
    _git_panel(entry, unlocked=unlocked)


def _save(entry, edited: pd.DataFrame, heads: dict[str, str]) -> None:
    cfg = settings()
    fill = {"kunnr": entry.kunnr, "name1": entry.sap_name or entry.name} if entry else {}
    rows = [brand_store.SapRow(**r) for r in sheet.records(edited, heads, fill)]
    try:
        brand_store.set_sap_rows(
            cfg.masters_dir, rows, kunnr=entry.kunnr if entry else None,
            storage_dir=cfg.storage_dir, backup_keep=cfg.master_backup_keep,
        )
    except (brand_store.BrandError, MasterError, ValueError) as exc:
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
    st.success(f"저장했습니다 — {len(rows)}행.", icon="✅")
    _autopush(entry)
    catalog.clear()
    preview_for.clear()
    choices_for.clear()
    st.rerun()


def _overlay_notice(entry) -> None:
    """보정 파일에 행이 남아 있으면 판정 후보가 이 표와 다를 수 있다 — 알린다."""
    manual = brand_store.load_manual(settings().masters_dir)
    if entry is not None:
        manual = [m for m in manual if m.kunnr == entry.kunnr]
    if manual:
        st.caption(
            f"⚠️ 보정 파일(`{brand_store.MANUAL_FILE}`)에 {len(manual)}행이 있어 판정에 "
            "함께 적용됩니다 — 후보가 이 표와 다를 수 있습니다."
        )


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


# ── Git 동기화 ─────────────────────────────────────────────────────────
def _sync_message(entry) -> str:
    """`rules:` 커밋은 본문에 근거를 남긴다 (CLAUDE.md §6)."""
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    who = f"{entry.name} ({entry.kunnr})" if entry else "전체 표"
    scope = f"고객 {entry.kunnr} 의 ZBRAND 후보" if entry else "전 고객의 ZBRAND 후보"
    return (
        f"rules: 브랜드 마스터 — {who}\n\n"
        f"Brand Master 화면에서 저장했다. 일시: {when}\n"
        f"영향 범위: {scope} ({brand_store.MASTER_FILE})."
    )


def _autopush(entry) -> None:
    """저장 직후 자동 커밋·푸시. 꺼져 있으면 아무것도 하지 않는다."""
    cfg = settings()
    if not cfg.master_git_autopush:
        return
    result = gitsync.commit_and_push(
        cfg.project_root,
        [cfg.masters_dir / brand_store.MASTER_FILE],
        _sync_message(entry),
    )
    if result.ok:
        st.caption(f"🔄 {result.detail}")
    else:
        st.warning(
            f"저장은 끝났습니다. Git 동기화만 실패했습니다.\n\n{result.detail}",
            icon="🔄",
        )


def _git_panel(entry, *, unlocked: bool) -> None:
    """서버의 CSV 가 저장소와 갈렸는지 보여주고, 원하면 맞춘다.

    자동으로 `pull` 하지 않는다 — 합쳐야 할 것이 있으면 사람이 판단할 일이고,
    화면이 조용히 되돌리는 것이 가장 나쁘다.
    """
    cfg = settings()
    path = cfg.masters_dir / brand_store.MASTER_FILE
    st_ = gitsync.status(cfg.project_root, [path])

    if not st_.repo:
        return          # Git 밖에서 돌리는 설치라면 갈릴 일 자체가 없다

    if st_.synced:
        head = "🔄 Git 과 같음 — 이 서버의 브랜드 마스터가 저장소에 반영돼 있습니다"
    elif st_.dirty:
        head = "🔄 커밋 안 된 변경이 있습니다 — `git pull` 이 막힐 수 있습니다"
    else:
        head = f"🔄 커밋 {st_.ahead}개가 아직 푸시되지 않았습니다"

    with st.expander(head, expanded=not st_.synced):
        st.caption(
            f"브랜치 `{st_.branch}` · 파일 `{brand_store.MASTER_FILE}`"
            + ("" if st_.tracked else " · **아직 Git 에 추적되지 않는 파일입니다**")
        )
        if not st_.synced:
            st.markdown(
                "이 서버에서 고친 내용이 저장소에 아직 없습니다. 이 상태로 "
                "`git pull` 을 하면 막히고, 막힌 것을 푼다고 `git checkout .` 을 "
                "누르면 **여기서 채운 값이 사라집니다.** 아래로 맞춰 두세요."
            )
        backups = backup.history(path, cfg.storage_dir)
        if backups:
            st.caption(f"되돌릴 사본 {len(backups)}개 · 최근 `{backups[0].name}`")

        key = f"gitpush_{entry.kunnr if entry else 'all'}"
        if st.button("커밋하고 푸시", key=key, disabled=not unlocked or st_.synced):
            result = gitsync.commit_and_push(cfg.project_root, [path], _sync_message(entry))
            (st.success if result.ok else st.error)(result.detail)
            if result.ok:
                st.rerun()
