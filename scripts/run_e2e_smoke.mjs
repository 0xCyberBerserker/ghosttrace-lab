import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const appUrl = process.env.GHOSTTRACE_E2E_URL || "http://127.0.0.1:5000/";
const outputDir = path.resolve("output", "playwright");
const reportPath = path.join(outputDir, "ghosttrace-smoke-report.json");
const allowlistedConsoleErrorPatterns = [
  /favicon\.ico/i
];

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

async function writeReport(report) {
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
}

async function collectUiSnapshot(page) {
  return page.evaluate(() => {
    const readText = (selector) => document.querySelector(selector)?.textContent?.trim() ?? "";
    const listCount = (selector) => document.querySelectorAll(selector).length;

    return {
      theme: document.body.dataset.theme ?? "",
      activeJobTitle: readText("#active-job-title"),
      telemetry: {
        overall: readText("#metrics-overall-pill"),
        services: readText("#metrics-services-overview"),
        queues: readText("#metrics-queues-overview"),
        activeJobs: readText("#metrics-active-jobs-overview"),
        status: readText("#metrics-status"),
      },
      reconstruction: {
        focusText: readText("#reconstruction-focus"),
        draftPreviewText: readText("#reconstruction-draft-preview"),
        targetCount: listCount("#reconstruction-targets-list .reconstruction-card"),
      },
      x64dbg: {
        sessionStatus: readText("#x64dbg-session-status"),
        findingsCount: readText("#x64dbg-findings-count"),
        requestCount: readText("#x64dbg-requests-count"),
      },
      windowsLab: {
        username: readText("#windows-lab-username"),
        password: readText("#windows-lab-password"),
        status: readText("#windows-lab-credentials-status"),
      }
    };
  });
}

async function assertVisible(page, selector, label) {
  const locator = page.locator(selector);
  const count = await locator.count();
  if (count < 1) {
    throw new Error(`Missing expected element: ${label} (${selector})`);
  }
}

async function assertText(page, selector, expected, label) {
  const text = await page.locator(selector).first().textContent();
  if (!text || !text.includes(expected)) {
    throw new Error(`Unexpected ${label}. Expected to include "${expected}", got "${text ?? ""}"`);
  }
}

async function waitForTextNotContaining(page, selector, disallowedText, label, timeout = 15000) {
  await page.waitForFunction(
    ([targetSelector, forbiddenText]) => {
      const node = document.querySelector(targetSelector);
      const text = node?.textContent?.trim() ?? "";
      return Boolean(text) && !text.includes(forbiddenText);
    },
    [selector, disallowedText],
    { timeout }
  );
  await assertVisible(page, selector, label);
}

async function assertNonEmptyText(page, selector, label) {
  const text = (await page.locator(selector).first().textContent())?.trim() ?? "";
  if (!text) {
    throw new Error(`Expected non-empty text for ${label} (${selector})`);
  }
}

async function assertThemeHero(page, expectedThemeLabel) {
  const themeValue = await page.evaluate(() => {
    const blocks = Array.from(document.querySelectorAll(".phase-hero-meta-block"));
    for (const block of blocks) {
      const label = block.querySelector(".phase-hero-meta-label")?.textContent?.trim();
      if (label === "Visual theme") {
        return block.querySelector(".phase-hero-meta-value")?.textContent?.trim() ?? "";
      }
    }
    return "";
  });

  if (!themeValue.includes(expectedThemeLabel)) {
    throw new Error(`Unexpected theme hero copy. Expected to include "${expectedThemeLabel}", got "${themeValue}"`);
  }
}

async function waitForVisible(page, selector, label, timeout = 15000) {
  await page.locator(selector).first().waitFor({ state: "visible", timeout });
  await assertVisible(page, selector, label);
}

async function waitForViewActive(page, selector, label, timeout = 15000) {
  await page.waitForFunction(
    (targetSelector) => {
      const node = document.querySelector(targetSelector);
      return Boolean(node) && !node.classList.contains("hidden");
    },
    selector,
    { timeout }
  );
  await assertVisible(page, selector, label);
}

async function run() {
  await ensureDir(outputDir);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const report = {
    appUrl,
    startedAt: new Date().toISOString(),
    endedAt: null,
    status: "running",
    durationMs: null,
    steps: [],
    screenshots: [],
    consoleMessages: [],
    pageErrors: [],
    openedJob: null,
    uiSnapshot: null,
    failure: null
  };

  const stepStarts = new Map();
  const recordStep = (name, status, detail = "") => {
    const now = new Date();
    if (status === "started") {
      stepStarts.set(name, now.getTime());
    }
    const startedAtMs = stepStarts.get(name);
    report.steps.push({
      name,
      status,
      detail,
      at: now.toISOString(),
      durationMs: status === "started" || typeof startedAtMs !== "number" ? null : now.getTime() - startedAtMs
    });
  };

  page.on("console", (message) => {
    report.consoleMessages.push({
      type: message.type(),
      text: message.text(),
      location: message.location()
    });
  });

  page.on("pageerror", (error) => {
    report.pageErrors.push({
      message: error.message,
      stack: error.stack ?? ""
    });
  });

  try {
    recordStep("open-shell", "started");
    await page.goto(appUrl, { waitUntil: "domcontentloaded" });

    await assertText(page, "title", "GhostTrace", "page title");
    await assertVisible(page, "h1", "main title");
    await assertVisible(page, "#upload-form", "upload form");
    await assertVisible(page, "#jobs-list-shell", "jobs list shell");
    await assertVisible(page, ".phase-hero", "workspace hero");
    await assertVisible(page, ".workflow-mode-card", "workflow cards");
    await assertVisible(page, ".theme-picker-select", "theme selector");

    const workflowCards = await page.locator(".workflow-mode-card").count();
    if (workflowCards !== 3) {
      throw new Error(`Expected 3 workflow cards, found ${workflowCards}`);
    }
    recordStep("open-shell", "passed", "Main shell rendered with workflow cards.");

    await page.screenshot({ path: path.join(outputDir, "ghosttrace-home-smoke.png"), fullPage: false });
    report.screenshots.push("ghosttrace-home-smoke.png");

    recordStep("theme-persistence", "started");
    await page.evaluate(() => {
      localStorage.setItem("ghidraaas-theme", "fallout-3-terminal");
    });
    await page.reload({ waitUntil: "domcontentloaded" });

    const activeTheme = await page.evaluate(() => document.body.dataset.theme);
    if (activeTheme !== "fallout-3-terminal") {
      throw new Error(`Expected fallout-3-terminal theme, got ${activeTheme ?? "none"}`);
    }

    await assertThemeHero(page, "Fallout 3 Terminal");
    recordStep("theme-persistence", "passed", "Fallout theme persisted after reload.");

    await page.screenshot({ path: path.join(outputDir, "ghosttrace-fallout-smoke.png"), fullPage: false });
    report.screenshots.push("ghosttrace-fallout-smoke.png");

    recordStep("quick-health", "started");
    await waitForTextNotContaining(page, "#metrics-status", "Loading stack telemetry", "metrics status");
    await assertNonEmptyText(page, "#metrics-services-overview", "services overview");
    await assertNonEmptyText(page, "#metrics-queues-overview", "queues overview");
    await assertNonEmptyText(page, "#metrics-active-jobs-overview", "active jobs overview");
    recordStep("quick-health", "passed", "Quick Health rendered non-empty telemetry summaries.");

    recordStep("reconstruct-lane", "started");
    const openButtons = page.locator(".job-open-button");
    const openCount = await openButtons.count();
    if (openCount < 1) {
      throw new Error("Smoke E2E requires at least one existing analysis job");
    }

    report.openedJob = await openButtons.first().getAttribute("data-job-id");
    await openButtons.first().click();
    await waitForVisible(page, "#chat-container", "chat container");
    await waitForVisible(page, ".workspace-progress-shell", "workspace progress shell");

    await page.locator(".workspace-progress-card").filter({ hasText: "Reconstruct" }).first().click();
    await waitForViewActive(page, "#reconstruction-view", "reconstruction view");
    await waitForVisible(page, "#reconstruction-generate-targets", "reconstruction actions");
    await waitForVisible(page, "#reconstruction-targets-list", "reconstruction targets list");
    await waitForVisible(page, '[data-collapse-target="reconstruction-draft-list-shell"]', "reconstruction drafts toggle");
    await assertNonEmptyText(page, "#reconstruction-focus", "reconstruction focus");
    await assertNonEmptyText(page, "#reconstruction-draft-preview", "reconstruction draft preview");
    recordStep("reconstruct-lane", "passed", "Reconstruct lane opened with generation controls.");
    await page.screenshot({ path: path.join(outputDir, "ghosttrace-reconstruct-smoke.png"), fullPage: false });
    report.screenshots.push("ghosttrace-reconstruct-smoke.png");

    recordStep("validate-lane", "started");
    await page.locator("button").filter({ hasText: "3. Validate" }).first().click();
    await page.locator(".workspace-progress-card").filter({ hasText: "Validate" }).first().click();
    await waitForViewActive(page, "#x64dbg-view", "x64dbg view");
    await waitForVisible(page, "#x64dbg-status", "x64dbg status");

    await page.locator('[data-collapse-target="x64dbg-operations-shell"]').click();
    await waitForVisible(page, "#x64dbg-operations-shell", "x64dbg operations shell");
    await page.locator('[data-collapse-target="windows-lab-shell"]').click();
    await waitForVisible(page, "#windows-lab-shell", "windows lab shell");
    await waitForVisible(page, "#toggle-windows-lab-password", "windows lab reveal button");
    await waitForVisible(page, "#windows-lab-username", "windows lab username");
    await waitForTextNotContaining(page, "#windows-lab-credentials-status", "Loading generated lab credentials", "windows lab credentials status");
    await assertText(page, "#toggle-windows-lab-password", "Reveal Password", "windows lab reveal control");
    await page.locator("#toggle-windows-lab-password").click();
    await waitForTextNotContaining(page, "#windows-lab-password", "••••••••••••••••••••••••", "revealed windows lab password");
    await assertText(page, "#toggle-windows-lab-password", "Hide Password", "windows lab hide control");
    await assertText(page, "#windows-lab-credentials-status", "revealed", "windows lab reveal status");
    recordStep("validate-lane", "passed", "Validate lane opened with x64dbg and lab controls.");

    await page.screenshot({ path: path.join(outputDir, "ghosttrace-x64dbg-smoke.png"), fullPage: false });
    report.screenshots.push("ghosttrace-x64dbg-smoke.png");

    recordStep("console-health", "started");
    const actionableConsoleErrors = report.consoleMessages.filter((message) => {
      if (!["error", "assert"].includes(message.type)) {
        return false;
      }
      return !allowlistedConsoleErrorPatterns.some((pattern) => pattern.test(message.text));
    });
    if (report.pageErrors.length > 0) {
      throw new Error(`Smoke E2E saw ${report.pageErrors.length} page error(s). Check ${reportPath}.`);
    }
    if (actionableConsoleErrors.length > 0) {
      throw new Error(`Smoke E2E saw ${actionableConsoleErrors.length} console error(s). Check ${reportPath}.`);
    }
    recordStep("console-health", "passed", "No actionable console errors or page errors detected.");

    report.status = "passed";
    report.endedAt = new Date().toISOString();
    report.durationMs = new Date(report.endedAt).getTime() - new Date(report.startedAt).getTime();
    report.uiSnapshot = await collectUiSnapshot(page);
    await writeReport(report);
    console.log(`Smoke E2E passed against ${appUrl}`);
  } catch (error) {
    report.failure = {
      message: error instanceof Error ? error.message : String(error)
    };
    report.uiSnapshot = await collectUiSnapshot(page).catch(() => null);
    throw error;
  } finally {
    if (report.status === "running") {
      report.status = "failed";
      report.endedAt = new Date().toISOString();
      report.durationMs = new Date(report.endedAt).getTime() - new Date(report.startedAt).getTime();
      await writeReport(report);
    }
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
