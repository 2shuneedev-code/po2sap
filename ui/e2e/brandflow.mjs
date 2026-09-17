/**
 * 브라우저 실동작 확인 — 타입체크나 임포트 성공은 화면이 뜨는 증거가 아니다.
 *
 * 전제:
 *   LLM_PROVIDER=mock EAI_ENDPOINT=http://127.0.0.1:9000/po2sap/order \
 *     streamlit run po2sap.py --server.port 8501 --server.headless true
 *   python scripts/mock_eai_server.py
 *
 * 실행: node ui/e2e/<파일>.mjs   (로컬 크로미움이 따로면 CHROME_PATH=...)
 * LLM 호출 없음(mock 재생) = 비용 0.
 */
import { chromium } from "playwright";
const SHOT = process.env.SHOT_DIR ?? "ui/e2e/shots";
const errors = [];
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);
const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
page.on("pageerror", (e) => errors.push(e.message));
const text = async () => (await page.locator('[data-testid="stMain"]').textContent()).replace(/\s+/g, " ");
const settle = async (ms = 2000) => page.waitForTimeout(ms);

await page.goto("http://localhost:8501", { waitUntil: "networkidle" });
await settle(3000);
await page.locator('[data-testid="stSidebar"]').getByText("브랜드 매핑", { exact: true }).first().click();
await settle(2500);
console.log("고객 수:", await page.locator('[data-testid="stSidebar"]').getByText(/곳$/).first().textContent());

await page.locator('[data-testid="stSidebar"] input[type="text"]').first().fill("YG-1 Japan");
await page.keyboard.press("Enter");
await settle(2500);
await page.locator('[data-testid="stSidebar"] button', { hasText: "YG-1 Japan" }).first().click();
await settle(3500);

const heads = await page.locator('[data-testid="stMain"] [role="columnheader"]').allTextContents();
console.log("표 컬럼:", heads.join(" | "));
const rows = await page.locator('[data-testid="stMain"] [role="row"]').count();
console.log("표 행 수(헤더 포함):", rows);
console.log("에디터 수:", await page.locator('[data-testid="stMain"] [data-testid="stDataFrameResizable"]').count());
console.log("본문 요약:", (await text()).slice(0, 260));
await page.screenshot({ path: `${SHOT}/b1-table.png`, fullPage: false });

console.log("\n── 미매핑 목록 펼치기");
const un = page.locator('[data-testid="stMain"] summary', { hasText: "매핑 안 된" }).first();
if (await un.count()) { await un.click(); await settle(1800); console.log("펼침:", (await un.textContent()).trim()); }
await page.screenshot({ path: `${SHOT}/b2-unmapped.png`, fullPage: true });

console.log("\n── 적용 로직 탭");
await page.locator('[data-testid="stMain"] [role="tab"]', { hasText: "적용 로직" }).first().click();
await settle(2500);
await page.screenshot({ path: `${SHOT}/b3-logic.png`, fullPage: true });
console.log("탭 선택됨:", await page.locator('[data-testid="stMain"] [role="tab"][aria-selected="true"]').textContent());

console.log("\n══ 페이지 오류:", errors.length ? errors : "없음");
console.log("══ 트레이스백:", (await text()).includes("Traceback") ? "있음 (문제!)" : "없음");
await browser.close();
