/**
 * 브랜드 매핑 콘솔 — contracts/api-contract.md §10.
 *
 * 왼쪽에서 고객을 고르면 **그 고객의 브랜드**와 **적용 로직**이 함께 보인다.
 * 대상은 규칙이 설정된 거래처가 아니라 SAP 브랜드 마스터의 **전 고객**이다 —
 * 규칙이 아직 없는 고객도 원문 키부터 채워둘 수 있어야 하기 때문이다.
 *
 * 편집 대상은 `brand_keys.csv` 하나뿐이다. 코드·이름은 SAP 원본이라 읽기 전용.
 */

import { useEffect, useMemo, useState } from "react";
import { ApiFailure, api } from "../api/client";
import type { BrandCustomer, BrandDetail, BrandKey, BrandRow } from "../api/types";

type Filter = "all" | "configured" | "unconfigured";

export function BrandConsole() {
  const [list, setList] = useState<BrandCustomer[]>([]);
  const [total, setTotal] = useState("0");
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [kunnr, setKunnr] = useState("");
  const [detail, setDetail] = useState<BrandDetail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"brands" | "logic">("brands");

  // 검색어 디바운스 — 타이핑마다 430행을 훑지 않는다
  const [query, setQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQuery(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    api
      .brandCustomers({ q: query, filter, limit: 500 })
      .then((r) => { setList(r.customers); setTotal(r.total); })
      .catch((e: ApiFailure) => setError(e.message));
  }, [query, filter]);

  useEffect(() => {
    if (!kunnr) return setDetail(null);
    let alive = true;
    api
      .brandDetail(kunnr)
      .then((d) => alive && setDetail(d))
      .catch((e: ApiFailure) => alive && setError(e.message));
    return () => { alive = false; };
  }, [kunnr]);

  async function saveKeys(zbrand: string, keys: BrandKey[]) {
    if (!detail) return;
    try {
      const saved = await api.saveBrandKeys(detail.kunnr, zbrand, keys);
      setDetail((d) =>
        d && {
          ...d,
          brands: d.brands.map((b) =>
            b.zbrand === zbrand ? { ...b, keys: saved.keys, status: saved.status } : b),
        },
      );
      setError("");
    } catch (e) {
      // 거부 사유(중복 문구 · 미등록 코드)를 그대로 띄운다. 파일은 안 바뀌었다.
      setError(e instanceof ApiFailure ? e.message : String(e));
    }
  }

  return (
    <div className="page wide">
      {error && <div className="callout error">⛔ {error}</div>}

      <div className="console">
        <div className="panel" style={{ padding: 0 }}>
          <div style={{ padding: 12, borderBottom: "1px solid var(--line)" }}>
            <input
              type="search"
              placeholder="고객명 · 고객코드 검색"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ width: "100%", marginBottom: 8 }}
            />
            <div style={{ display: "flex", gap: 6 }}>
              {(["all", "configured", "unconfigured"] as Filter[]).map((f) => (
                <button
                  key={f}
                  className="ghost"
                  aria-current={filter === f}
                  style={filter === f ? { background: "var(--accent-soft)", color: "var(--accent)" } : undefined}
                  onClick={() => setFilter(f)}
                >
                  {f === "all" ? "전체" : f === "configured" ? "규칙 있음" : "규칙 없음"}
                </button>
              ))}
            </div>
            <p className="faint" style={{ margin: "8px 0 0", fontSize: 12 }}>
              {list.length} / {total}곳
            </p>
          </div>
          <ul className="cust-list">
            {list.map((c) => (
              <li key={c.kunnr}>
                <button aria-current={c.kunnr === kunnr} onClick={() => setKunnr(c.kunnr)}>
                  <div className="nm">{c.name}</div>
                  <div className="sub">
                    <span className="mono">{c.kunnr}</span>
                    {c.code && <span className="badge on">{c.code}</span>}
                    <span>브랜드 {c.mapped_count}/{c.brand_count}</span>
                  </div>
                </button>
              </li>
            ))}
            {!list.length && <li><p className="empty">해당하는 고객이 없습니다.</p></li>}
          </ul>
        </div>

        <div className="panel">
          {!detail ? (
            <p className="empty">왼쪽에서 고객을 선택하세요.</p>
          ) : (
            <>
              <header style={{ marginBottom: 12 }}>
                <h2 style={{ margin: 0, fontSize: 18 }}>
                  {detail.name}{" "}
                  <span className="mono faint" style={{ fontSize: 13 }}>{detail.kunnr}</span>
                </h2>
                <div className="muted" style={{ fontSize: 13 }}>
                  SAP 명 {detail.sap_name}
                  {detail.code && <> · 거래처 <b>{detail.code}</b></>}
                  {detail.file_types.length > 0 && <> · {detail.file_types.join("/").toUpperCase()}</>}
                </div>
              </header>

              <div className="tabs">
                <button aria-current={tab === "brands"} onClick={() => setTab("brands")}>
                  브랜드 매핑 ({detail.brands.length})
                </button>
                <button aria-current={tab === "logic"} onClick={() => setTab("logic")}>
                  적용 로직
                </button>
              </div>

              {tab === "brands" ? (
                <BrandTable brands={detail.brands} onSave={saveKeys} />
              ) : (
                <LogicPanel detail={detail} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 브랜드 표 ────────────────────────────────────────────────────────
function BrandTable(props: {
  brands: BrandRow[];
  onSave: (zbrand: string, keys: BrandKey[]) => void;
}) {
  const [onlyUnmapped, setOnlyUnmapped] = useState(false);
  const shown = useMemo(
    () => (onlyUnmapped ? props.brands.filter((b) => b.status === "unmapped") : props.brands),
    [props.brands, onlyUnmapped],
  );

  return (
    <>
      <label className="muted" style={{ display: "block", marginBottom: 8, fontSize: 13 }}>
        <input
          type="checkbox"
          checked={onlyUnmapped}
          onChange={(e) => setOnlyUnmapped(e.target.checked)}
        />{" "}
        미매핑만 보기
      </label>
      <p className="faint" style={{ fontSize: 12, marginTop: 0 }}>
        코드·이름은 SAP 원본이라 고칠 수 없습니다. 채우는 것은 <b>발주서 원문 문구</b>뿐입니다.
        같은 줄에 여러 개를 두면 <b>위에서부터 순서대로</b> 판정합니다.
      </p>
      <div className="scroll-y" style={{ maxHeight: "60vh" }}>
        <table className="matrix">
          <thead>
            <tr>
              <th style={{ width: 70 }}>코드</th>
              <th style={{ width: 200 }}>브랜드명 (SAP)</th>
              <th>발주서 원문 문구</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((b) => (
              <tr key={b.zbrand}>
                <td className="mono">{b.zbrand}</td>
                <td>{b.name}</td>
                <td>
                  <KeyEditor keys={b.keys} onSave={(keys) => props.onSave(b.zbrand, keys)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function KeyEditor(props: { keys: BrandKey[]; onSave: (keys: BrandKey[]) => void }) {
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<"contains" | "equals">("contains");

  function add() {
    const text = draft.trim();
    if (!text) return;
    props.onSave([...props.keys, { text, match: mode, note: "" }]);
    setDraft("");
  }

  return (
    <div className="keys">
      {props.keys.map((k, i) => (
        <span className={k.match === "equals" ? "chip equals" : "chip"} key={`${k.text}-${i}`}>
          <span title={k.match === "equals" ? "완전일치" : "포함"}>{k.text}</span>
          <button
            title="삭제"
            onClick={() => props.onSave(props.keys.filter((_, j) => j !== i))}
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        placeholder="원문 문구 추가"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && add()}
        style={{ width: 150, padding: "3px 8px", fontSize: 12 }}
      />
      <select
        value={mode}
        onChange={(e) => setMode(e.target.value as "contains" | "equals")}
        style={{ padding: "3px 6px", fontSize: 12 }}
      >
        <option value="contains">포함</option>
        <option value="equals">완전일치</option>
      </select>
      <button onClick={add} disabled={!draft.trim()} style={{ padding: "3px 10px", fontSize: 12 }}>
        추가
      </button>
    </div>
  );
}

// ── 적용 로직 패널 ───────────────────────────────────────────────────
function LogicPanel({ detail }: { detail: BrandDetail }) {
  if (!detail.logic) {
    return (
      <div className="callout info">
        <span>ⓘ</span>
        <span>
          이 고객은 아직 <b>규칙이 설정되지 않았습니다.</b> 브랜드 원문 문구는 미리
          채워둘 수 있고, 규칙은 <span className="mono">masters/customers/</span> 에
          파일을 추가하면 여기에 나타납니다.
        </span>
      </div>
    );
  }

  const { split, tables, rules, fields, checks } = detail.logic;

  return (
    <div>
      {split.by !== "none" && split.label && (
        <div className="callout info">⑂ <b>오더 분할</b> — {split.label}</div>
      )}

      {tables.map((t) => (
        <section className="rule-card" key={t.id}>
          <header>
            <span aria-hidden="true">▦</span>
            <b>{t.label}</b>
            {t.scope && <span className="kind">{t.scope}</span>}
          </header>
          <div className="body">
            <Matrix columns={t.columns} rows={t.rows} />
            {t.on_no_match && (
              <p className="faint" style={{ fontSize: 12, margin: "6px 0 0" }}>
                해당 없음 → {t.on_no_match.action}: {t.on_no_match.message}
              </p>
            )}
          </div>
        </section>
      ))}

      {rules.map((r) => (
        <section className="rule-card" key={r.id}>
          <header>
            <span aria-hidden="true">🔤</span>
            <b>{r.label}</b>
            <span className="kind">{r.kind}</span>
          </header>
          <div className="body">
            {r.note && <p className="note">{r.note}</p>}
            {r.columns.length > 0
              ? <Matrix columns={r.columns} rows={r.rows} />
              : <p className="faint" style={{ margin: 0, fontSize: 12 }}>
                  판정 내용은 위 <b>브랜드 매핑</b> 탭의 표 그대로입니다.
                </p>}
            {r.on_no_match && (
              <p className="faint" style={{ fontSize: 12, margin: "6px 0 0" }}>
                해당 없음 → {r.on_no_match.action}: {r.on_no_match.message}
              </p>
            )}
          </div>
        </section>
      ))}

      {fields.length > 0 && (
        <section className="rule-card">
          <header><span aria-hidden="true">≡</span><b>전송 필드 산출</b></header>
          <div className="body">
            <table className="matrix">
              <thead>
                <tr><th>필드</th><th>설명</th><th>산출식</th></tr>
              </thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={f.field}>
                    <td>
                      <span className="mono">{f.field}</span>
                      <div className="faint" style={{ fontSize: 11 }}>{f.label}</div>
                    </td>
                    <td>
                      {f.explain || <span className="faint">—</span>}
                      {f.todo && <div style={{ color: "var(--warn)", fontSize: 12 }}>⚠ {f.todo}</div>}
                    </td>
                    <td className="mono" style={{ fontSize: 12 }}>{f.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {checks.length > 0 && (
        <section className="rule-card">
          <header><span aria-hidden="true">✓</span><b>검증</b></header>
          <div className="body">
            {checks.map((c) => (
              <p key={c.id} style={{ margin: "0 0 6px" }}>
                {c.severity === "error" ? "⛔" : "⚠"} <b>{c.label}</b>
                <span className="faint"> — {c.description}</span>
              </p>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Matrix({ columns, rows }: { columns: string[]; rows: string[][] }) {
  if (!columns.length || !rows.length) return null;
  return (
    <div className="scroll-y">
      <table className="matrix">
        <thead>
          <tr>{columns.map((c, i) => <th key={i}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((_, j) => (
                <td key={j} className={j > 0 ? "mono" : undefined}>{row[j] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
