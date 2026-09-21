"""브랜드 매핑 — 발주서 원문 문구 → SAP 브랜드 코드(ZBRAND).

SAP 이 주는 것은 `코드 → 이름` 뿐이고 **원문 키는 어디에도 없다.** 사람이 채운다.
그래서 이 화면은 `brand_master.csv` 를 읽기만 하고 `brand_keys.csv` 만 쓴다.

화면은 **참조표와 같은 모양의 표 하나**다 — 1행 = 매핑 1건. 브랜드마다 칸을
따로 여는 것보다, 지금 뭐가 어디에 걸려 있는지 한눈에 보인다.
**행 순서가 곧 판정 우선순위다** (SCHEMA §4.5).

저장 전 검증은 서버가 한다 — 그 고객에 없는 코드, 다른 코드가 이미 쓰는 문구는
거부된다. **저장은 서버 디스크의 CSV 를 고치고 모두에게 즉시 반영되므로**
암호로 잠가 둔다 (`ui/auth.py`). 변경 이력은 CSV 의 Git 이력이 남긴다.
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

    unlocked = gate(cfg.master_edit_password, what="브랜드 매핑")

    edited = st.data_editor(
        frame,
        disabled=not unlocked,
        num_rows="dynamic" if unlocked else "fixed",
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
    if left.button("저장", type="primary", key=f"save_{entry.kunnr}", disabled=not unlocked):
        _save(entry, keys, edited)
    right.caption(f"현재 {len(keys)}건 · 브랜드 {entry.mapped_count}/{entry.brand_count} 매핑됨")

    _unmapped(brands, keys, names)
    _git_panel(entry, unlocked=unlocked)


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


def _save(entry, before, edited: pd.DataFrame) -> None:
    kunnr = entry.kunnr
    grouped = group_for_save(kunnr, before, edited.to_dict("records"))

    if not grouped:
        st.info("바뀐 내용이 없습니다.")
        return

    cfg = settings()

    # 저장 버튼 한 번에 코드가 여러 개 바뀐다. 사본은 **누르기 1회당 1개**면 된다
    # — 코드마다 남기면 되돌릴 지점이 아니라 잡음이 쌓인다.
    keys_path = cfg.masters_dir / brand_store.KEYS_FILE
    try:
        backup.snapshot(keys_path, cfg.storage_dir, keep=cfg.master_backup_keep)
    except OSError as exc:
        st.error(
            f"사본을 남기지 못해 저장을 멈췄습니다 — {exc}\n\n"
            "되돌릴 수단 없이 덮어쓰지 않습니다. 디스크 여유와 "
            f"`{cfg.storage_dir}` 쓰기 권한을 확인하세요.",
            icon="🚫",
        )
        return

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

    if saved:
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
        f"rules: 브랜드 매핑 수정 — {name} ({kunnr})\n\n"
        f"브랜드 매핑 화면에서 저장했다. 일시: {when}\n"
        f"영향 범위: 고객 {kunnr} 의 브랜드 판정.\n"
        "원문 문구 → ZBRAND 대조표(refs/brand_keys.csv)만 바뀐다."
    )


def _autopush(entry) -> None:
    """저장 직후 자동 커밋·푸시. 꺼져 있으면 아무것도 하지 않는다."""
    cfg = settings()
    if not cfg.master_git_autopush:
        return
    result = gitsync.commit_and_push(
        cfg.project_root,
        [cfg.masters_dir / brand_store.KEYS_FILE],
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
    keys_path = cfg.masters_dir / brand_store.KEYS_FILE
    st_ = gitsync.status(cfg.project_root, [keys_path])

    if not st_.repo:
        return          # Git 밖에서 돌리는 설치라면 갈릴 일 자체가 없다

    if st_.synced:
        head = "🔄 Git 과 같음 — 이 서버의 매핑이 저장소에 반영돼 있습니다"
    elif st_.dirty:
        head = "🔄 커밋 안 된 변경이 있습니다 — `git pull` 이 막힐 수 있습니다"
    else:
        head = f"🔄 커밋 {st_.ahead}개가 아직 푸시되지 않았습니다"

    with st.expander(head, expanded=not st_.synced):
        st.caption(
            f"브랜치 `{st_.branch}` · 파일 `{brand_store.KEYS_FILE}`"
            + ("" if st_.tracked else " · **아직 Git 에 추적되지 않는 파일입니다**")
        )
        if not st_.synced:
            st.markdown(
                "이 서버에서 고친 내용이 저장소에 아직 없습니다. 이 상태로 "
                "`git pull` 을 하면 막히고, 막힌 것을 푼다고 `git checkout .` 을 "
                "누르면 **여기서 채운 값이 사라집니다.** 아래로 맞춰 두세요."
            )
        backups = backup.history(keys_path, cfg.storage_dir)
        if backups:
            st.caption(f"되돌릴 사본 {len(backups)}개 · 최근 `{backups[0].name}`")

        if st.button("커밋하고 푸시", key=f"gitpush_{entry.kunnr}", disabled=not unlocked or st_.synced):
            result = gitsync.commit_and_push(
                cfg.project_root, [keys_path], _sync_message(entry.kunnr, entry.name)
            )
            (st.success if result.ok else st.error)(result.detail)
            if result.ok:
                st.rerun()
