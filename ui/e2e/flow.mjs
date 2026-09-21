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

const main = () => page.locator('[data-testid="stMain"]');
const text = async () => (await main().textContent()).replace(/\s+/g, " ");
// 스트림릿은 재실행 중 "Running" 표시가 뜬다. 그게 사라질 때까지 기다린다.
const settle = async () => {
  await page.waitForTimeout(700);
  await page.waitForFunction(
    () => !document.querySelector('[data-testid="stStatusWidget"]'),
    { timeout: 60000 },
  ).catch(() => {});
  await page.waitForTimeout(900);
};

await page.goto("http://localhost:8501", { waitUntil: "networkidle" });
await settle();

console.log("── 거래처 검색 → 선택");
await page.locator('[data-testid="stSidebar"] input[type="text"]').first().fill("MSC");
await page.keyboard.press("Enter");
await settle();
console.log("사이드바 건수:", await page.locator('[data-testid="stSidebar"]').getByText(/곳$/).first().textContent());
await page.locator('[data-testid="stSidebar"] button', { hasText: "MSC Industrial" }).first().click();
await settle();

console.log("\n── 업로드");
await page.locator('[data-testid="stMain"] input[type="file"]').first()
  .setInputFiles("backend/tests/fixtures/msc/PO-SAMPLE-0001.htm");
await settle();
// 진행 막대(st.progress)는 변환 중에만 잠깐 있다가 사라진다 — 뜨는 순간을 놓치지 않게
// 클릭 전에 관찰자를 걸어 둔다. (픽스처 재생이면 청크 호출이 없어 0% 막대만 스친다)
await page.evaluate(() => {
  window.__sawProgressBar = false;
  new MutationObserver(() => {
    if (document.querySelector('[data-testid="stProgress"], [role="progressbar"]')) {
      window.__sawProgressBar = true;
    }
  }).observe(document.body, { childList: true, subtree: true });
});
await page.locator('[data-testid="stMain"] button', { hasText: "변환하기" }).first().click();
await settle();
console.log("진행 막대 떴음:", await page.evaluate(() => window.__sawProgressBar));
const afterParse = await text();
console.log("변환 결과:", afterParse.match(/변환 (완료|실패)[^가-힣]*[^·]*/)?.[0] ?? "(못 찾음)");
console.log("파싱 로그:", afterParse.match(/✔[^✔✖]*/g)?.join(" | ") ?? "(없음)");
await page.screenshot({ path: `${SHOT}/f1-parsed.png`, fullPage: true });

console.log("\n── 스프레드시트");
const grid = page.locator('[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"]').first();
console.log("그리드 있음:", await grid.count() > 0);
const headers = await page.locator('[data-testid="stMain"] [role="columnheader"]').allTextContents();
console.log("컬럼 수:", headers.length, "→", headers.slice(0, 8).join(" | "));
const metrics = await page.locator('[data-testid="stMetricValue"]').allTextContents();
console.log("합계 바:", metrics.join(" / "));
console.log("검증 통과:", afterParse.includes("검증을 통과") || (await text()).includes("검증을 통과"));
await page.screenshot({ path: `${SHOT}/f2-grid.png`, fullPage: true });

console.log("\n── 전송");
const sendBtn = page.locator('[data-testid="stMain"] button', { hasText: /전송/ }).last();
console.log("전송 버튼:", await sendBtn.textContent().catch(() => "(없음)"));
await sendBtn.click();
await settle();
const after = await text();
console.log("전송 결과:", after.match(/\d+건이 EAI로 전송[^.]*\.|전송[^.]*실패[^.]*\./)?.[0] ?? after.slice(-220));
await page.screenshot({ path: `${SHOT}/f3-sent.png`, fullPage: true });

console.log("\n── 브랜드 매핑 탭");
await page.locator('[data-testid="stSidebar"]').getByText("브랜드 매핑", { exact: true }).first().click();
await settle();
console.log("본문:", (await text()).slice(0, 200));
await page.screenshot({ path: `${SHOT}/f4-brands.png`, fullPage: true });

console.log("\n══ 페이지 오류:", errors.length ? errors : "없음");
console.log("══ 화면 트레이스백:", (await text()).includes("Traceback") ? "있음 (문제!)" : "없음");
await browser.close();
