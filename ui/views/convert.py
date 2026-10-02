"""P/O 변환 — 발주서(PDF/HTM)를 올리면 전송표가 되고, 고쳐서 SAP 으로 보낸다.

process.md §4 화면 1~3 을 한 페이지로 합쳤다. 스트림릿은 위에서 아래로 한 번
도는 모델이라, 화면을 나누는 것보다 단계를 접었다 펴는 편이 흐름이 끊기지 않는다.

값의 주인은 **화면**이다 (계약 §6). 재검증은 `issues`/`edited` 만 갱신하고
입력값을 덮어쓰지 않는다. 반대로 **무엇이 바뀌었는지 판단하는 쪽은 서버**다
(계약 §6.1) — `edited` 를 화면이 계산하지 않는다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.service import (
    Batch,
    MasterError,
    SendBlocked,
    choices_for,
    merge_edits,
    preview_for,
    repo,
    send_batch,
    settings,
    start_batch,
    summary,
)
from ui.views.picker import customer_header, customer_picker
from ui.views.rules import rule_preview

META = ["#", "파일", "그룹"]


def render() -> None:
    entry = customer_picker("convert")

    st.title("P/O Transfer")
    st.caption("발주서(PDF·HTM)를 올리면 SAP 전송표로 펼쳐집니다. 고친 값이 그대로 전송됩니다.")

    if entry is None:
        st.info("왼쪽에서 거래처를 선택하세요.", icon="👈")
        return

    customer_header(entry)

    if not entry.ready:
        _no_brands(entry)
        return
    if not entry.configured and entry.brand_count > 1:
        _brand_choice_notice(entry)

    # 거래처를 바꾸면 이전 배치를 놓는다 — 다른 거래처 행이 섞이면 안 된다.
    if st.session_state.get("convert_customer") != entry.parse_code:
        st.session_state["convert_customer"] = entry.parse_code
        st.session_state.pop("batch_id", None)

    _rules_section(entry)
    batch = _upload_section(entry)
    if batch is not None:
        _review_section(batch)


# ── 규칙 미설정 거래처 ────────────────────────────────────────────────
def _no_brands(entry) -> None:
    """브랜드 마스터에도 없는 고객 — 읽어낼 근거가 하나도 없다."""
    st.error(
        "이 고객은 **브랜드 마스터에 등록된 브랜드가 없습니다.** 브랜드를 "
        "판정할 근거가 없어 발주서를 읽어도 전송할 수 없습니다. SAP 쪽 등록을 "
        "먼저 확인하세요.",
        icon="🚫",
    )


def _brand_choice_notice(entry) -> None:
    """공용 프로필 거래처의 브랜드 후보가 여럿 — 사람이 골라야 하는 것만 알린다.

    판매처·출하처·최종고객은 기본이 고객코드라 따로 안내하지 않는다.
    확인 중인 값은 검수 표의 노란 칸이 이미 보여준다.
    """
    st.info(
        f"브랜드 후보가 `{entry.brand_count}`개라 자동으로 정하지 않습니다 — "
        "검수 표의 ZBRAND 드롭다운에서 고르세요.",
        icon="🏷️",
    )


# ── ① 규칙 미리보기 ───────────────────────────────────────────────────
def _rules_section(entry) -> None:
    with st.expander("이 거래처에 자동 적용되는 값", expanded=False):
        try:
            rule_preview(preview_for(entry.parse_code))
        except (MasterError, ValueError) as exc:
            st.error(f"규칙을 읽지 못했습니다: {exc}")


# ── ② 업로드 ─────────────────────────────────────────────────────────
def _upload_section(entry) -> Batch | None:
    types = entry.file_types or ["pdf", "htm", "html"]
    st.markdown("#### 발주서 업로드")

    uploads = st.file_uploader(
        f"{entry.name} 발주서 — 여러 개 동시 가능",
        accept_multiple_files=True,
        key=f"up_{entry.parse_code}",
    )

    # file_types 는 **안내용**이다. 다른 형식이어도 막지 않고 경고만 한다 (계약 §1).
    odd = [u.name for u in uploads or [] if u.name.rsplit(".", 1)[-1].lower() not in types]
    if odd:
        st.warning(
            f"{', '.join(odd)} — 이 거래처는 보통 {'/'.join(t.upper() for t in types)} 로 "
            "보냅니다. 그대로 읽어봅니다.",
            icon="⚠️",
        )

    if uploads and st.button("변환하기", type="primary"):
        with st.status("발주서를 읽는 중…", expanded=True) as status:
            try:
                # 진행 막대 하나를 제자리에서 갱신한다. 큰 문서는 호출이 수십 번이라
                # `st.write` 로 줄을 쌓으면 화면이 로그로 넘친다.
                bar = st.progress(0.0, text=f"{len(uploads)}개 파일 저장")
                batch = start_batch(entry.parse_code, uploads, on_progress=_ticker(bar))
                bar.empty()
                for f in batch.files:
                    if f.status == "DONE":
                        st.write(f"✔ {f.name} — {f.row_count}행")
                    else:
                        st.write(f"✖ {f.name} — {f.error or '파싱 실패'}")
                st.session_state["batch_id"] = batch.batch_id
                status.update(label=f"변환 완료 — {len(batch.rows)}행", state="complete")
            except (ValueError, MasterError) as exc:
                status.update(label="변환 실패", state="error")
                st.error(str(exc))
                return None

    batch_id = st.session_state.get("batch_id")
    if not batch_id:
        return None
    try:
        return repo().load(batch_id)
    except KeyError:
        st.session_state.pop("batch_id", None)
        return None


def _tick(bar, stage: str, done: int, total: int, label: str) -> None:
    """진행 막대를 제자리에서 갱신한다. `st.write` 로 줄을 쌓지 않는다.

    호출은 `start_batch` 를 부른 **스크립트 스레드에서만** 온다 — 추출기가 워커 스레드에서는
    콜백을 부르지 않는다. 스트림릿 위젯은 그 스레드에서만 만질 수 있다.
    """
    bar.progress(min(1.0, done / max(total, 1)), text=f"{label} — {stage} {done}/{total}")


def _ticker(bar):
    """`start_batch(on_progress=...)` 에 넘길 콜백 — `_tick` 에 막대를 묶는다."""
    return lambda stage, done, total, label: _tick(bar, stage, done, total, label)


# ── ③ 검수 ───────────────────────────────────────────────────────────
def _review_section(batch: Batch) -> None:
    if not batch.rows:
        failed = [f"{f.name}: {f.error}" for f in batch.files if f.status == "FAILED" and f.error]
        st.error(
            "읽어낸 행이 없습니다. 파일 형식이나 규칙의 `hints` 를 확인하세요."
            + ("\n\n" + "\n\n".join(failed) if failed else "")
        )
        return

    st.divider()
    st.markdown("#### 검수")

    files = sorted({r.file for r in batch.rows})
    groups = sorted({r.group for r in batch.rows if r.group})

    bar = st.columns([2, 2, 3])
    file_filter = bar[0].selectbox("파일", ["전체", *files], key="f_file")
    group_filter = (
        bar[1].selectbox("그룹", ["전체", *groups], key="f_group") if groups else "전체"
    )

    visible = [
        r for r in batch.rows
        if (file_filter == "전체" or r.file == file_filter)
        and (group_filter == "전체" or r.group == group_filter)
    ]
    if not visible:
        st.info("필터에 해당하는 행이 없습니다.")
        return

    show_all = bar[2].toggle(
        "숨김 컬럼까지 보기",
        key="show_hidden",
        help="숨겨진 컬럼도 **전송에는 그대로 들어갑니다**(빈 값). 보기에서만 접어둔 것입니다.",
    )

    # 일괄 채우기는 표 **위에** 보이되, 표의 미저장 수정을 이어받아야 하므로
    # 자리만 먼저 잡고 내용은 표를 그린 뒤에 채운다.
    bulk_slot = st.container()
    frame, issues_by_row = _to_frame(visible, _grid_columns(batch))
    edited = st.data_editor(
        frame,
        width="stretch",
        hide_index=True,
        height=min(620, 90 + 36 * len(visible)),
        column_order=_column_order(batch, show_all),
        column_config=_column_config(batch),
        disabled=META,
        key=f"grid_{batch.batch_id}_{file_filter}_{group_filter}_{show_all}"
            f"_{st.session_state.get(_GRID_VERSION, 0)}",
    )

    with bulk_slot:
        _bulk_fill(batch, edited, visible)

    if st.button("검증", help="고친 값을 서버 스냅샷에 반영하고 다시 검사합니다"):
        _apply(batch, edited, visible)
        st.rerun()

    _summary_bar(batch)
    _issue_list(batch, issues_by_row)
    _send_section(batch)


# 표 키에 붙이는 판 번호. 일괄 채우기 뒤에 올린다 — 같은 키면 표가 들고 있던
# 칸 단위 수정이 새 값 위에 다시 얹혀, 방금 채운 값을 옛 값이 덮는다.
_GRID_VERSION = "grid_version"


def _bulk_fill(batch: Batch, edited: pd.DataFrame, visible) -> None:
    """한 값을 여러 행에 한 번에 — 스트림릿 표에는 엑셀의 채우기 핸들이 없다.

    붙여넣기는 **복사한 크기만큼만** 들어간다. 한 칸을 복사해 열 전체를 잡고
    붙여넣으면 첫 칸 하나만 바뀐다(표 라이브러리 동작, 2026-09-30 확인).
    어느 열을 먼저 보일지는 드롭다운 후보가 있는 열 — YAML 이 정한다.
    """
    choices = choices_for(batch.customer)
    columns = [c for c in _column_order(batch, True) if c not in META]
    if not columns:
        return
    first = next((c for c in columns if c in choices), columns[0])

    with st.expander("⇣ 열 일괄 채우기 — 한 값을 여러 행에 한 번에", expanded=bool(choices)):
        left, mid, right, go = st.columns([2, 3, 2, 1], vertical_alignment="bottom")
        column = left.selectbox("열", columns, index=columns.index(first), key="bulk_col")
        if column in choices:
            names = {o[0]: o[1] for o in choices[column] if len(o) > 1}
            value = mid.selectbox(
                "값", [o[0] for o in choices[column]], key=f"bulk_val_{column}",
                format_func=lambda code: f"{code} · {names[code]}" if code in names else code,
            )
        else:
            value = mid.text_input("값", key=f"bulk_val_{column}")
        scope = right.radio("대상", ["빈 칸만", "보이는 행 전체"], key="bulk_scope", horizontal=True)
        if go.button("채우기", type="primary", key="bulk_go"):
            frame = edited.copy()
            current = frame[column].fillna("").astype(str).str.strip()
            mask = current == "" if scope == "빈 칸만" else pd.Series(True, index=frame.index)
            frame.loc[mask, column] = value
            _apply(batch, frame, visible)
            st.session_state[_GRID_VERSION] = st.session_state.get(_GRID_VERSION, 0) + 1
            st.toast(f"{column} — {int(mask.sum())}행을 채웠습니다.", icon="✅")
            st.rerun()


def _to_frame(rows, columns: list[str]) -> tuple[pd.DataFrame, dict]:
    data = []
    issues_by_row = {}
    for index, row in enumerate(rows, start=1):
        record = {
            "#": index,
            "파일": row.file,
            "그룹": row.group or "",
            **{name: row.fields.get(name, "") for name in columns},
        }
        data.append(record)
        if row.issues:
            issues_by_row[index] = (row, row.issues)
    return pd.DataFrame(data, columns=[*META, *columns]), issues_by_row


def _column_order(batch: Batch, show_all: bool) -> list[str]:
    """중요한 컬럼을 앞으로. 36컬럼을 `_base` 순서 그대로 펼치면 검수자가
    `BSTKD`·`MATNR` 을 보려고 빈 컬럼을 한참 지나쳐야 한다.

    순서는 마스터의 `grid.pinned`/`hidden` 이 정한다 — 이 파일에 필드 이름을
    나열하지 않는다 (CLAUDE.md P2). 숨김 컬럼도 **전송에는 그대로 들어간다.**
    """
    columns = _grid_columns(batch)
    pinned = [c for c in (batch.grid.get("pinned") or []) if c in columns]
    hidden = set(batch.grid.get("hidden") or [])
    rest = [c for c in columns if c not in pinned and c not in hidden]
    tail = [c for c in columns if c in hidden] if show_all else []
    meta = [m for m in META if m != "그룹" or any(r.group for r in batch.rows)]
    return [*meta, *pinned, *rest, *tail]


def _grid_columns(batch: Batch) -> list[str]:
    """표에 그릴 컬럼. `send_only`(판매조직 등)는 전송에만 들어가고 표에는 없다."""
    send_only = set(batch.grid.get("send_only") or [])
    return [c for c in batch.columns if c not in send_only]


def _column_config(batch: Batch) -> dict:
    """헤더는 `SAP 필드명 · 한글명`. 숨김 컬럼은 접어두되 전송에는 그대로 들어간다."""
    from ui.service import field_specs_for

    specs = field_specs_for(batch.customer)
    hidden = set(batch.grid.get("hidden") or [])
    widths = batch.grid.get("width") or {}           # 마스터가 정한 폭이 있으면 그걸 쓴다
    config: dict = {
        "#": st.column_config.NumberColumn("#", width=40),
        "파일": st.column_config.TextColumn("파일", width="medium"),
        "그룹": st.column_config.TextColumn("그룹", width=_fit("그룹")),
    }
    choices = choices_for(batch.customer)
    for name in _grid_columns(batch):
        label = str((specs.get(name) or {}).get("label") or name)
        help_text = f"{label} ({name})" + (
            " — 보기에서 접힌 컬럼. 전송에는 들어갑니다." if name in hidden else ""
        )
        header = f"{name} · {label}"
        if name in choices:
            config[name] = _choice_column(name, label, help_text, choices[name])
            continue
        config[name] = st.column_config.TextColumn(
            header, help=help_text, width=int(widths.get(name) or _fit(header)),
        )
    return config


def _fit(header: str) -> int:
    """열 폭 = 머리글 글자 폭. `small`·`medium` 은 짧은 머리글에도 넓어서 한 화면에
    보이는 열이 적었다. 한글은 영문의 두 배 가까이 넓다. 여백은 머리글 아이콘 몫."""
    text = sum(13 if ord(ch) >= 0x1100 else 7.5 for ch in header)
    return max(56, int(text) + 40)


def _choice_column(name: str, label: str, help_text: str, options: list[list[str]]):
    """후보가 여럿인 필드 — 드롭다운. 값은 코드, 보이는 글자는 `코드 · 이름`."""
    names = {o[0]: o[1] for o in options if len(o) > 1 and o[1]}
    header = f"▾ {name} · {label}"
    longest = max((f"{o[0]} · {o[1]}" if len(o) > 1 else o[0] for o in options), key=len)
    return st.column_config.SelectboxColumn(
        header,
        help=help_text + " — 후보 중에서 고릅니다.",
        options=[o[0] for o in options],
        format_func=lambda code: f"{code} · {names[code]}" if code in names else str(code),
        width=max(_fit(header), _fit(longest)),     # 고른 값("038 · HERTEL")이 잘리지 않게
    )


def _apply(batch: Batch, edited: pd.DataFrame, visible) -> None:
    """화면 값을 서버 스냅샷에 병합한다.

    **보이는 행만 보낸다.** 누락은 삭제가 아니므로(계약 §6.1) 필터로 가려진
    행은 그대로 남는다.
    """
    by_index = {index: row for index, row in enumerate(visible, start=1)}
    edits = []
    for record in edited.to_dict("records"):
        row = by_index.get(int(record["#"]))
        if row is None:
            continue
        fields = {k: str(v) if v is not None else "" for k, v in record.items() if k not in META}
        edits.append({"row_id": row.row_id, "fields": fields})

    rejected = merge_edits(batch, edits, settings())
    repo().save(batch)
    if rejected:
        st.error("이 배치에 없는 행입니다: " + ", ".join(rejected[:5]))


def _summary_bar(batch: Batch) -> None:
    info = summary(batch)
    cols = st.columns(4)
    cols[0].metric("행", info["row_count"])
    cols[1].metric("총 수량", info["total_qty"])
    cols[2].metric("오류", info["error_count"], delta=None,
                   delta_color="inverse" if info["error_count"] != "0" else "normal")
    cols[3].metric("경고", info["warn_count"])


def _issue_list(batch: Batch, issues_by_row: dict) -> None:
    """위에는 **묶은 요약**만, 행별 상세는 접어 둔다.

    행마다 같은 경고("브랜드 후보가 2개입니다")가 수십 줄 반복되면 전송 버튼까지
    한참 내려가야 했다. 같은 (필드·문구)는 한 줄로, 빈 칸 경고는 필드 목록 한 줄로
    합친다. 어떤 필드가 중요한지는 여기서 정하지 않는다 — 마스터의 `required` 가
    낸 경고를 묶기만 한다 (CLAUDE.md P2).
    """
    if not issues_by_row:
        st.success("검증을 통과했습니다.", icon="✅")
        return

    for severity, show in (("error", st.error), ("warn", st.warning)):
        lines = _grouped(issues_by_row, severity)
        if lines:
            show("\n\n".join(lines), icon="⛔" if severity == "error" else "⚠️")

    total = sum(len(issues) for _, issues in issues_by_row.values())
    with st.expander(f"행별 상세 {total}건", expanded=False):
        for index, (row, issues) in sorted(issues_by_row.items()):
            for issue in issues:
                icon = "⛔" if issue.severity == "error" else "⚠️"
                st.markdown(
                    f"{icon} **{index}행** ({row.file}) `{issue.field}` — {issue.message}"
                )


def _grouped(issues_by_row: dict, severity: str) -> list[str]:
    """(필드·문구)별로 몇 행인지. 빈 칸(REQUIRED_MISSING)은 필드 목록 한 줄로."""
    missing: dict[str, set[int]] = {}
    other: dict[tuple[str, str], set[int]] = {}
    for index, (_, issues) in issues_by_row.items():
        for issue in issues:
            if issue.severity != severity:
                continue
            if issue.code == "REQUIRED_MISSING":
                missing.setdefault(issue.field, set()).add(index)
            else:
                other.setdefault((issue.field, issue.message), set()).add(index)

    lines = [
        (f"`{field}` — " if field else "") + f"{message} (**{len(rows)}행**)"
        for (field, message), rows in other.items()
    ]
    if missing:
        fields = " · ".join(f"`{f}`({len(rows)}행)" for f, rows in missing.items())
        lines.append(f"빈 칸 있음: {fields} — 확인해 보세요")
    return lines


# ── ④ 전송 ───────────────────────────────────────────────────────────
def _send_section(batch: Batch) -> None:
    st.divider()
    live = batch.live_rows
    errors = sum(r.error_count for r in live)
    endpoint = settings().eai_endpoint

    if not endpoint:
        st.error(
            "`EAI_ENDPOINT` 가 설정되지 않아 전송할 수 없습니다. `.env` 를 확인하세요.",
            icon="🚫",
        )
        return
    if errors:
        st.error(f"오류 {errors}건을 먼저 해결해야 전송할 수 있습니다.", icon="⛔")
        return

    resend = batch.status == "SENT"
    label = "다시 전송" if resend else "SAP 으로 전송"
    st.caption(f"전송 대상 **{len(live)}행** → `{endpoint}`")
    if resend:
        st.warning(
            "이미 전송된 배치입니다. CBO 업서트 키가 아직 확정되지 않아 "
            "**중복 적재될 수 있습니다** (감사 로그에는 재전송으로 남습니다).",
            icon="⚠️",
        )

    if st.button(label, type="primary"):
        with st.spinner("전송 중…"):
            try:
                report = send_batch(batch, [], settings())
            except SendBlocked as exc:
                st.error(exc.message)
                return
        if report.status == "SENT":
            st.success(report.message, icon="✅")
            st.balloons()
        else:
            st.error(report.message, icon="✖")
        st.caption(f"시도 {report.attempts}회 · {report.sent_at or '-'}")
