import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

function extractBlock(css, startMarker) {
  const start = css.indexOf(startMarker);
  assert.notEqual(start, -1, `missing block start: ${startMarker}`);
  let depth = 0;
  for (let i = start; i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) return { body: css.slice(start, i + 1), end: i + 1 };
    }
  }
  throw new Error(`unclosed block: ${startMarker}`);
}

function declaredVariables(block) {
  return new Set(
    [...block.matchAll(/(--[a-z0-9-]+)\s*:/gi)].map((match) =>
      match[1].toLowerCase(),
    ),
  );
}

// Lines outside the variable-definition blocks that are allowed to keep a
// hex literal. Must stay empty: new literals need a variable instead.
const HEX_LITERAL_WHITELIST = [];

test("every :root theme variable has a dark-theme override", async () => {
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  const root = extractBlock(css, ":root {");
  const dark = extractBlock(css, '[data-theme="dark"] {');
  const rootVars = declaredVariables(root.body);
  const darkVars = declaredVariables(dark.body);

  assert.ok(rootVars.size > 0, ":root should declare theme variables");
  const missing = [...rootVars].filter((name) => !darkVars.has(name));
  assert.deepEqual(
    missing,
    [],
    `variables missing in [data-theme="dark"]: ${missing.join(", ")}`,
  );
});

test("no hex color literals outside the variable-definition blocks", async () => {
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  const root = extractBlock(css, ":root {");
  const dark = extractBlock(css, '[data-theme="dark"] {');
  const withoutBlocks = css.replace(root.body, "").replace(dark.body, "");

  const offenders = [];
  withoutBlocks.split("\n").forEach((line, index) => {
    const matches = line.match(/#[0-9a-fA-F]{3,8}\b/g);
    if (matches) {
      offenders.push(`${index + 1}: ${line.trim()}`);
    }
  });
  const unexpected = offenders.filter(
    (line) => !HEX_LITERAL_WHITELIST.some((allowed) => line.includes(allowed)),
  );
  assert.deepEqual(unexpected, [], `hex literals outside :root/dark blocks:\n${unexpected.join("\n")}`);
  assert.equal(
    HEX_LITERAL_WHITELIST.length,
    0,
    "the hex-literal whitelist must stay empty",
  );
});

test("system mode is resolved in JS, not by a CSS media-query fork", async () => {
  const [css, layout, profileSettings, workspaceApp] = await Promise.all([
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(
      new URL("../app/components/profile-settings-view.tsx", import.meta.url),
      "utf8",
    ),
    readFile(new URL("../app/workspace-app.tsx", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(css, /\[data-theme="system"\]/);
  assert.match(layout, /matchMedia\('\(prefers-color-scheme: dark\)'\)/);
  assert.match(layout, /dataset\.theme=d\?'dark':'light'/);
  assert.match(profileSettings, /root\.dataset\.theme = resolved/);
  // The live system-theme listener is registered exactly once, at the
  // always-mounted app root, so every view follows OS theme changes.
  assert.match(workspaceApp, /addEventListener\("change", followSystemTheme\)/);
  assert.match(workspaceApp, /removeEventListener\("change", followSystemTheme\)/);
  assert.doesNotMatch(profileSettings, /addEventListener\("change"/);
});
