/**
 * 브라우저가 실제로 그리는지 확인한다 — 타입체크와 빌드는 화면이 뜨는 증거가 아니다.
 *
 * 전제: 백엔드(:8000) · vite(:5173) · 모의 EAI(:9000) 가 떠 있어야 한다.
 *   터미널 1  LLM_PROVIDER=mock EAI_ENDPOINT=http://127.0.0.1:9000/po2sap/order \
 *             uvicorn backend.app.main:app --port 8000
 *   터미널 2  python scripts/mock_eai_server.py
 *   터미널 3  cd frontend && npm run dev
 *   터미널 4  cd frontend && npm run e2e
 *
 * LLM 호출 없음(mock 재생) = 비용 0.
 */
import { chromium } from "playwright";

const SHOT = process.env.SHOT_DIR ?? "e2e/shots";
const errors = [];
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(`PAGEERROR: ${e.message}`));
page.on("response", (r) => { if (r.status() >= 400) console.log("  !! HTTP", r.status(), r.url()); });

function step(n) { console.log(`\n── ${n}`); }

await page.goto("http://localhost:5173", { waitUntil: "networkidle" });

step("화면 1 — 거래처 카드");
await page.waitForSelector(".customer-card", { timeout: 10000 });
const codes = await page.$$eval(".customer-card .code", (n) => n.map((e) => e.textContent));
console.log("거래처:", codes.join(", "));

step("MSC 선택 → 규칙 카드");
await page.getByRole("button", { name: /MSC/ }).click();
await page.waitForSelector(".rule-card", { timeout: 10000 });
const fixed = await page.$$eval(".fixed-item .k", (n) => n.map((e) => e.textContent.trim()));
const rules = await page.$$eval(".rule-card header b", (n) => n.map((e) => e.textContent));
console.log("고정값:", fixed.join(" | "));
console.log("규칙 카드:", rules.join(" | "));
console.log("분할 안내:", await page.locator(".callout.info").first().textContent().catch(() => "(없음)"));
await page.screenshot({ path: `${SHOT}/01-upload.png`, fullPage: true });

step("업로드");
await page.setInputFiles('input[type="file"]', "../backend/tests/fixtures/msc/PO-SAMPLE-0001.htm");
await page.waitForSelector(".file-list li", { timeout: 15000 });
await page.waitForFunction(() => document.querySelector(".state.done") !== null, { timeout: 20000 });
console.log("파일 상태:", await page.locator(".file-list li").first().textContent());

step("검수 화면");
await page.getByRole("button", { name: /검수하기/ }).click();
await page.waitForSelector(".ag-center-cols-container .ag-row", { timeout: 15000 });
const rowCount = await page.locator(".ag-center-cols-container .ag-row").count();
console.log("그리드 행:", rowCount);
// col-id 로 센다. 헤더 텍스트 노드는 커스텀 헤더에서 사라져 실제 컬럼 수를 못 센다.
const headers = await page.$$eval(".ag-header-cell[col-id]", (n) =>
  n.map((e) => e.getAttribute("col-id")));
console.log("표시 컬럼:", headers.length, "→", headers.slice(0, 10).join(", "));
const hiddenLeak = headers.filter((h) => ["VTWEG", "VBELN", "MAKTX"].includes(h));
console.log("숨김 컬럼 노출:", hiddenLeak.length ? hiddenLeak : "없음 (정상)");
console.log("상단바:", (await page.locator(".review-bar").first().textContent()).replace(/\s+/g, " "));
await page.screenshot({ path: `${SHOT}/02-review.png`, fullPage: false });

step("셀 편집 → 재검증 → 오류 표시");
const cell = page.locator(`.ag-row[row-id="r_0001"] [col-id="MATNR"]`).first();
await cell.dblclick();
await page.keyboard.press("Control+A");
await page.keyboard.press("Delete");
await page.keyboard.press("Enter");
await page.waitForSelector(".issue-panel li", { timeout: 10000 });
console.log("이슈:", (await page.locator(".issue-panel li").first().textContent()).replace(/\s+/g, " "));
console.log("오류 카운터:", await page.locator(".counter.error").textContent().catch(() => "(없음)"));
const blocked = await page.getByRole("button", { name: /전체 전송/ }).isDisabled();
console.log("전송 버튼 차단됨:", blocked);
await page.screenshot({ path: `${SHOT}/03-error.png`, fullPage: false });

step("값 복구 → 전송 가능");
await cell.dblclick();
await page.keyboard.type("YG-EM0600");
await page.keyboard.press("Enter");
await page.waitForFunction(
  () => document.querySelector(".review-bar .counter.ok") !== null, { timeout: 10000 });
console.log("복구 후:", await page.locator(".review-bar .counter.ok").textContent());
console.log("edited 파랑 셀:", await page.locator(".cell-edited").count());

step("전송");
await page.getByRole("button", { name: /전체 전송/ }).click();
await page.waitForSelector(".modal", { timeout: 5000 });
console.log("확인 모달:", (await page.locator(".modal").textContent()).replace(/\s+/g, " ").slice(0, 120));
await page.locator(".modal button.primary").click();
await page.waitForFunction(
  () => /전송 (완료|실패)/.test(document.querySelector(".modal h3")?.textContent ?? ""),
  { timeout: 20000 });
console.log("결과:", (await page.locator(".modal").textContent()).replace(/\s+/g, " ").slice(0, 160));
await page.screenshot({ path: `${SHOT}/04-sent.png`, fullPage: false });

step("브랜드 매핑 콘솔");
await page.locator(".modal button").first().click();
await page.getByRole("button", { name: "브랜드 매핑" }).click();
await page.waitForSelector(".cust-list li button", { timeout: 15000 });
console.log("고객 수:", (await page.locator(".cust-list li").count()), "/", await page.locator(".faint").first().textContent());
await page.locator(".cust-list li button").first().click();
await page.waitForSelector("table.matrix", { timeout: 10000 });
console.log("브랜드 행:", await page.locator("table.matrix tbody tr").count());
await page.screenshot({ path: `${SHOT}/05-brands.png`, fullPage: false });

await page.getByRole("button", { name: /적용 로직/ }).click();
await page.waitForTimeout(700);
console.log("로직 패널:", (await page.locator(".panel").last().textContent()).replace(/\s+/g, " ").slice(0, 200));
await page.screenshot({ path: `${SHOT}/06-logic.png`, fullPage: true });

console.log("\n══ 콘솔 오류:", errors.length ? errors : "없음");
await browser.close();
if (errors.length) process.exit(1);
