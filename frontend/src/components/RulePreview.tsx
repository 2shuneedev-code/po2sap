/**
 * 화면 1-② "이 거래처에 자동 적용되는 값" — process.md §4 화면 1.
 *
 * ★ 이 컴포넌트에 **거래처별 분기가 하나도 없다.** `/preview` 응답을 모양
 * 그대로 그린다. 규칙이 YAML 에서 바뀌면 화면도 바뀐다 — 문서와 실동작이
 * 어긋날 자리를 아예 없앤 것이다 (CLAUDE.md P2).
 */

import type { Preview, RuleCard } from "../api/types";

/** `kind` 는 아이콘 하나 고르는 데만 쓴다. 모르는 kind 는 기본 아이콘. */
const ICON: Record<string, string> = {
  table: "▦",
  csv_map: "🔤",
  value_map: "🔤",
  keyword_map: "🔤",
  lookup: "🔎",
};

export function RulePreview({ preview }: { preview: Preview }) {
  const { fixed, rules, split, todos, footer } = preview;

  return (
    <div className="panel">
      {fixed.length > 0 && (
        <>
          <h3 style={{ margin: "0 0 8px", fontSize: 13 }}>고정값</h3>
          <div className="fixed-grid">
            {fixed.map((f) => (
              <div className="fixed-item" key={f.field}>
                <div className="k">
                  {f.label} <span className="mono faint">{f.field}</span>
                </div>
                <div className="v mono">{f.value}</div>
                {f.note && <div className="note">{f.note}</div>}
              </div>
            ))}
          </div>
        </>
      )}

      {rules.length > 0 && (
        <>
          <h3 style={{ margin: "18px 0 0", fontSize: 13 }}>자동 판별 규칙</h3>
          {rules.map((r) => (
            <RuleBlock key={r.id} rule={r} />
          ))}
        </>
      )}

      {split.by !== "none" && split.label && (
        <div className="callout info">
          <span>⑂</span>
          <span>
            <b>오더 분할</b> — {split.label}
          </span>
        </div>
      )}

      {todos.length > 0 && (
        <div className="callout warn">
          <span>⚠</span>
          <span>
            <b>확인 중인 값</b> —{" "}
            {todos.map((t, i) => (
              <span key={`${t.field}-${i}`}>
                {i > 0 && " · "}
                <span className="mono">{t.field}</span> ({t.note})
              </span>
            ))}
          </span>
        </div>
      )}

      {footer && <p className="muted" style={{ margin: "12px 0 0", fontSize: 13 }}>{footer}</p>}
    </div>
  );
}

function RuleBlock({ rule }: { rule: RuleCard }) {
  const hasTable = rule.columns.length > 0 && rule.rows.length > 0;

  return (
    <section className="rule-card">
      <header>
        <span aria-hidden="true">{ICON[rule.kind] ?? "•"}</span>
        <b>{rule.label}</b>
        <span className="kind">{rule.kind}</span>
      </header>
      <div className="body">
        {rule.note && <p className="note">{rule.note}</p>}
        {hasTable ? (
          <div className="scroll-y">
            <table className="matrix">
              <thead>
                <tr>
                  {rule.columns.map((c, i) => (
                    <th key={i}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rule.rows.map((row, i) => (
                  <tr key={i}>
                    {rule.columns.map((_, j) => (
                      <td key={j} className={j > 0 ? "mono" : undefined}>
                        {row[j] ?? ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          !rule.note && <p className="faint" style={{ margin: 0, fontSize: 13 }}>표시할 표가 없습니다.</p>
        )}
        {rule.rows.length > 12 && (
          <p className="faint" style={{ margin: "6px 0 0", fontSize: 12 }}>
            {rule.rows.length}건 — 위에서부터 순서대로 확인합니다.
          </p>
        )}
      </div>
    </section>
  );
}
