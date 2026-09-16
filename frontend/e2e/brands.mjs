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
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.on("pageerror", (e) => errors.push(e.message));
page.on("response", (r) => { if (r.status() >= 400) console.log("  !! HTTP", r.status(), r.url()); });

await page.goto("http://localhost:5173", { waitUntil: "networkidle" });
await page.getByRole("button", { name: "브랜드 매핑" }).click();
await page.waitForSelector(".cust-list li button");

console.log("── MSC 검색");
await page.locator('input[type="search"]').fill("MSC");
await page.waitForTimeout(900);
const names = await page.$$eval(".cust-list .nm", (n) => n.map((e) => e.textContent));
console.log("검색 결과:", names.join(" | "));

await page.locator(".cust-list li button").first().click();
await page.waitForSelector("table.matrix tbody tr");
console.log("브랜드 행:", await page.locator("table.matrix tbody tr").count());
console.log("기존 매핑 칩:", await page.locator(".chip").allTextContents());
await page.screenshot({ path: `${SHOT}/07-msc-brands.png` });

console.log("\n── 적용 로직 탭");
await page.getByRole("button", { name: /적용 로직/ }).click();
await page.waitForSelector(".rule-card");
console.log("로직 카드:", await page.$$eval(".rule-card header b", (n) => n.map((e) => e.textContent)).then(a => a.join(" | ")));
await page.screenshot({ path: `${SHOT}/08-msc-logic.png`, fullPage: true });

console.log("\n── 원문 키 추가 (쓰기 경로)");
await page.getByRole("button", { name: /브랜드 매핑/ }).last().click();
await page.waitForSelector("table.matrix tbody tr");
const row = page.locator("table.matrix tbody tr").filter({ hasText: "HERTEL" }).first();
const before = await row.locator(".chip").allTextContents();
console.log("추가 전:", before);
await row.locator('input[type="text"]').fill("E2E-TEST-KEY");
await row.getByRole("button", { name: "추가" }).click();
await page.waitForTimeout(1200);
console.log("추가 후:", await row.locator(".chip").allTextContents());

console.log("\n── 중복 문구는 서버가 거부해야 한다");
const other = page.locator("table.matrix tbody tr").filter({ hasText: "INTERSTATE" }).first();
await other.locator('input[type="text"]').fill("E2E-TEST-KEY");
await other.getByRole("button", { name: "추가" }).click();
await page.waitForTimeout(1200);
console.log("거부 메시지:", await page.locator(".callout.error").textContent().catch(() => "(없음 — 문제!)"));

console.log("\n── 되돌리기 (테스트가 참조표를 더럽히지 않게)");
await row.locator(".chip").filter({ hasText: "E2E-TEST-KEY" }).locator("button").click();
await page.waitForTimeout(1200);
console.log("복원 후:", await row.locator(".chip").allTextContents());
await page.screenshot({ path: `${SHOT}/09-brand-write.png` });

console.log("\n══ 페이지 오류:", errors.length ? errors : "없음");
await browser.close();
