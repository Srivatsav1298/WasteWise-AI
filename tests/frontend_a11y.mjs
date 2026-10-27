/* Accessibility and contrast audit.
 *
 * Drives the dashboard in a real browser and checks the things a screenshot
 * cannot show: colour contrast, heading order, accessible names, table
 * semantics, focus visibility and reduced motion.
 *
 * Run: node tests/frontend_a11y.mjs
 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const PORT = 4175;

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

const ROUTES = ["overview", "waste-risk", "demand-events", "simulator", "trust", "lineage"];

await new Promise((resolve) => server.listen(PORT, resolve));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

await page.goto(`http://localhost:${PORT}/index.html`, { waitUntil: "networkidle" });
await page.waitForSelector(".page-head h1", { timeout: 15000 });

// ---- contrast -------------------------------------------------------------
// Relative luminance per WCAG 2.1, computed from the rendered colours so the
// audit measures what the browser actually paints, not the stylesheet.
const CONTRAST_FN = `(() => {
  const parse = (value) => {
    const match = value.match(/rgba?\\(([^)]+)\\)/);
    if (!match) return null;
    const parts = match[1].split(",").map((part) => parseFloat(part.trim()));
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1
  });
  const channel = (value) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const luminance = (color) =>
    0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
  const effectiveBg = (node) => {
    let current = node;
    while (current && current !== document.documentElement) {
      const style = getComputedStyle(current);
      const color = parse(style.backgroundColor);
      if (color && color.a > 0) {
        if (color.a === 1) return color;
        return over(color, effectiveBg(current.parentElement || document.body));
      }
      current = current.parentElement;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const ratio = (a, b) => {
    const l1 = luminance(a);
    const l2 = luminance(b);
    const light = Math.max(l1, l2);
    const dark = Math.min(l1, l2);
    return (light + 0.05) / (dark + 0.05);
  };
  return (node) => {
    const style = getComputedStyle(node);
    const fg = parse(style.color);
    if (!fg) return null;
    const bg = effectiveBg(node);
    const painted = fg.a < 1 ? over(fg, bg) : fg;
    const size = parseFloat(style.fontSize);
    const weight = Number(style.fontWeight) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    return {
      ratio: ratio(painted, bg),
      required: large ? 3 : 4.5,
      size,
      weight,
      text: (node.textContent || "").trim().slice(0, 40)
    };
  };
})()`;

for (const route of ROUTES) {
  await page.evaluate((id) => {
    window.location.hash = `#/${id}`;
  }, route);
  await page.waitForFunction(
    (id) => document.querySelector(".nav-item[data-route='" + id + "']")?.getAttribute("aria-current") === "page",
    route,
    { timeout: 10000 }
  );

  // ---- heading order --------------------------------------------------
  const headings = await page.locator("#view h1, #view h2, #view h3, #view h4").evaluateAll((nodes) =>
    nodes.map((node) => ({ level: Number(node.tagName.slice(1)), text: node.textContent.trim().slice(0, 40) }))
  );
  check(`route ${route} has exactly one h1`, headings.filter((h) => h.level === 1).length === 1,
    headings.map((h) => `h${h.level}:${h.text}`).join(", "));
  let previous = 0;
  const jumps = [];
  for (const heading of headings) {
    if (previous && heading.level > previous + 1) {
      jumps.push(`h${previous} to h${heading.level} at "${heading.text}"`);
    }
    previous = heading.level;
  }
  check(`route ${route} heading levels never skip`, jumps.length === 0, jumps.join("; "));

  // ---- accessible names ----------------------------------------------
  const unnamed = await page.locator("#view button, #view a").evaluateAll((nodes) =>
    nodes
      .filter((node) => {
        const label = (
          node.getAttribute("aria-label") ||
          node.getAttribute("title") ||
          node.textContent ||
          ""
        ).trim();
        return label.length === 0;
      })
      .map((node) => node.outerHTML.slice(0, 80))
  );
  check(`route ${route} every control has an accessible name`, unnamed.length === 0, unnamed.join(" | "));

  // ---- table semantics ------------------------------------------------
  const tableIssues = await page.locator("#view table").evaluateAll((tables) =>
    tables.flatMap((table) => {
      const issues = [];
      if (!table.querySelector("caption")) {
        issues.push("table without a caption");
      }
      if (!table.querySelector("th")) {
        issues.push("table without a header cell");
      }
      const headers = Array.from(table.querySelectorAll("th"));
      headers.forEach((header) => {
        if (!header.getAttribute("scope") && !header.closest("thead")) {
          issues.push("header cell without a scope: " + header.textContent.trim().slice(0, 30));
        }
      });
      return issues;
    })
  );
  check(`route ${route} tables are properly structured`, tableIssues.length === 0, [...new Set(tableIssues)].join("; "));

  // ---- charts are described -------------------------------------------
  const chartIssues = await page.locator("#view svg.chart").evaluateAll((nodes) =>
    nodes
      .filter((node) => {
        const described =
          node.getAttribute("aria-label") ||
          node.getAttribute("aria-labelledby") ||
          node.getAttribute("role") === "img" ||
          node.closest("figure")?.querySelector("figcaption");
        return !described;
      })
      .map((node) => node.outerHTML.slice(0, 80))
  );
  check(`route ${route} every chart is described`, chartIssues.length === 0, chartIssues.join(" | "));

  // ---- contrast -------------------------------------------------------
  const lowContrast = await page.evaluate((fnSource) => {
    const measure = eval(fnSource);
    const results = [];
    const nodes = document.querySelectorAll(
      "#view p, #view li, #view td, #view th, #view h1, #view h2, #view h3, #view h4, #view span, #view a, #view button, #view figcaption, #view .stat-value, #view .stat-label"
    );
    nodes.forEach((node) => {
      if (!node.textContent || !node.textContent.trim()) return;
      if (node.querySelector("p, li, td, th, span, a")) return;
      const style = getComputedStyle(node);
      if (style.visibility === "hidden" || style.display === "none") return;
      const box = node.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) return;
      const measurement = measure(node);
      if (!measurement) return;
      if (measurement.ratio < measurement.required) {
        results.push(
          measurement.ratio.toFixed(2) + ":1 (needs " + measurement.required + ":1) " +
            measurement.size + "px " + measurement.text
        );
      }
    });
    return results;
  }, CONTRAST_FN);
  check(`route ${route} text meets the WCAG AA contrast ratio`, lowContrast.length === 0,
    [...new Set(lowContrast)].slice(0, 6).join(" | "));
}

// ---- shell ---------------------------------------------------------------
const skipLink = await page.locator("a.skip-link").count();
check("the page has a skip link", skipLink === 1, `${skipLink} skip links`);

const mainLandmark = await page.locator("main#main").count();
check("the page has a main landmark", mainLandmark === 1, `${mainLandmark} main landmarks`);

const navLabel = await page.locator("nav[aria-label]").count();
check("navigation is labelled", navLabel >= 1, `${navLabel} labelled navs`);

const focusRing = await page.evaluate(() => {
  const style = Array.from(document.styleSheets)
    .flatMap((sheet) => {
      try {
        return Array.from(sheet.cssRules);
      } catch {
        return [];
      }
    })
    .find((rule) => rule.selectorText && rule.selectorText.includes(":focus-visible"));
  return style ? style.style.outline || style.style.getPropertyValue("outline-width") : null;
});
check("focus-visible is styled", focusRing !== null, String(focusRing));

const reducedMotion = await page.evaluate(() =>
  Array.from(document.styleSheets)
    .flatMap((sheet) => {
      try {
        return Array.from(sheet.cssRules);
      } catch {
        return [];
      }
    })
    .some((rule) => rule.conditionText && rule.conditionText.includes("prefers-reduced-motion"))
);
check("reduced motion is respected", reducedMotion, "no prefers-reduced-motion block");

// Keyboard: the first tab stop must reach the skip link, then the navigation.
const tabOrder = [];
for (let index = 0; index < 6; index += 1) {
  await page.keyboard.press("Tab");
  tabOrder.push(
    await page.evaluate(() => {
      const active = document.activeElement;
      return active ? (active.className || active.tagName) + ":" + (active.textContent || "").trim().slice(0, 24) : "none";
    })
  );
}
check("the skip link is the first tab stop", tabOrder[0].includes("skip-link"), tabOrder.join(" > "));

const focusVisible = await page.evaluate(() => {
  const link = document.querySelector(".nav-item");
  link.focus();
  const style = getComputedStyle(link, ":focus-visible");
  return style.outlineStyle !== "none" || style.boxShadow !== "none";
});
check("focused elements show a visible focus indicator", focusVisible, "no focus ring on nav items");

await browser.close();
server.close();

const passed = checks.filter((entry) => entry.ok).length;
console.log(`${passed}/${checks.length} accessibility checks passed`);
if (failures.length) {
  console.error("FAILURES:");
  failures.forEach((failure) => console.error(`  - ${failure}`));
  process.exit(1);
}
console.log("accessibility audit OK");
