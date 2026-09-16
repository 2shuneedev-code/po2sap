/** 화면 전환과 헬스 표시만. 업무 로직은 각 화면이 갖는다. */

import { useEffect, useState } from "react";
import { api } from "./api/client";
import type { Batch, Health } from "./api/types";
import { BrandConsole } from "./screens/BrandConsole";
import { ReviewScreen } from "./screens/ReviewScreen";
import { UploadScreen } from "./screens/UploadScreen";

type Tab = "work" | "brands";

export default function App() {
  const [tab, setTab] = useState<Tab>("work");
  const [batch, setBatch] = useState<Batch | null>(null);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <h1>PO2SAP</h1>
        <nav>
          <button
            aria-current={tab === "work"}
            onClick={() => { setTab("work"); }}
          >
            발주서 검수
          </button>
          <button aria-current={tab === "brands"} onClick={() => setTab("brands")}>
            브랜드 매핑
          </button>
        </nav>
        <span className="spacer" />
        <HealthChip health={health} />
      </header>

      {tab === "brands" ? (
        <BrandConsole />
      ) : batch ? (
        <ReviewScreen batch={batch} onBack={() => setBatch(null)} />
      ) : (
        <UploadScreen onReview={setBatch} />
      )}
    </div>
  );
}

/**
 * EAI 주소가 비어 있으면 눈에 띄게 알린다 — `.env` 를 깜빡한 채 검수를 끝까지
 * 하고 전송에서야 막히는 일을 막는다.
 */
function HealthChip({ health }: { health: Health | null }) {
  if (!health) return <span className="faint" style={{ fontSize: 12 }}>서버 확인 중…</span>;

  const problems: string[] = [];
  if (!health.masters.ok) problems.push("마스터");
  if (!health.llm.ok) problems.push("LLM");
  if (!health.eai_endpoint) problems.push("EAI 주소 미설정");

  return (
    <span
      className={problems.length ? "counter warn" : "counter ok"}
      title={`마스터: ${health.masters.detail}\nLLM: ${health.llm.provider} ${health.llm.detail}\nEAI: ${health.eai_endpoint || "(미설정)"}`}
    >
      {problems.length ? `⚠ ${problems.join(" · ")}` : `✔ ${health.llm.provider}`}
    </span>
  );
}
