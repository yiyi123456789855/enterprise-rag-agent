const { chromium } = require("playwright");

async function main() {
  const baseUrl = process.argv[2] || "http://127.0.0.1:8000";
  const screenshotPath = process.argv[3] || "ui-smoke.png";
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.BROWSER_EXECUTABLE_PATH || undefined,
  });
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}, deviceScaleFactor: 1});
  const errors = [];
  page.on("console", message => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(baseUrl, {waitUntil: "networkidle"});
  await page.locator("#refreshButton").click();
  await page.waitForTimeout(300);
  const title = await page.locator("h1").textContent();
  const health = await page.locator("#healthText").textContent();
  if (!title.includes("企业知识库 RAG Agent")) throw new Error(`Unexpected title: ${title}`);
  if (!health.includes("服务正常")) throw new Error(`Health check failed: ${health}`);
  if (errors.length) throw new Error(`Browser errors: ${errors.join(" | ")}`);
  await page.screenshot({path: screenshotPath, fullPage: true});
  await browser.close();
  console.log(JSON.stringify({status: "ok", title, health, screenshotPath}));
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
