"""브랜드 후보 — 고객별 ZBRAND 후보 목록과 그 보정 (SCHEMA §4.5-A).

ZBRAND 는 `csv_choice` 가 **고객의 후보 수**로 정한다. 1개면 자동, 여럿이면
검수 표의 드롭다운에서 사람이 고른다. 발주서 문구는 보지 않는다.

후보 = SAP 원본(`brand_master.csv`, 읽기 전용) ∪ 사람이 얹은 보정
(`brand_master_manual.csv`). 이 화면은 **보정만 쓴다.**

  add       SAP 에 아직 없는 후보를 더한다 (재추출 전 임시)
  override  SAP 행의 브랜드명을 고친다 (오탈자 등)
  suppress  잘못된 후보를 뺀다

저장은 서버 디스크의 CSV 를 고치고 모두에게 즉시 반영되므로 암호로 잠가 둔다
(`ui/auth.py`). 변경 이력은 CSV 의 Git 이력이 남긴다.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from backend.app import gitsync
from backend.app.masters import backup
from ui.auth import gate
from ui.service import MasterError, brand_store, catalog, preview_for, settings
from ui.views.picker import customer_header, customer_picker
from ui.views.rules import rule_preview

ACTIONS = list(brand_store.ACTIONS)
COLS = ["동작", "코드", "브랜드명", "비고"]
SOURCE_LABEL = {"sap": "SAP", "override": "SAP · 이름 보정", "add": "수동 추가"}


def render() -> None:
    entry = customer_picker("brands")

    st.title("브랜드 후보")
    st.caption(
        "고객별 ZBRAND 후보입니다. **후보가 1개면 자동으로 채우고, 여럿이면 검수 표에서 "
        "고릅니다.** SAP 원본은 고칠 수 없고, 아래 보정 표로 더하거나 빼거나 이름을 고칩니다."
    )

    if entry is None:
        st.info("왼쪽에서 고객을 선택하세요.", icon="👈")
        return

    customer_header(entry)

    tab_keys, tab_logic = st.tabs(["후보 표", "적용 로직"])
    with tab_keys:
        _candidates(entry)
    with tab_logic:
        _logic(entry)


def _candidates(entry) -> None:
    cfg = settings()
    merged = [b for b in brand_store.load_master(cfg.masters_dir) if b.kunnr == entry.kunnr]
    manual = [m for m in brand_store.load_manual(cfg.masters_dir) if m.kunnr == entry.kunnr]

    if merged:
        verdict = "자동으로 채웁니다" if len(merged) == 1 else "검수 표에서 고릅니다"
        st.markdown(f"**판정 후보 {len(merged)}개** — {verdict}")
        st.dataframe(
            pd.DataFrame([
                {"코드": b.zbrand, "브랜드명": b.name, "출처": SOURCE_LABEL.get(b.source, b.source)}
                for b in merged
            ]),
            width="stretch", hide_index=True,
        )
    else:
        st.warning("이 고객은 판정 후보가 없습니다. 발주서를 읽을 수 없습니다.", icon="⚠️")

    st.markdown("**보정**")
    st.caption(
        "add = SAP 에 없는 후보 추가 · override = SAP 행의 브랜드명 교체 · "
        "suppress = 후보에서 제외. **비고는 필수**입니다 — 왜 고쳤는지 남깁니다."
    )

    frame = pd.DataFrame(
        [{"동작": m.action, "코드": m.zbrand, "브랜드명": m.zbrant, "비고": m.note} for m in manual],
        columns=COLS,
    )
    unlocked = gate(cfg.master_edit_password, what="브랜드 후보")

    edited = st.data_editor(
        frame,
        disabled=not unlocked,
        num_rows="dynamic" if unlocked else "fixed",
        width="stretch",
        hide_index=True,
        key=f"brandmanual_{entry.kunnr}",
        column_config={
            "동작": st.column_config.SelectboxColumn(
                "동작", options=ACTIONS, required=True, width="small",
            ),
            "코드": st.column_config.TextColumn(
                "코드", required=True, width="small",
                help="override·suppress 는 SAP 에 있는 코드, add 는 SAP 에 없는 코드",
            ),
            "브랜드명": st.column_config.TextColumn(
                "브랜드명", width="medium", help="suppress 면 비워도 됩니다",
            ),
            "비고": st.column_config.TextColumn("비고 (필수)", required=True),
        },
    )

    if st.button("저장", type="primary", key=f"save_{entry.kunnr}", disabled=not unlocked):
        _save(entry, edited)

    if any(m.action == "add" for m in manual):
        st.caption("⚠️ add 한 코드는 SAP 재추출 전까지 SAP 이 모르는 코드일 수 있습니다.")
    _git_panel(entry, unlocked=unlocked)


def rows_for_save(kunnr: str, records: list[dict]) -> list:
    """표의 행 → 보정 행. 빈 줄은 없는 것으로 본다.

    화면에서 떼어놨다 — 순수 함수라 테스트가 잡을 수 있다.
    """
    rows = []
    for record in records:
        code = str(record.get("코드") or "").strip()
        action = str(record.get("동작") or "").strip()
        if not code and not action:
            continue
        rows.append(brand_store.ManualRow(
            kunnr=kunnr, zbrand=code, action=action,
            zbrant=str(record.get("브랜드명") or "").strip(),
            note=str(record.get("비고") or "").strip(),
        ))
    return rows


def _save(entry, edited: pd.DataFrame) -> None:
    cfg = settings()
    rows = rows_for_save(entry.kunnr, edited.to_dict("records"))
    try:
        brand_store.set_manual(
            cfg.masters_dir, entry.kunnr, rows,
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

    st.success(f"저장했습니다 — 보정 {len(rows)}행.", icon="✅")
    _autopush(entry)
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


# ── Git 동기화 ─────────────────────────────────────────────────────────
def _sync_message(kunnr: str, name: str) -> str:
    """`rules:` 커밋은 본문에 근거를 남긴다 (CLAUDE.md §6)."""
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"rules: 브랜드 후보 보정 — {name} ({kunnr})\n\n"
        f"브랜드 후보 화면에서 저장했다. 일시: {when}\n"
        f"영향 범위: 고객 {kunnr} 의 ZBRAND 후보.\n"
        f"보정표({brand_store.MANUAL_FILE})만 바뀐다. SAP 원본은 그대로다."
    )


def _autopush(entry) -> None:
    """저장 직후 자동 커밋·푸시. 꺼져 있으면 아무것도 하지 않는다."""
    cfg = settings()
    if not cfg.master_git_autopush:
        return
    result = gitsync.commit_and_push(
        cfg.project_root,
        [cfg.masters_dir / brand_store.MANUAL_FILE],
        _sync_message(entry.kunnr, entry.name),
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
    path = cfg.masters_dir / brand_store.MANUAL_FILE
    st_ = gitsync.status(cfg.project_root, [path])

    if not st_.repo:
        return          # Git 밖에서 돌리는 설치라면 갈릴 일 자체가 없다

    if st_.synced:
        head = "🔄 Git 과 같음 — 이 서버의 보정이 저장소에 반영돼 있습니다"
    elif st_.dirty:
        head = "🔄 커밋 안 된 변경이 있습니다 — `git pull` 이 막힐 수 있습니다"
    else:
        head = f"🔄 커밋 {st_.ahead}개가 아직 푸시되지 않았습니다"

    with st.expander(head, expanded=not st_.synced):
        st.caption(
            f"브랜치 `{st_.branch}` · 파일 `{brand_store.MANUAL_FILE}`"
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

        if st.button("커밋하고 푸시", key=f"gitpush_{entry.kunnr}", disabled=not unlocked or st_.synced):
            result = gitsync.commit_and_push(
                cfg.project_root, [path], _sync_message(entry.kunnr, entry.name)
            )
            (st.success if result.ok else st.error)(result.detail)
            if result.ok:
                st.rerun()
