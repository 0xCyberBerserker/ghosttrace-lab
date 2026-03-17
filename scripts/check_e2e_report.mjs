import fs from "node:fs/promises";
import path from "node:path";

const reportPath = process.env.GHOSTTRACE_E2E_REPORT
  ? path.resolve(process.env.GHOSTTRACE_E2E_REPORT)
  : path.resolve("output", "playwright", "ghosttrace-smoke-report.json");
const reportDir = path.dirname(reportPath);

const totalDurationLimitMs = Number(process.env.GHOSTTRACE_E2E_MAX_TOTAL_MS || 15000);
const defaultStepLimitMs = Number(process.env.GHOSTTRACE_E2E_MAX_STEP_MS || 5000);
const expectedTheme = process.env.GHOSTTRACE_E2E_EXPECTED_THEME || "fallout-3-terminal";
const expectedScreenshots = (
  process.env.GHOSTTRACE_E2E_REQUIRED_SCREENSHOTS
  || "ghosttrace-home-smoke.png,ghosttrace-fallout-smoke.png,ghosttrace-reconstruct-smoke.png,ghosttrace-x64dbg-smoke.png"
).split(",").map((entry) => entry.trim()).filter(Boolean);
const allowedX64dbgStates = (
  process.env.GHOSTTRACE_E2E_ALLOWED_X64DBG_STATES
  || "bridge-online,attached,idle"
).split(",").map((entry) => entry.trim()).filter(Boolean);
const stepLimits = {
  "open-shell": Number(process.env.GHOSTTRACE_E2E_MAX_OPEN_SHELL_MS || 2000),
  "theme-persistence": Number(process.env.GHOSTTRACE_E2E_MAX_THEME_MS || 2000),
  "quick-health": Number(process.env.GHOSTTRACE_E2E_MAX_QUICK_HEALTH_MS || 4000),
  "reconstruct-lane": Number(process.env.GHOSTTRACE_E2E_MAX_RECONSTRUCT_MS || 5000),
  "validate-lane": Number(process.env.GHOSTTRACE_E2E_MAX_VALIDATE_MS || 5000),
  "console-health": Number(process.env.GHOSTTRACE_E2E_MAX_CONSOLE_HEALTH_MS || 1000),
};

function fail(message) {
  throw new Error(message);
}

function getCompletedSteps(report) {
  return Array.isArray(report.steps)
    ? report.steps.filter((step) => step.status === "passed")
    : [];
}

function assertStepDurations(report) {
  const completedSteps = getCompletedSteps(report);
  for (const step of completedSteps) {
    if (typeof step.durationMs !== "number") {
      fail(`Missing durationMs for completed step "${step.name}".`);
    }
    const limit = stepLimits[step.name] ?? defaultStepLimitMs;
    if (step.durationMs > limit) {
      fail(`Step "${step.name}" exceeded its threshold: ${step.durationMs} ms > ${limit} ms.`);
    }
  }
}

function assertUiSnapshot(report) {
  const snapshot = report.uiSnapshot;
  if (!snapshot) {
    fail("Smoke report is missing uiSnapshot.");
  }
  if (snapshot.theme !== expectedTheme) {
    fail(`Expected final theme "${expectedTheme}", got "${snapshot.theme ?? "unknown"}".`);
  }
  if (!snapshot.activeJobTitle) {
    fail("Smoke report did not capture an active job title.");
  }
  if (snapshot.telemetry?.overall !== "healthy") {
    fail(`Expected healthy final telemetry state, got "${snapshot.telemetry?.overall ?? "unknown"}".`);
  }
  if (!snapshot.telemetry?.services || !snapshot.telemetry?.queues) {
    fail("Smoke report is missing final telemetry summaries.");
  }
  if (!snapshot.reconstruction?.focusText || !snapshot.reconstruction?.draftPreviewText) {
    fail("Smoke report is missing reconstruction snapshot content.");
  }
  if (!snapshot.x64dbg?.sessionStatus) {
    fail("Smoke report is missing x64dbg session status.");
  }
  if (!allowedX64dbgStates.includes(snapshot.x64dbg.sessionStatus)) {
    fail(`Unexpected x64dbg session state "${snapshot.x64dbg.sessionStatus}".`);
  }
  if (!snapshot.windowsLab?.username) {
    fail("Smoke report is missing Windows lab username.");
  }
  if (!snapshot.windowsLab?.status || !snapshot.windowsLab.status.toLowerCase().includes("revealed")) {
    fail("Smoke report does not show a successful Windows lab reveal state.");
  }
}

async function assertScreenshots(report) {
  const screenshots = Array.isArray(report.screenshots) ? report.screenshots : [];
  for (const screenshotName of expectedScreenshots) {
    if (!screenshots.includes(screenshotName)) {
      fail(`Smoke report is missing screenshot entry "${screenshotName}".`);
    }
    const screenshotPath = path.join(reportDir, screenshotName);
    let stats;
    try {
      stats = await fs.stat(screenshotPath);
    } catch {
      fail(`Expected screenshot artifact not found: ${screenshotPath}`);
    }
    if (!stats.isFile() || stats.size <= 0) {
      fail(`Screenshot artifact is empty or invalid: ${screenshotPath}`);
    }
  }
}

async function run() {
  const report = JSON.parse(await fs.readFile(reportPath, "utf8"));

  if (report.status !== "passed") {
    fail(`Smoke report status is "${report.status}", expected "passed".`);
  }
  if (typeof report.durationMs !== "number") {
    fail("Smoke report is missing total durationMs.");
  }
  if (report.durationMs > totalDurationLimitMs) {
    fail(`Smoke total duration exceeded threshold: ${report.durationMs} ms > ${totalDurationLimitMs} ms.`);
  }
  if (Array.isArray(report.pageErrors) && report.pageErrors.length > 0) {
    fail(`Smoke report contains ${report.pageErrors.length} page error(s).`);
  }
  if (Array.isArray(report.consoleMessages)) {
    const errorMessages = report.consoleMessages.filter((entry) => ["error", "assert"].includes(entry.type));
    if (errorMessages.length > 0) {
      fail(`Smoke report contains ${errorMessages.length} console error(s).`);
    }
  }
  if (!report.openedJob) {
    fail("Smoke report is missing openedJob.");
  }

  assertStepDurations(report);
  assertUiSnapshot(report);
  await assertScreenshots(report);

  console.log(`Release check passed for ${reportPath}`);
  console.log(`Total duration: ${report.durationMs} ms`);
  for (const step of getCompletedSteps(report)) {
    console.log(`- ${step.name}: ${step.durationMs} ms`);
  }
}

run().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
