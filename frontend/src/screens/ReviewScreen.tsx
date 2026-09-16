/**
 * 화면 2 — 통합 검수 (process.md §4 화면 2). 1행 = 1품목, 전송 필드 전 컬럼.
 *
 * 값의 주인은 **프론트**다 (계약 §6). 재검증 응답은 `issues`/`edited` 만
 * 반영하고 값은 건드리지 않는다 — 검수자가 입력하는 도중에 서버 응답이
 * 도착해 타이핑이 사라지는 일을 막는다.
 *
 * 반대로 **무엇이 바뀌었는지 판단하는 쪽은 서버**다 (계약 §6.1). `edited` 를
 * 프론트가 계산하지 않는다.
 */

import type { CellClassParams, ColDef, GetRowIdParams, RowClassParams } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import { ApiFailure, api } from "../api/client";
import type { Batch, FieldSpec, Issue, Row, RowEdit, SendResult } from "../api/types";

const ALL = "__all__";

interface Props {
  batch: Batch;
  onBack: () => void;
}

export function ReviewScreen({ batch: initial, onBack }: Props) {
  const [batch, setBatch] = useState<Batch>(initial);
  const [rows, setRows] = useState<Row[]>(initial.rows);
  const [fieldSpecs, setFieldSpecs] = useState<Record<string, FieldSpec>>({});
  const [fileFilter, setFileFilter] = useState(ALL);
  const [groupFilter, setGroupFilter] = useState(ALL);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<SendResult | null>(null);
  const [sending, setSending] = useState(false);
  const gridRef = useRef<AgGridReact<Row>>(null);

  useEffect(() => {
    api.fields()
      .then((r) => setFieldSpecs(Object.fromEntries(r.fields.map((f) => [f.name, f]))))
      .catch(() => undefined);
  }, []);

  // ── 컬럼: columns 응답이 곧 목록이다. 개수를 세지 않는다 ────────────
  const columnDefs = useMemo<ColDef<Row>[]>(() => {
    const meta: ColDef<Row>[] = [
      {
        // `_line_no` 는 **출하처 안에서의** 품목 번호라 한 그리드에 1이 여러 번 나온다.
        // 이슈 목록이 "1행"을 두 번 가리키면 검수자가 어느 행인지 알 수 없다.
        // 화면 번호는 그리드에서의 순번으로 매긴다 (process.md 화면 2).
        headerName: "#",
        valueGetter: (p) => (p.node?.rowIndex ?? 0) + 1,
        width: 62,
        pinned: "left",
      },
      { headerName: "파일", field: "_file", width: 150, pinned: "left" },
      { headerName: "그룹", field: "_group", width: 110, pinned: "left" },
    ];

    const data: ColDef<Row>[] = batch.columns.map((name) => {
      const spec = fieldSpecs[name];
      return {
        colId: name,
        // SAP 필드명 + 한글명 2줄 (process.md §4.2.1). 한글명은 /api/masters/fields.
        headerName: name,
        headerTooltip: spec?.label ? `${name} · ${spec.label}` : name,
        headerComponentParams: { label: spec?.label ?? "" },
        headerComponent: TwoLineHeader,
        valueGetter: (p) => p.data?.fields[name] ?? "",
        valueSetter: (p) => {
          if (!p.data) return false;
          const next = String(p.newValue ?? "");
          if (p.data.fields[name] === next) return false;
          p.data.fields[name] = next;
          return true;
        },
        width: batch.grid.width?.[name] ?? 130,
        hide: batch.grid.hidden?.includes(name) ?? false,
        pinned: batch.grid.pinned?.includes(name) ? ("left" as const) : undefined,
        editable: (p) => !p.data?._deleted,
        cellClass: (p: CellClassParams<Row>) => {
          const row = p.data;
          if (!row) return "";
          const issue = row.issues.find((i) => i.field === name);
          if (issue) return issue.severity === "error" ? "cell-error" : "cell-warn";
          return row.edited.includes(name) ? "cell-edited" : "";
        },
        tooltipValueGetter: (p) =>
          p.data?.issues.find((i) => i.field === name)?.message ?? undefined,
      };
    });

    return [...meta, ...data];
  }, [batch.columns, batch.grid, fieldSpecs]);

  // ── 필터 ────────────────────────────────────────────────────────────
  const files = useMemo(
    () => [...new Set(rows.map((r) => r._file))].filter(Boolean),
    [rows],
  );
  const groups = useMemo(
    () => [...new Set(rows.map((r) => r._group))].filter(Boolean),
    [rows],
  );
  const visible = useMemo(
    () =>
      rows.filter(
        (r) =>
          (fileFilter === ALL || r._file === fileFilter) &&
          (groupFilter === ALL || r._group === groupFilter),
      ),
    [rows, fileFilter, groupFilter],
  );

  // ── 합계 바 — 화면에 보이는 것만 센다 ───────────────────────────────
  const live = useMemo(() => {
    const active = visible.filter((r) => !r._deleted);
    const qty = active.reduce((sum, r) => sum + (Number(r.fields.KWMENG) || 0), 0);
    const errors = active.reduce(
      (n, r) => n + r.issues.filter((i) => i.severity === "error").length, 0);
    const warns = active.reduce(
      (n, r) => n + r.issues.filter((i) => i.severity === "warn").length, 0);
    return { count: active.length, qty, errors, warns };
  }, [visible]);

  const issueList = useMemo(
    () =>
      visible
        .filter((r) => !r._deleted)
        .flatMap((r, idx) => r.issues.map((i) => ({ row: r, issue: i, no: idx + 1 })))
        .sort((a, b) => (a.issue.severity === b.issue.severity ? 0
          : a.issue.severity === "error" ? -1 : 1)),
    [visible],
  );

  // ── 서버에 보낼 편집분. 누락은 삭제가 아니므로 전 행을 보낸다 ────────
  const asEdits = useCallback(
    (): RowEdit[] =>
      rows.map((r) => ({ row_id: r.row_id, fields: r.fields, deleted: !!r._deleted })),
    [rows],
  );

  /** 값은 그대로 두고 판정만 갈아끼운다 (계약 §6). */
  const revalidate = useCallback(async () => {
    try {
      const res = await api.validate(batch.batch_id, asEdits());
      const by = new Map(res.rows.map((r) => [r.row_id, r]));
      setRows((prev) =>
        prev.map((r) => {
          const got = by.get(r.row_id);
          return got ? { ...r, issues: got.issues, edited: got.edited } : r;
        }),
      );
      setBatch((b) => ({ ...b, status: res.status, summary: res.summary }));
      setError("");
    } catch (e) {
      setError(e instanceof ApiFailure ? e.message : String(e));
    }
  }, [batch.batch_id, asEdits]);

  // 편집이 멈추면 재검증 (디바운스)
  const [dirty, setDirty] = useState(0);
  useEffect(() => {
    if (!dirty) return;
    const t = setTimeout(() => void revalidate(), 600);
    return () => clearTimeout(t);
  }, [dirty, revalidate]);

  function toggleDeleted(rowId: string) {
    setRows((prev) =>
      prev.map((r) => (r.row_id === rowId ? { ...r, _deleted: !r._deleted } : r)));
    setDirty((n) => n + 1);
  }

  /** 열 일괄 채우기 — 적용 범위는 현재 필터를 따른다 (process.md §4.2.2). */
  function fillColumn(field: string) {
    const scope =
      fileFilter !== ALL || groupFilter !== ALL ? "현재 필터에 보이는 행" : "전체 행";
    const value = prompt(`${field} — ${scope} ${visible.length}건에 채울 값`);
    if (value === null) return;
    const ids = new Set(visible.map((r) => r.row_id));
    setRows((prev) =>
      prev.map((r) =>
        ids.has(r.row_id) && !r._deleted
          ? { ...r, fields: { ...r.fields, [field]: value } }
          : r,
      ),
    );
    setDirty((n) => n + 1);
  }

  function focusIssue(rowId: string, field: string) {
    const api_ = gridRef.current?.api;
    if (!api_) return;
    const node = api_.getRowNode(rowId);
    if (node?.rowIndex == null) return;
    api_.ensureIndexVisible(node.rowIndex, "middle");
    api_.ensureColumnVisible(field);
    api_.setFocusedCell(node.rowIndex, field);
  }

  async function send() {
    setSending(true);
    try {
      setResult(await api.send(batch.batch_id, asEdits()));
      setConfirming(false);
    } catch (e) {
      setError(e instanceof ApiFailure ? e.message : String(e));
      setConfirming(false);
    } finally {
      setSending(false);
    }
  }

  const blocked = live.errors > 0;

  return (
    <div className="review">
      <div className="review-bar">
        <button className="ghost" onClick={onBack}>← 뒤로</button>
        <b>{batch.customer}</b>
        <span className="muted">
          파일 {batch.files.length}개 · {live.count}행 · {live.qty.toLocaleString()} EA
        </span>
        <span className="spacer" />
        {live.errors > 0 && <span className="counter error">⛔ 오류 {live.errors}</span>}
        {live.warns > 0 && <span className="counter warn">⚠ 경고 {live.warns}</span>}
        {!blocked && <span className="counter ok">✔ 전송 가능</span>}
        <button className="primary" disabled={blocked || sending} onClick={() => setConfirming(true)}>
          전체 전송 ▶
        </button>
      </div>

      <div className="review-bar" style={{ borderTop: 0 }}>
        <label className="muted">
          파일{" "}
          <select value={fileFilter} onChange={(e) => setFileFilter(e.target.value)}>
            <option value={ALL}>전체</option>
            {files.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        {groups.length > 0 && (
          <label className="muted">
            그룹{" "}
            <select value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}>
              <option value={ALL}>전체</option>
              {groups.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </label>
        )}
        <label className="muted">
          열 일괄채우기{" "}
          <select
            value=""
            onChange={(e) => { if (e.target.value) fillColumn(e.target.value); e.target.value = ""; }}
          >
            <option value="">컬럼 선택…</option>
            {batch.columns.map((name) => (
              <option key={name} value={name}>
                {name}{fieldSpecs[name]?.label ? ` · ${fieldSpecs[name]!.label}` : ""}
              </option>
            ))}
          </select>
        </label>
        <span className="faint" style={{ fontSize: 12 }}>
          행을 우클릭하면 전송에서 뺍니다
        </span>
        <span className="spacer" />
        <button className="ghost" onClick={() => void revalidate()}>재검증</button>
      </div>

      {error && <div className="callout error" style={{ margin: "8px 20px" }}>⛔ {error}</div>}

      <div className="grid-wrap ag-theme-quartz ag-theme-po2sap">
        <AgGridReact<Row>
          ref={gridRef}
          rowData={visible}
          columnDefs={columnDefs}
          getRowId={(p: GetRowIdParams<Row>) => p.data.row_id}
          defaultColDef={{ resizable: true, sortable: false, editable: true, minWidth: 80 }}
          enableCellTextSelection
          tooltipShowDelay={200}
          stopEditingWhenCellsLoseFocus
          undoRedoCellEditing
          undoRedoCellEditingLimit={50}
          rowClassRules={{
            "row-deleted": (p: RowClassParams<Row>) => !!p.data?._deleted,
          }}
          onCellValueChanged={() => setDirty((n) => n + 1)}
          onCellContextMenu={(e) => {
            e.event?.preventDefault();
            const no = (e.node?.rowIndex ?? 0) + 1;
            if (e.data && confirm(`${no}행을 전송에서 ${e.data._deleted ? "다시 포함" : "제외"}할까요?`)) {
              toggleDeleted(e.data.row_id);
            }
          }}
          domLayout="normal"
        />
      </div>

      {issueList.length > 0 && (
        <div className="issue-panel">
          <ul>
            {issueList.map(({ row, issue, no }, i) => (
              <li key={`${row.row_id}-${issue.field}-${i}`}
                  onClick={() => focusIssue(row.row_id, issue.field)}>
                <span>{issue.severity === "error" ? "⛔" : "⚠"}</span>
                <span className="where">
                  {no}행 ({row._file}) <span className="mono">{issue.field}</span>
                </span>
                <span>{issue.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {confirming && (
        <SendConfirm
          rows={live.count}
          qty={live.qty}
          warns={live.warns}
          sending={sending}
          onCancel={() => setConfirming(false)}
          onSend={() => void send()}
        />
      )}
      {result && <SendResultModal result={result} onClose={() => setResult(null)} onBack={onBack} />}
    </div>
  );
}

/** SAP 필드명 위, 한글명 아래. 현업은 한글명으로, 개발·SAP 담당은 코드로 읽는다. */
function TwoLineHeader(props: { displayName: string; label?: string }) {
  return (
    <div style={{ lineHeight: 1.25, padding: "2px 0" }}>
      <div style={{ fontWeight: 600 }}>{props.displayName}</div>
      <div style={{ fontSize: 11, color: "var(--ink-faint)", fontWeight: 400 }}>
        {props.label || "\u00a0"}
      </div>
    </div>
  );
}

// ── 화면 3 — 전송 확인 → 결과 ────────────────────────────────────────
function SendConfirm(props: {
  rows: number; qty: number; warns: number; sending: boolean;
  onCancel: () => void; onSend: () => void;
}) {
  return (
    <div className="backdrop" onClick={props.onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>전송 확인</h3>
        <p>
          <b>{props.rows}행</b> · 총 {props.qty.toLocaleString()} EA 를 EAI 로 보냅니다.
        </p>
        {props.warns > 0 && (
          <div className="callout warn">
            ⚠ 경고 {props.warns}건이 남아 있습니다. 경고는 전송을 막지 않습니다.
          </div>
        )}
        <div className="actions">
          <button onClick={props.onCancel} disabled={props.sending}>취소</button>
          <button className="primary" onClick={props.onSend} disabled={props.sending}>
            {props.sending ? "전송 중…" : "전송"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SendResultModal(props: { result: SendResult; onClose: () => void; onBack: () => void }) {
  const ok = props.result.status === "SENT";
  return (
    <div className="backdrop">
      <div className="modal">
        <h3>{ok ? "✔ 전송 완료" : "✖ 전송 실패"}</h3>
        <p>{props.result.message}</p>
        <p className="muted">
          전송 행 {String(props.result.sent_rows)}
          {props.result.attempts ? ` · 시도 ${props.result.attempts}회` : ""}
          {props.result.resend ? " · 재전송" : ""}
        </p>
        {!ok && (
          <div className="callout warn">
            같은 화면에서 다시 전송할 수 있습니다. 4xx 오류는 재시도해도 같은 이유로 거부됩니다.
          </div>
        )}
        <div className="actions">
          <button onClick={props.onClose}>화면으로</button>
          {ok && <button className="primary" onClick={props.onBack}>새 발주서</button>}
        </div>
      </div>
    </div>
  );
}

export type { Issue };
