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
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
page.on("pageerror", (e) => errors.push(e.message));

const settle = async (ms = 1200) => { await page.waitForTimeout(ms); };

await page.goto("http://localhost:8501", { waitUntil: "networkidle" });
await settle(3000);

console.log("── 첫 화면");
console.log("제목:", await page.locator("h1").first().textContent().catch(() => "(없음)"));
const sidebarText = (await page.locator('[data-testid="stSidebar"]').textContent()).replace(/\s+/g, " ");
console.log("사이드바:", sidebarText.slice(0, 220));
await page.screenshot({ path: `${SHOT}/s1-home.png`, fullPage: true });

console.log("\n── 거래처 목록 (전체 430곳 나오는지)");
const custButtons = await page.locator('[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] button').count();
console.log("거래처 버튼 수:", custButtons);
console.log("건수 표시:", await page.locator('[data-testid="stSidebar"]').getByText(/곳$/).first().textContent().catch(() => "(없음)"));

console.log("\n── 검색: MSC");
const search = page.locator('[data-testid="stSidebar"] input[type="text"]').first();
await search.fill("MSC");
await settle(2500);
const after = (await page.locator('[data-testid="stSidebar"]').textContent()).replace(/\s+/g, " ");
console.log("검색 후 사이드바:", after.slice(0, 260));
await page.screenshot({ path: `${SHOT}/s2-search.png`, fullPage: true });

console.log("\n── MSC 선택");
const msc = page.locator('[data-testid="stSidebar"] button', { hasText: "MSC Industrial" }).first();
await msc.click();
await settle(3000);
console.log("본문:", (await page.locator('[data-testid="stMain"]').textContent()).replace(/\s+/g, " ").slice(0, 300));
await page.screenshot({ path: `${SHOT}/s3-selected.png`, fullPage: true });

console.log("\n── 규칙 미리보기 펼치기");
const exp = page.locator('[data-testid="stMain"] summary', { hasText: "자동 적용되는 값" }).first();
if (await exp.count()) { await exp.click(); await settle(2000); }
await page.screenshot({ path: `${SHOT}/s4-rules.png`, fullPage: true });
console.log("규칙 영역:", (await page.locator('[data-testid="stMain"]').textContent()).replace(/\s+/g, " ").slice(0, 400));

console.log("\n══ 페이지 오류:", errors.length ? errors : "없음");
await browser.close();
