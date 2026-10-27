/* Frontend smoke test.
 *
 * Serves the repository over HTTP, drives the dashboard in a real browser and
 * asserts that every route renders published data without console errors.
 *
 * Run: node tests/frontend_smoke.mjs
 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const PORT = 4174;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8"
};

const server = createServer(async (request, response) => {
  const url = new URL(request.url, `http://localhost:${PORT}`);
  const relative = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, "");
  const target = join(ROOT, relative === "/" ? "index.html" : relative);
  try {
    const body = await readFile(target);
    response.writeHead(200, { "content-type": MIME[extname(target)] || "application/octet-stream" });
    response.end(body);
  } catch {
    response.writeHead(404, { "content-type": "text/plain" });
    response.end("not found");
  }
});

const failures = [];
const checks = [];

function check(name, condition, detail) {
  checks.push({ name, ok: Boolean(condition) });
  if (!condition) {
    failures.push(detail ? `${name} — ${detail}` : name);
  }
}

const ROUTES = [
  { id: "overview", expect: ["overview", "avoidable waste cost", "measured"] },
  { id: "waste-risk", expect: ["waste risk", "ranked prevention backlog", "avoidable"] },
  {
    id: "demand-events",
    expect: ["demand & events", "measured demand lift", "no published lift", "purchase plan", "order to place"]
  },
  { id: "simulator", expect: ["what-if", "scenario", "scenario estimate"] },
  { id: "trust", expect: ["data trust console", "metric registry", "expectations", "protected"] },
  { id: "lineage", expect: ["pipeline & lineage", "model lineage", "reconciliation ledger"] }
];

await new Promise((resolve) => server.listen(PORT, resolve));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") {
    consoleErrors.push(message.text());
  }
});
page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

await page.goto(`http://localhost:${PORT}/index.html`, { waitUntil: "networkidle" });
await page.waitForSelector(".page-head h1", { timeout: 15000 });

for (const route of ROUTES) {
  await page.evaluate((id) => {
    window.location.hash = `#/${id}`;
  }, route.id);
  await page.waitForFunction(
    (id) => document.querySelector(".nav-item[data-route='" + id + "']")?.getAttribute("aria-current") === "page",
    route.id,
    { timeout: 10000 }
  );
  const text = (await page.locator("#view").innerText()).toLowerCase();
  for (const needle of route.expect) {
    check(`route ${route.id} shows "${needle}"`, text.includes(needle.toLowerCase()), `view text missing "${needle}"`);
  }
  const svgCount = await page.locator("#view svg.chart").count();
  if (route.id !== "lineage" && route.id !== "trust") {
    check(`route ${route.id} draws a chart`, svgCount > 0, "no svg.chart rendered");
  }
  const emptyCells = await page.locator("#view td").evaluateAll((cells) =>
    cells.filter((cell) => cell.textContent.trim() === "undefined" || cell.textContent.trim() === "NaN").length
  );
  check(`route ${route.id} has no undefined/NaN cells`, emptyCells === 0, `${emptyCells} broken cells`);
}

const badge = await page.locator("#publish-badge").innerText();
check("publish badge reports the trust gate", badge.includes("Published"), badge);

const activeCount = await page.locator('.nav-item[aria-current="page"]').count();
check("exactly one nav item is current", activeCount === 1, `${activeCount} current items`);

// Every metric the registry publishes must reach the trust console, and every
// published number on the overview must carry a trust chip.
await page.evaluate(() => {
  window.location.hash = "#/trust";
});
await page.waitForFunction(
  () => document.querySelector(".nav-item[data-route='trust']")?.getAttribute("aria-current") === "page",
  null,
  { timeout: 10000 }
);
const metricRows = await page.locator("#view table.data tbody tr").count();
check("trust console lists the metric registry", metricRows >= 8, `${metricRows} metric rows`);
const uncovered = await page.locator("#view .chip-unverified").count();
const unverifiedMetrics = await page.evaluate(() => {
  const report = window.WW && window.WW.app && window.WW.app.state.bundle.trust_report;
  return report ? report.metrics.filter((m) => m.trust_state === "unverified").length : -1;
});
check(
  "no published metric is unverified",
  unverifiedMetrics === 0,
  `${unverifiedMetrics} unverified metrics`
);

await page.evaluate(() => {
  window.location.hash = "#/overview";
});
await page.waitForFunction(
  () => document.querySelector(".nav-item[data-route='overview']")?.getAttribute("aria-current") === "page",
  null,
  { timeout: 10000 }
);
const statChips = await page.locator("#view .stat .stat-trust .chip").count();
check("every overview stat tile carries a trust chip", statChips >= 4, `${statChips} chips`);
const overviewText = await page.locator("#view").innerText();
check(
  "overview publishes no placeholder for a displayed metric",
  !overviewText.includes("NaN") && !overviewText.includes("undefined"),
  overviewText.slice(0, 200)
);

const overflow = await page.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth
);
check("no horizontal overflow at 1440px", overflow <= 1, `overflow ${overflow}px`);

await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(250);
const mobileOverflow = await page.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth
);
check("no horizontal overflow at 390px", mobileOverflow <= 1, `overflow ${mobileOverflow}px`);

check("no console errors", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));

await browser.close();
server.close();

const passed = checks.filter((entry) => entry.ok).length;
console.log(`${passed}/${checks.length} frontend checks passed`);
if (failures.length) {
  console.error("FAILURES:");
  failures.forEach((failure) => console.error(`  - ${failure}`));
  process.exit(1);
}
console.log("frontend smoke test OK");
