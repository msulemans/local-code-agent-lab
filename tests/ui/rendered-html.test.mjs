import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const html = await readFile(new URL("../../learning/index.html", import.meta.url), "utf8");
const css = await readFile(new URL("../../learning/styles.css", import.meta.url), "utf8");
const js = await readFile(new URL("../../learning/app.js", import.meta.url), "utf8");

const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
assert.equal(new Set(ids).size, ids.length, "HTML IDs must be unique");

const requiredIds = [
  "main",
  "anatomy",
  "tools",
  "loop",
  "journey",
  "benchmark",
  "failures",
  "practice",
  "glossary",
  "anatomyMap",
  "toolTabs",
  "loopRail",
  "journeyNav",
  "configurationSelector",
  "failureList",
  "quizCard",
  "glossaryGrid",
];
for (const id of requiredIds) assert(ids.includes(id), `missing required #${id}`);

const staticAnchors = [...html.matchAll(/href="#([^"]+)"/g)].map((match) => match[1]);
for (const target of staticAnchors) assert(ids.includes(target), `anchor target #${target} must exist`);

assert.match(html, /<meta name="viewport"/);
assert.match(html, /<a class="skip-link"/);
assert.match(html, /aria-live="polite"/);
assert.doesNotMatch(html, /https?:\/\//, "learning UI must not depend on remote assets");
assert.doesNotMatch(html, /<script(?![^>]*src=)/, "inline scripts are not allowed");

assert.match(css, /@media \(max-width: 780px\)/);
assert.match(css, /prefers-reduced-motion: reduce/);
assert.match(css, /:focus-visible/);

assert.match(js, /localcode-learning-state-v1/);
assert.match(js, /const anatomy = \[/);
assert.match(js, /const tools = \[/);
assert.match(js, /const loopSteps = \[/);
assert.match(js, /const failures = \[/);
assert.match(js, /const flashcards = \[/);
assert.match(js, /const quiz = \[/);
assert.match(js, /const glossary = \[/);
assert.match(js, /truncated=true/);
assert.match(js, /qwen2\.5-coder:1\.5b-base/);
assert.match(js, /1\/20 observed/);
assert.match(js, /20 prompts/);
assert.match(js, /4\.15 GiB swap/);
assert.match(js, /0 tools executed/);
assert.match(js, /Offline gate passed/);
assert.match(js, /Preflight blocks unsafe inference/);
assert.match(js, /atomic recorder preserves every CLI outcome/);
assert.match(html, /B0\/A1\/A2\/A3 implemented/);
assert.match(html, /Luna post-repair resolved 1\/1/);
assert.match(html, /The first retrieval context treatment/);
assert.match(html, /issue → repo map → ranked excerpts → loop context/);
assert.match(js, /id: "apply_patch"/);
assert.match(js, /id: "run_tests"/);
assert.match(js, /micro suite 8\/8 retained/);
assert.match(js, /3612\.62 MiB/);
assert.match(js, /resource checks around every inference/);
assert.match(js, /headless\/TUI equivalence proved/);
assert.match(js, /LoopObserver/);
assert.match(js, /presentation from changing agent semantics/);
assert.match(js, /9\/9 expected changed paths recalled/);
assert.match(js, /parser context 1947 chars/);
assert.match(js, /explicit retrieval context compiler/);
assert.match(js, /Relevant-file recall/);
assert.match(html, /The measured ladder was <code>7 → 8 → 8 → 8<\/code>/);
assert.match(html, /ratio-retry/);
assert.match(js, /A1 8\/8 and A2 8\/8 on the micro suite/);
assert.match(js, /m-online-terra-requests-a3-v2/);
assert.match(js, /m-ladder3-terra-v1/);
assert.match(js, /pinned SWE-bench images/);
assert.match(js, /m-luna-requests-a3-fixed-v1/);
assert.match(js, /2,528 tokens/);
assert.match(js, /Tests are read-only during review/);
assert.match(js, /One patch decision/);

console.log(`learning UI contract passed: ${ids.length} unique static IDs`);
