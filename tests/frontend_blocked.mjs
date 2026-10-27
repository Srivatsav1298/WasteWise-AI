/* Blocked-gate frontend test.
 *
 * The dashboard promises that a refused run shows the block, not last run's
 * numbers. This serves the repository, makes the gate report `blocked` and the
 * measured artefacts absent (which is what the export leaves behind), and
 * asserts that the data routes refuse to render a figure while the trust and
 * pipeline pages still explain what happened.
 *
 * Run: node tests/frontend_blocked.mjs
 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const PORT = 4176;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8"
};

const MEASUREMENTS = [
  "waste_priority",
  "waste_opportunity",
  "waste_daily",
  "waste_by_reason",
  "waste_by_ingredient",
  "waste_by_category",
  "demand_events",
  "purchase_plan",
  "food_loss_summary",
  "overview"
];

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

const DATA_ROUTES = ["overview", "waste-risk", "demand-events", "simulator"];

const blockedStatus = {
  status: "blocked",
  generated_at: "2026-09-30T00:00:00Z",
  blockers: [
    {
      check_id: "dq_waste_cost_reconciles",
      message: "waste cost does not reconcile with the delivery",
      remediation: "rebuild the waste facts and re-run the trust engine"
    }
  ],
  warnings: [],
  metrics_displayable: 0,
  metrics_total: 8
};

await new Promise((resolve) => server.listen(PORT, resolve));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() !== "error") {
    return;
  }
  const text = message.text();
  // The purged measurement files are expected to 404; the data layer treats a
  // missing artefact as "nothing published", which is the point of the test.
  if (/Failed to load resource.*404/.test(text)) {
    return;
  }
  consoleErrors.push(text);
});
page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

// A blocked run: the gate says blocked and the numbers were purged.
for (const name of MEASUREMENTS) {
  await page.route(`**/data/marts/${name}.json`, (route) => route.fulfill({ status: 404, body: "" }));
}
await page.route("**/data/marts/publish_status.json", (route) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(blockedStatus) })
);
await page.route("**/data/marts/trust_report.json", (route) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      status: "blocked",
      generated_at: blockedStatus.generated_at,
      summary: {
        checks_total: 20,
        checks_passed: 19,
        checks_failed: 1,
        blockers: 1,
        warnings: 0,
        metrics_total: 8,
        metrics_displayable: 0
      },
      checks: [
        {
          check_id: "dq_waste_cost_reconciles",
          target_model: "mart_food_loss_summary",
          severity: "blocker",
          status: "fail",
          message: "waste cost does not reconcile with the delivery",
          remediation: "rebuild the waste facts and re-run the trust engine",
          observed: 1,
          expected: 0
        }
      ],
      metrics: [],
      sources: []
    })
  })
);

await page.goto(`http://localhost:${PORT}/index.html`, { waitUntil: "networkidle" });

const masthead = await page.locator("#publish-badge").innerText();
check("masthead says the publication is blocked", /blocked/i.test(masthead), masthead);

for (const route of DATA_ROUTES) {
  await page.evaluate((id) => {
    window.location.hash = `#/${id}`;
  }, route);
  await page.waitForFunction(
    (id) => document.querySelector(".nav-item[data-route='" + id + "']")?.getAttribute("aria-current") === "page",
    route,
    { timeout: 10000 }
  );

  const text = await page.locator("#view").innerText();
  check(`route ${route} says the publication is blocked`, /publication blocked/i.test(text), text.slice(0, 120));
  check(
    `route ${route} names the failing expectation`,
    text.includes("dq_waste_cost_reconciles"),
    "blocker not shown"
  );

  const numbers = await page.locator("#view .stat-value").count();
  check(`route ${route} renders no published numbers`, numbers === 0, `${numbers} stat tiles`);

  const charts = await page.locator("#view svg.chart").count();
  check(`route ${route} draws no chart from stale data`, charts === 0, `${charts} charts`);

  const h1 = await page.locator("#view h1").count();
  check(`route ${route} has exactly one h1`, h1 === 1, `${h1} h1 elements`);
}

// The trust console is how a reader finds out what broke.
await page.evaluate(() => {
  window.location.hash = "#/trust";
});
await page.waitForFunction(
  () => document.querySelector(".nav-item[data-route='trust']")?.getAttribute("aria-current") === "page",
  null,
  { timeout: 10000 }
);
const trustText = await page.locator("#view").innerText();
check("trust console explains the block", /publication blocked/i.test(trustText), trustText.slice(0, 120));
check(
  "trust console lists the failed expectation",
  trustText.includes("dq_waste_cost_reconciles"),
  "failed check missing"
);
check(
  "trust console shows the remediation",
  trustText.includes("rebuild the waste facts"),
  "remediation missing"
);

// The pipeline page is structural, so it stays available.
await page.evaluate(() => {
  window.location.hash = "#/lineage";
});
await page.waitForFunction(
  () => document.querySelector(".nav-item[data-route='lineage']")?.getAttribute("aria-current") === "page",
  null,
  { timeout: 10000 }
);
const lineageText = await page.locator("#view").innerText();
check("pipeline page still renders", /model lineage/i.test(lineageText), lineageText.slice(0, 120));

check("no console errors", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));

await browser.close();
await new Promise((resolve) => server.close(resolve));

const passed = checks.filter((item) => item.ok).length;
console.log(`${passed}/${checks.length} blocked-gate checks passed`);
if (failures.length) {
  console.error("FAILURES:");
  failures.forEach((failure) => console.error(`  - ${failure}`));
  process.exit(1);
}
console.log("blocked-gate test OK");
