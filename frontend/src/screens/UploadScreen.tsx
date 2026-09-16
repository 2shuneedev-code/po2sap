/**
 * 화면 1 — 거래처 선택 + 규칙 미리보기 + 업로드 (process.md §4 화면 1).
 *
 * 거래처를 **먼저** 고르게 해서 자동판별 오판 리스크를 원천 제거한다.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { ApiFailure, api } from "../api/client";
import type { Batch, Customer, Preview } from "../api/types";
import { RulePreview } from "../components/RulePreview";

interface Props {
  onReview: (batch: Batch) => void;
}

export function UploadScreen({ onReview }: Props) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [error, setError] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.customers().then(setCustomers).catch((e: ApiFailure) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return setPreview(null);
    let alive = true;
    api
      .preview(selected)
      .then((p) => alive && setPreview(p))
      .catch((e: ApiFailure) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [selected]);

  // 파싱 중이면 1.5초 폴링 (계약 §5)
  useEffect(() => {
    if (!batch || batch.status !== "PARSING") return;
    const timer = setTimeout(() => {
      api.batch(batch.batch_id).then(setBatch).catch(() => undefined);
    }, 1500);
    return () => clearTimeout(timer);
  }, [batch]);

  const current = customers.find((c) => c.code === selected);

  /** file_types 는 **안내용**이다. 다른 형식이어도 막지 않고 경고만 한다 (계약 §1). */
  const formatWarning = useMemo(() => {
    if (!batch || !current?.file_types.length) return "";
    const odd = batch.files
      .map((f) => f.name)
      .filter((n) => {
        const ext = n.split(".").pop()?.toLowerCase() ?? "";
        return !current.file_types.includes(ext);
      });
    return odd.length
      ? `${odd.join(", ")} — 이 거래처는 보통 ${current.file_types.join("/").toUpperCase()} 로 보냅니다. 그대로 읽어봅니다.`
      : "";
  }, [batch, current]);

  function pick(code: string) {
    if (batch && code !== selected) {
      if (!confirm("거래처를 바꾸면 업로드한 파일이 초기화됩니다. 계속할까요?")) return;
      setBatch(null);
    }
    setSelected(code);
    setError("");
  }

  async function upload(files: File[]) {
    if (!selected || !files.length) return;
    setBusy(true);
    setError("");
    try {
      setBatch(await api.upload(selected, files));
    } catch (e) {
      setError(e instanceof ApiFailure ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const parsedRows = batch?.files.reduce((n, f) => n + Number(f.row_count ?? 0), 0) ?? 0;
  const canReview = !!batch && batch.status !== "PARSING" && parsedRows > 0;

  return (
    <div className="page">
      {error && <div className="callout error">⛔ {error}</div>}

      <section className="section">
        <h2><span className="step">1</span>거래처 선택</h2>
        <div className="customers">
          {customers.map((c) => (
            <button
              key={c.code}
              className="customer-card"
              aria-pressed={c.code === selected}
              onClick={() => pick(c.code)}
            >
              <div className="code">{c.code}</div>
              <div className="no">{c.customer_no}</div>
              <div className="types">{c.file_types.join(" · ") || "—"}</div>
            </button>
          ))}
          {!customers.length && <p className="faint">거래처를 불러오는 중…</p>}
        </div>
      </section>

      {preview && (
        <section className="section">
          <h2><span className="step">2</span>이 거래처에 자동 적용되는 값</h2>
          <RulePreview preview={preview} />
        </section>
      )}

      {selected && (
        <section className="section">
          <h2><span className="step">3</span>발주서 업로드</h2>
          <div
            className={over ? "dropzone over" : "dropzone"}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              void upload([...e.dataTransfer.files]);
            }}
          >
            <div className="big">📄 {selected} 발주서를 여기에 끌어다 놓으세요</div>
            <div className="faint" style={{ marginBottom: 12 }}>
              {(current?.file_types.join(" · ").toUpperCase() || "PDF · HTM")} · 여러 개 동시 가능
            </div>
            <button onClick={() => fileInput.current?.click()} disabled={busy}>
              {busy ? "업로드 중…" : "파일 선택"}
            </button>
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              onChange={(e) => {
                void upload([...(e.target.files ?? [])]);
                e.target.value = "";
              }}
            />
          </div>

          {formatWarning && <div className="callout warn">⚠ {formatWarning}</div>}

          {batch && (
            <>
              <ul className="file-list">
                {batch.files.map((f) => (
                  <li key={f.file_id}>
                    <span aria-hidden="true">📄</span>
                    <span className="name">{f.name}</span>
                    {f.status === "DONE" && (
                      <span className="state done">✔ 파싱완료 {f.row_count ?? 0}행</span>
                    )}
                    {f.status === "FAILED" && (
                      <span className="state failed">✖ {f.error || "파싱 실패"}</span>
                    )}
                    {f.status !== "DONE" && f.status !== "FAILED" && (
                      <span className="state parsing">⏳ 파싱중…</span>
                    )}
                  </li>
                ))}
              </ul>
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
                <button className="primary" disabled={!canReview} onClick={() => onReview(batch)}>
                  검수하기 ▶
                </button>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
