const STORAGE_KEY = "localcode-learning-state-v1";

const lessons = [
  ["anatomy", "Anatomy"],
  ["tools", "Tool contracts"],
  ["loop", "Agent loop"],
  ["journey", "Milestones"],
  ["benchmark", "Benchmark"],
  ["failures", "Failures"],
  ["practice", "Practice"],
  ["glossary", "Glossary"],
];

const anatomy = [
  {
    id: "issue",
    label: "Issue",
    role: "Untrusted task description",
    summary: "The requested behavior, symptoms, and constraints enter the run as data. An issue can contain mistakes or malicious instructions, so it cannot change runtime policy.",
    owns: "The problem statement the agent must investigate.",
    never: "Permission to read secrets, escape the workspace, or weaken tests.",
    example: "“Calling parse_value(None) raises an exception.”",
  },
  {
    id: "controller",
    label: "Run controller",
    role: "Trusted state machine",
    summary: "The current controller accepts exactly one model response and dispatches at most one validated read-only tool. Later milestones add budgets, repeated-action detection, multiple turns, and termination rules. It—not the model—decides what actually runs.",
    owns: "Today: one backend call, validation, one tool dispatch, and events. Later: the full loop.",
    never: "Inventing repository evidence or letting the loop run forever.",
    example: "INSPECTING → EDITING → VERIFYING → COMPLETED",
  },
  {
    id: "context",
    label: "Context compiler",
    role: "Bounded evidence packer",
    summary: "It selects the issue, recent events, file excerpts, failures, and remaining budgets that fit into the next model request.",
    owns: "Selection, line numbers, deduplication, truncation notices, and token limits.",
    never: "Treating repository text as trusted system instructions.",
    example: "Issue + 2 excerpts + latest test failure + 6 steps remaining",
  },
  {
    id: "model",
    label: "Local model",
    role: "Probabilistic strategist",
    summary: "A local coding instruct model predicts the next structured action or a final response from the context it receives.",
    owns: "Hypotheses, action proposals, and concise rationale.",
    never: "Direct filesystem or shell authority, benchmark truth, or policy enforcement.",
    example: "Propose search_code(query='parse_value', path='.')",
  },
  {
    id: "validator",
    label: "Action validator",
    role: "Protocol checkpoint",
    summary: "It parses a versioned action envelope, rejects malformed or unknown calls, checks types and sizes, and applies policy before execution.",
    owns: "Schema correctness and the final allow/reject decision.",
    never: "Optimistically executing a partly understood model response.",
    example: "unknown tool → typed invalid_action observation",
  },
  {
    id: "tools",
    label: "Tool registry",
    role: "Narrow capabilities",
    summary: "Each tool performs one semantic job with explicit arguments, limits, output shape, and failure codes. A general terminal is not a substitute for missing tool design.",
    owns: "Safe execution and bounded observations.",
    never: "Expanding permissions because the model asks persuasively.",
    example: "read_file(path, start_line, end_line) → ToolResult",
  },
  {
    id: "events",
    label: "Event store",
    role: "Immutable flight recorder",
    summary: "Every accepted action, tool result, state change, budget snapshot, and termination becomes a structured event. Large artifacts are referenced by hash rather than dumped into context.",
    owns: "Chronology and reproducible evidence.",
    never: "Logging credentials, hidden reasoning, or unbounded raw output.",
    example: "schema_version + run_id + sequence + observation + budgets",
  },
  {
    id: "evaluator",
    label: "Evaluator",
    role: "Independent judge",
    summary: "The benchmark harness applies the final patch in a controlled environment and runs required tests. It remains outside the agent boundary.",
    owns: "The resolved/not-resolved verdict.",
    never: "Sharing gold patches or evaluator-only tests with the agent.",
    example: "model_patch → container → tests → resolved: true/false",
  },
];

const tools = [
  {
    id: "list_files",
    title: "Map the repository",
    description: "Returns allowed repository-relative files in stable lexical order. It prunes excluded directories and stops traversing beyond the requested depth.",
    call: 'list_files(path=".", max_depth=4, max_results=200)',
    output: "ISSUE.md\nsrc/tiny_parser.py\ntests/test_tiny_parser.py",
    limits: [["Results", "≤ 1,000"], ["Depth", "≤ 20"], ["Order", "Stable lexical"]],
  },
  {
    id: "search_code",
    title: "Find evidence by text",
    description: "Searches allowed UTF-8 files with literal or regex matching. It reports file, line number, and a bounded preview—not entire files.",
    call: 'search_code(query="text.strip", path=".", glob="*.py")',
    output: "src/tiny_parser.py:2:     return text.strip()",
    limits: [["Matches", "≤ 200"], ["Files", "≤ 5,000"], ["Bytes scanned", "≤ 16 MiB"]],
  },
  {
    id: "read_file",
    title: "Read one bounded excerpt",
    description: "Returns line-numbered UTF-8 text from one allowed regular file. Binary files and inputs larger than one MiB are rejected.",
    call: 'read_file(path="src/tiny_parser.py", start_line=1, end_line=40)',
    output: "     1 | def parse_value(text: str | None) -> str:\n     2 |     return text.strip()",
    limits: [["Input", "≤ 1 MiB"], ["Lines", "≤ 1,000"], ["Output", "≤ 65,536 chars"]],
  },
  {
    id: "git_diff",
    title: "Inspect the tracked patch",
    description: "Returns a staged or unstaged tracked diff after filtering changed filenames. External diff and text-conversion helpers are disabled.",
    call: 'git_diff(path=".", staged=false, max_bytes=65536)',
    output: "[empty]\nThe lab has no tracked baseline commit yet.\nTemporary committed fixtures prove safe diff behavior.",
    limits: [["Output", "≤ 65,536 bytes"], ["Timeout", "10 seconds"], ["Untracked", "Not included"]],
  },
];

const safetyScenarios = [
  { id: "safe", label: "Safe request", mode: "SAFE REQUEST" },
  { id: "traversal", label: "../ traversal", mode: "REJECTED", code: "path_escape", output: "path must stay within the repository" },
  { id: "secret", label: ".env secret", mode: "REJECTED", code: "excluded_path", output: "path is excluded by policy (secret-like filename): .env" },
  { id: "symlink", label: "Symlink", mode: "REJECTED", code: "symlink_rejected", output: "symlink paths are not readable: src/link.py" },
  { id: "truncated", label: "Result limit", mode: "BOUNDED", code: "truncated=true", output: "Observation stopped at the configured limit. Narrow the next request." },
];

const loopSteps = [
  {
    state: "CREATED",
    title: "Receive the issue",
    body: "The runtime records the task and starting repository identity. The issue is untrusted content; it cannot grant new capabilities.",
    hypothesis: "We need evidence before proposing a fix.",
    next: "List the small fixture repository.",
    capability: "available",
    event: { event_type: "run_created", state: "created", summary: "Parser issue registered.", budgets_remaining: { steps: 12, tokens: 4096 } },
  },
  {
    state: "INSPECTING",
    title: "Map the repository",
    body: "The model proposes list_files. The validator checks its arguments, then the tool returns three allowed paths.",
    hypothesis: "Implementation and tests are both visible.",
    next: "Search for the named function.",
    capability: "available",
    event: { event_type: "tool_result", state: "inspecting", summary: "list_files returned 3 paths; truncated=false.", budgets_remaining: { steps: 11, tokens: 3820 } },
  },
  {
    state: "INSPECTING",
    title: "Search and read",
    body: "Search finds parse_value on line 1. A bounded read shows line 2 calling strip directly on a possibly absent value.",
    hypothesis: "None reaches text.strip() without a guard.",
    next: "Form a minimal edit and inspect the test.",
    capability: "available",
    event: { event_type: "tool_result", state: "inspecting", summary: "Relevant implementation localized to src/tiny_parser.py:1-2.", budgets_remaining: { steps: 9, tokens: 3310 } },
  },
  {
    state: "EDITING",
    title: "Apply a guarded patch",
    body: "A future apply_patch tool will validate a unified diff, reject path escape and excessive scope, and apply only inside a disposable workspace.",
    hypothesis: "Return an empty string when text is None; preserve strip otherwise.",
    next: "Compile or run the narrowest relevant test.",
    capability: "planned",
    event: { event_type: "planned_action", state: "editing", summary: "apply_patch is not implemented in Milestone 003.", budgets_remaining: { steps: 8, tokens: 2980 } },
  },
  {
    state: "VERIFYING",
    title: "Run targeted tests",
    body: "A constrained test tool will use an approved command, timeout, isolated process, and bounded output. Exit code and exact command become evidence.",
    hypothesis: "The None regression should pass without harming trimming.",
    next: "Interpret the failure or broaden verification.",
    capability: "planned",
    event: { event_type: "planned_action", state: "verifying", summary: "run_tests is not implemented in Milestone 003.", budgets_remaining: { steps: 6, tokens: 2350 } },
  },
  {
    state: "REVIEWING",
    title: "Review the patch",
    body: "A fresh reviewer sees the issue, current diff, and test evidence. It may accept, request one bounded revision, or reject.",
    hypothesis: "The patch is narrow, tested, and matches the issue.",
    next: "Return a final diff or one revision request.",
    capability: "planned",
    event: { event_type: "planned_action", state: "reviewing", summary: "Reviewer treatment is reserved for the final benchmark configuration.", budgets_remaining: { steps: 3, tokens: 1180 } },
  },
  {
    state: "COMPLETED",
    title: "Hand off evidence",
    body: "The final answer reports changed files, exact tests, limitations, and a reviewable Git diff. The independent evaluator—not the agent—decides benchmark resolution.",
    hypothesis: "The requested behavior is implemented under the recorded test contract.",
    next: "Submit only the patch to the evaluator.",
    capability: "planned",
    event: { event_type: "run_completed", state: "completed", summary: "Patch ready for independent evaluation.", budgets_remaining: { steps: 2, tokens: 640 } },
  },
];

const milestones = [
  {
    id: "001",
    state: "Verified",
    title: "Environment capability",
    story: "We checked the actual M2 Max rather than assuming CUDA, package versions, or Docker capacity. MLX and PyTorch MPS both completed real Metal calculations outside the sandbox.",
    evidence: "M2 Max · 32 GB · Python 3.11.9 · Metal result 54.0",
    decision: "Local inference is viable; full SWE-bench remains pilot-only until Docker constraints are proven.",
  },
  {
    id: "002",
    state: "Verified",
    title: "Repository and event contract",
    story: "We built configuration and immutable event primitives without a model. This separated trusted runtime state from the untrusted repository fixture.",
    evidence: "12 tests passed · canonical JSON round-trip true",
    decision: "Proceed only after the laboratory bench is deterministic.",
  },
  {
    id: "003",
    state: "Verified",
    title: "Read-only tool layer",
    story: "Four repository tools now share one exclusion policy and return bounded immutable observations. Adversarial cases cover traversal, symlinks, secrets, binaries, size, truncation, and Git behavior.",
    evidence: "28 tests passed · fixture list/search/read proof",
    decision: "The runtime has eyes. It still has no hands and no model.",
  },
  {
    id: "004",
    state: "No candidate passed",
    title: "Local model bake-off · stages A–B",
    story: "In candidate 1 v1, 1/20 observed before 4.15 GiB swap growth triggered the safety stop. Its clean v2 completed all prompts but failed quality. Candidate 2 then made one native tool call before 2.53 GiB swap growth triggered the same frozen limit from a clean host.",
    evidence: "20 prompts frozen · candidate 1: 0/12 schema, 1/16 decisions, 3/4 reasoning · candidate 2: 1/1 schema observed, 2.53 GiB swap · 0 tools executed",
    decision: "Neither original candidate passes. The separate Qwen3.5 9B extension is downloaded and fully hash-verified; a clean restart baseline is required before its one guarded run.",
  },
  {
    id: "005",
    state: "Offline gate passed",
    title: "Protocol and one-turn controller",
    story: "A fake Ollama-shaped response now crosses the local backend adapter, strict validator, exact registry, and one real read-only fixture tool. Success or rejection becomes an immutable event plus observation.",
    evidence: "61 tests passed · complete fake-Ollama bridge · malformed/oversized/ambiguous actions observed · deterministic trace",
    decision: "Keep the real Qwen3.5 smoke test deferred until a clean restart. Do not weaken the resource baseline or pretend the fake backend proves model compatibility.",
  },
];

const configurations = [
  { id: "B0", label: "Single-shot base", score: 0, change: "No tools or retry", body: "The fixed local model sees the issue and a bounded repository map, then gets one chance to return a patch. This is the untreated control." },
  { id: "A1", label: "Simple agent", score: 3, change: "+ tool loop", body: "The same model can list, search, read, edit, test, observe failures, and retry under a fixed total budget." },
  { id: "A2", label: "Retrieval agent", score: 7, change: "+ ranked context", body: "A1 gains deliberate repository mapping, symbol/caller/test proximity, deduplication, and context allocation. The model and total budget stay fixed." },
  { id: "A3", label: "Agent + review", score: 9, change: "+ fresh critique", body: "A2 gains a fresh reviewer that sees issue, diff, and test evidence. It may request at most one bounded revision." },
];

const fairnessControls = [
  "Same model checkpoint and quantization",
  "Same 20 pinned issue IDs and base commits",
  "Same generated-token allowance",
  "Same tool/context allowance",
  "Same timeouts and patch limits",
  "Same evaluator and container resources",
  "No gold patch or hidden test leakage",
  "Rerun every configuration after protocol changes",
];

const failures = [
  {
    type: "protocol",
    title: "Model text is not automatically a tool call",
    symptom: "The backend returns prose, malformed JSON, or a tool name the runtime does not know.",
    diagnosis: "Generation succeeded, but the response did not satisfy the versioned action contract.",
    lesson: "Turn rejection into a typed observation and execute nothing. Do not guess what the model probably meant.",
  },
  {
    type: "environment",
    title: "Metal disappeared inside the sandbox",
    symptom: "MLX reported no Metal device and PyTorch reported MPS unavailable.",
    diagnosis: "The restricted/headless process could not see the GPU. The same environments completed real matrix multiplication outside the sandbox.",
    lesson: "A failed capability check may describe the execution boundary rather than the machine. Prove the exact operation in the correct environment.",
  },
  {
    type: "test design",
    title: "The “non-repository” was still a Git repository",
    symptom: "A test expected git_diff to raise, but Git returned normally.",
    diagnosis: "The directory was nested inside a parent working tree, so Git correctly inherited repository membership.",
    lesson: "Validate fixture assumptions. We now require the policy root to equal Git’s top-level root and test a truly unrelated directory separately.",
  },
  {
    type: "security",
    title: "Read-only can still disclose credentials",
    symptom: "A generic file reader could return .env, private keys, Git internals, or credential directories.",
    diagnosis: "“Does not write” says nothing about confidentiality, context poisoning, or excessive output.",
    lesson: "Every semantic tool needs path exclusions, size limits, symlink rules, and explicit failure codes.",
  },
  {
    type: "reasoning",
    title: "A truncated observation looked complete",
    symptom: "The model reasoned as if the first 40 search matches represented the entire repository.",
    diagnosis: "The observation omitted its scope or the controller failed to preserve the truncation flag.",
    lesson: "Truncation is evidence. Return it structurally and require a narrower follow-up before broad conclusions.",
  },
  {
    type: "model",
    title: "A local Qwen file was mistaken for the selected model",
    symptom: "An existing qwen2.5-coder:1.5b-base artifact looked like a free shortcut.",
    diagnosis: "It is a small quantized base checkpoint. Local availability does not prove instruction following, tool-call validity, or repository reasoning.",
    lesson: "Register compatibility criteria first. Choose the smallest model that passes, not the first model already on disk.",
  },
  {
    type: "benchmark",
    title: "Host disk hid Docker constraints",
    symptom: "207 GiB free suggested SWE-bench was ready.",
    diagnosis: "Docker had only 7.75 GiB RAM, existing images/cache already occupied substantial storage, and ARM evaluation remains experimental.",
    lesson: "Benchmark readiness includes container architecture, memory, image budget, gold controls, and evaluator fidelity—not one host metric.",
  },
];

const flashcards = [
  ["What turns a local coding model into an agent?", "A trusted runtime repeatedly compiles context, validates a structured action, executes one allowed tool, records the observation, enforces budgets, and decides whether to continue or stop."],
  ["What happens when the model emits invalid JSON?", "The validator returns a typed action_rejected observation. No repository tool runs, and a future bounded loop may show that observation to the model for a retry."],
  ["Why is the model not allowed to call the filesystem directly?", "The model is probabilistic and repository text is untrusted. A validated tool boundary enforces paths, exclusions, sizes, output limits, and permission independently of what the model requests."],
  ["What is an observation?", "A bounded factual result produced by the runtime after an allowed action—for example a line-numbered file excerpt, search matches, a test exit code, or a Git diff."],
  ["Why keep an immutable event trace?", "It makes the run diagnosable and reproducible: we can see the issue, action, observation, state, artifacts, and remaining budgets in order without rewriting history."],
  ["What does truncated=true mean?", "The returned observation is incomplete because a safety or context limit was reached. The agent should narrow its next request rather than infer that unseen evidence does not exist."],
  ["Why is a passing targeted test not automatically enough?", "It proves only that command under that environment. The required broader evaluator may contain regression or issue-specific tests that still fail."],
  ["What is retrieval in this project?", "A controlled method for choosing the most relevant repository map, symbols, callers, tests, and excerpts under a fixed context budget. It is not simply adding more files."],
  ["Who decides whether a SWE-bench issue is resolved?", "The independent SWE-bench evaluator after applying the final model patch and running required tests in its container—not the agent’s final message."],
  ["Why compare B0, A1, A2, and A3 on the same issues?", "Holding model, tasks, and budgets fixed lets us attribute paired outcome changes to the loop, retrieval, or review rather than to an easier subset or more compute."],
  ["What makes this more than an API wrapper?", "We own the controller, tool schemas, validation, context assembly, safety policy, event history, budgets, retry logic, evaluation integration, and UI. The model backend supplies only local token generation."],
];

const quiz = [
  {
    q: "The model emits `{ tool: 'read_file', path: '../.ssh/id_rsa' }`. What happens?",
    options: ["The prompt decides", "The path validator rejects it before reading", "The model retries with sudo", "The file is summarized"],
    answer: 1,
    why: "Runtime policy—not model intent—prevents traversal and credential access before any content is opened.",
  },
  {
    q: "A search returns 40 matches with truncated=true. What may the agent conclude?",
    options: ["Only 40 matches exist", "The remaining files are irrelevant", "The observation is incomplete and needs narrowing", "The issue cannot be solved"],
    answer: 2,
    why: "The limit is part of the observation contract. Unseen matches may still matter.",
  },
  {
    q: "Which component owns tool-call permission?",
    options: ["Local model", "Issue text", "Action validator and runtime policy", "SWE-bench dataset"],
    answer: 2,
    why: "The model proposes; the validator and policy decide whether execution is permitted.",
  },
  {
    q: "What has LocalCode actually implemented in the offline part of Milestone 005?",
    options: ["A full autonomous agent", "A strict one-turn controller over four bounded read-only tools", "Editing and test retries", "SWE-bench resolution"],
    answer: 1,
    why: "The validator, exact registry, one backend call, one tool call, observations, and deterministic events are real. Multi-turn retries, editing, test execution, and the Qwen3.5 smoke remain pending.",
  },
  {
    q: "Why is qwen2.5-coder:1.5b-base not selected automatically?",
    options: ["Qwen cannot code", "It is too large", "Availability is not evidence of instruct/tool compatibility", "Only cloud models support tools"],
    answer: 2,
    why: "The checkpoint is a base model; the bake-off must measure action validity, context, speed, memory, and code reasoning.",
  },
  {
    q: "A1 solves a task that B0 failed. What is the strongest immediate statement?",
    options: ["The loop caused the improvement on that paired task", "All agents are better", "The model was retrained", "Retrieval is proven"],
    answer: 0,
    why: "Under frozen controls, the paired transition supports the simple loop treatment for that instance. It does not yet prove broad generalization or retrieval.",
  },
  {
    q: "The agent says 'all tests pass,' but records no command or exit code. What is true?",
    options: ["The issue is resolved", "The model is probably right", "There is no verification evidence", "The patch should be published"],
    answer: 2,
    why: "A claim is not an observation. Verification needs the exact command, environment, exit code, and bounded output.",
  },
  {
    q: "Who may see the SWE-bench gold patch during a scored run?",
    options: ["The retrieval system", "The reviewer", "The independent evaluator only", "The model after one failed test"],
    answer: 2,
    why: "Gold and evaluator-only test material must remain outside agent context or the benchmark is contaminated.",
  },
];

const glossary = [
  ["Action", "A structured proposal from the model to call one named tool with validated arguments, or to finish the run."],
  ["Action validator", "Trusted code that parses the model response, enforces the protocol schema, and rejects unknown or unsafe calls before execution."],
  ["Agent", "A model plus a runtime loop, tools, observations, memory/context, budgets, policy, and termination rules."],
  ["Agent loop", "The repeated sequence: compile context, ask the model, validate an action, execute a tool, record an observation, and decide whether to continue."],
  ["Artifact", "A larger persisted output such as a patch, test log, or context snapshot referenced from an event by path and hash."],
  ["Base commit", "The exact repository revision from which an issue run starts. Every compared configuration must use the same one."],
  ["Base model", "A pretrained next-token model without the instruction tuning expected for reliable conversational or tool-following behavior."],
  ["Benchmark harness", "Independent infrastructure that applies proposed patches and runs the official tests under a reproducible environment."],
  ["Budget", "A hard allowance such as remaining steps, generated tokens, tool bytes, tests, or wall-clock time."],
  ["Canonical JSON", "A deterministic JSON representation with stable key ordering and separators, useful for exact comparison and hashing."],
  ["Context", "The bounded information supplied to the model for one decision: instructions, issue, selected evidence, recent events, and remaining budgets."],
  ["Context compiler", "The component that selects, deduplicates, numbers, truncates, and packages evidence for the next model request."],
  ["Controller", "The trusted state machine that owns turns, budgets, tool dispatch, retry rules, termination, and final run status."],
  ["Diff", "A line-oriented representation of changes relative to a Git baseline. It is evidence of edits, not proof that tests pass."],
  ["Event", "One immutable structured fact in a run trace, identified by run, sequence, type, state, timestamp, summary, artifacts, and budgets."],
  ["Gold patch", "The known reference fix used by benchmark maintainers and controls. It must remain hidden from the scored agent."],
  ["Instruct model", "A model post-trained to follow instructions, produce useful responses, and often conform to tool-call formats."],
  ["Model backend", "The replaceable local inference adapter responsible for tokenization and generation—not tools, policy, retries, or evaluation."],
  ["Mixture of experts", "A model architecture that stores many parameter groups but activates only some per token. Low active parameters can reduce compute, but all quantized weights still consume storage and memory."],
  ["Observation", "A bounded factual result returned after an allowed action, such as file lines, search matches, a test result, or a diff."],
  ["Patch", "The proposed file changes produced by the agent. An evaluator can apply the patch without receiving the agent’s private trace."],
  ["Prompt injection", "Untrusted text that tries to override higher-priority runtime instructions or persuade the agent to perform unsafe actions."],
  ["Quantization", "Representing model weights with fewer bits to reduce memory and often increase local inference speed, with possible quality tradeoffs."],
  ["Artifact digest", "A content-derived hash used to identify the exact downloaded model manifest or blob. A short tag or web-page prefix is not the final local proof."],
  ["Repository policy", "The shared rules for allowed paths, excluded secrets/artifacts, symlinks, sizes, and output bounds."],
  ["Resolved", "The benchmark evaluator’s verdict that a submitted patch satisfies the required issue tests without prohibited regressions."],
  ["Retrieval", "Selecting the most useful repository evidence under a fixed context budget using maps, symbols, callers, tests, and ranking."],
  ["Reviewer", "A fresh critique pass that sees the issue, current patch, and test evidence and may accept, reject, or request one bounded revision."],
  ["Run trace", "The ordered collection of structured events and artifact references that explains what the agent observed and did."],
  ["Sandbox", "A restricted execution boundary that limits filesystem, devices, network, credentials, or processes. Its visibility may differ from the host."],
  ["Schema", "A versioned contract defining required fields, types, limits, and allowed values for configuration, events, actions, or results."],
  ["SWE-bench", "A benchmark of real GitHub issues where systems produce patches that are independently applied and tested in repository environments."],
  ["Termination condition", "An explicit rule that stops a run for success, safe failure, blocked evaluation, repeated behavior, or exhausted budget."],
  ["Test patch", "Evaluator-only tests added to check the requested behavior. It must not be exposed to the scored agent."],
  ["Tool", "A narrow runtime capability with named arguments, validation, limits, execution semantics, and a bounded result."],
  ["ToolResult", "LocalCode’s immutable read-only observation containing text content, a truncation flag, and scalar metadata."],
  ["Truncation", "A structural signal that an observation stopped at a configured file, byte, line, result, or context limit."],
  ["Workspace", "A disposable repository copy or worktree where a run may safely inspect and later modify files without touching the user’s primary checkout."],
];

function loadState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return {
      completed: Array.isArray(parsed.completed) ? parsed.completed : [],
      deep: parsed.deep === true,
      last: typeof parsed.last === "string" ? parsed.last : "#anatomy",
      bestQuiz: Number.isFinite(parsed.bestQuiz) ? parsed.bestQuiz : 0,
    };
  } catch {
    return { completed: [], deep: false, last: "#anatomy", bestQuiz: 0 };
  }
}

let state = loadState();

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderLessonProgress() {
  const nav = document.querySelector("#lessonNav");
  nav.innerHTML = lessons.map(([id, label], index) => {
    const complete = state.completed.includes(id);
    return `<li class="${complete ? "complete" : ""}"><a href="#${id}"><i>${complete ? "✓" : String(index + 1).padStart(2, "0")}</i>${label}</a></li>`;
  }).join("");
  const percent = Math.round((state.completed.length / lessons.length) * 100);
  document.querySelector("#progressValue").textContent = `${percent}%`;
  document.querySelector("#progressBar").style.width = `${percent}%`;
  document.querySelectorAll("[data-complete]").forEach((button) => {
    const complete = state.completed.includes(button.dataset.complete);
    button.classList.toggle("done", complete);
    button.querySelector("span").textContent = complete ? "✓" : "+";
    button.lastChild.textContent = complete ? " Lesson completed" : " Mark lesson complete";
  });
}

document.querySelectorAll("[data-complete]").forEach((button) => {
  button.addEventListener("click", () => {
    const id = button.dataset.complete;
    state.completed = state.completed.includes(id)
      ? state.completed.filter((item) => item !== id)
      : [...state.completed, id];
    saveState();
    renderLessonProgress();
  });
});
renderLessonProgress();

const depthToggle = document.querySelector("#depthToggle");
function applyDepth() {
  document.body.classList.toggle("deep-mode", state.deep);
  depthToggle.setAttribute("aria-pressed", String(state.deep));
  depthToggle.lastChild.textContent = state.deep ? " Hide deeper notes" : " Show deeper notes";
}
depthToggle.addEventListener("click", () => {
  state.deep = !state.deep;
  saveState();
  applyDepth();
});
applyDepth();

const anatomyMap = document.querySelector("#anatomyMap");
anatomy.forEach((item, index) => {
  const button = document.createElement("button");
  button.type = "button";
  button.role = "tab";
  button.dataset.component = item.id;
  button.setAttribute("aria-selected", String(index === 0));
  button.innerHTML = `<span>${String(index + 1).padStart(2, "0")}</span><strong>${item.label}</strong>`;
  button.addEventListener("click", () => selectAnatomy(item.id));
  anatomyMap.append(button);
});

function selectAnatomy(id) {
  const item = anatomy.find((candidate) => candidate.id === id) || anatomy[0];
  anatomyMap.querySelectorAll("button").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.component === item.id)));
  document.querySelector("#anatomyDetail").innerHTML = `
    <span>${item.role.toUpperCase()}</span>
    <h3>${item.label}</h3>
    <p>${item.summary}</p>
    <div class="ownership-grid">
      <div><span>OWNS</span><strong>${item.owns}</strong></div>
      <div><span>MUST NEVER OWN</span><strong>${item.never}</strong></div>
      <div><span>CONCRETE EXAMPLE</span><p><code>${escapeHtml(item.example)}</code></p></div>
      <div><span>BOUNDARY QUESTION</span><p>Could this component change policy, execute code, or declare success? If not, which component can?</p></div>
    </div>`;
}
selectAnatomy("controller");

let selectedTool = "list_files";
let selectedScenario = "safe";
const toolTabs = document.querySelector("#toolTabs");
tools.forEach((tool) => {
  const button = document.createElement("button");
  button.type = "button";
  button.role = "tab";
  button.dataset.tool = tool.id;
  button.textContent = tool.id;
  button.addEventListener("click", () => {
    selectedTool = tool.id;
    selectedScenario = "safe";
    renderTool();
  });
  toolTabs.append(button);
});

const scenarioButtons = document.querySelector("#scenarioButtons");
safetyScenarios.forEach((scenario) => {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.scenario = scenario.id;
  button.textContent = scenario.label;
  button.addEventListener("click", () => {
    selectedScenario = scenario.id;
    renderTool();
  });
  scenarioButtons.append(button);
});

function renderTool() {
  const tool = tools.find((candidate) => candidate.id === selectedTool) || tools[0];
  const scenario = safetyScenarios.find((candidate) => candidate.id === selectedScenario) || safetyScenarios[0];
  toolTabs.querySelectorAll("button").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.tool === tool.id)));
  scenarioButtons.querySelectorAll("button").forEach((button) => button.classList.toggle("active", button.dataset.scenario === scenario.id));
  document.querySelector("#toolTitle").textContent = tool.title;
  document.querySelector("#toolDescription").textContent = tool.description;
  document.querySelector("#toolLimits").innerHTML = tool.limits.map(([name, value]) => `<div><dt>${name}</dt><dd>${value}</dd></div>`).join("");
  const truncatedCalls = {
    list_files: 'list_files(path=".", max_results=1)',
    search_code: 'search_code(query="text.strip", path=".", max_results=1)',
    read_file: 'read_file(path="src/tiny_parser.py", max_lines=1)',
    git_diff: 'git_diff(path=".", max_bytes=80)',
  };
  const toolCall = scenario.id === "safe" ? tool.call : scenario.id === "traversal" ? `${tool.id}(path="../outside")` : scenario.id === "secret" ? `${tool.id}(path=".env")` : scenario.id === "symlink" ? `${tool.id}(path="src/link.py")` : truncatedCalls[tool.id];
  document.querySelector("#toolCall").textContent = toolCall;
  const mode = document.querySelector("#toolMode");
  mode.textContent = scenario.mode;
  mode.classList.toggle("danger", scenario.id !== "safe" && scenario.id !== "truncated");
  document.querySelector("#toolOutput").textContent = "Select a tool, then run the observation.";
  document.querySelector("#toolStatus").textContent = "READY";
  document.querySelector("#toolStatus").classList.remove("error");
}

document.querySelector("#runToolDemo").addEventListener("click", () => {
  const tool = tools.find((candidate) => candidate.id === selectedTool) || tools[0];
  const scenario = safetyScenarios.find((candidate) => candidate.id === selectedScenario) || safetyScenarios[0];
  const status = document.querySelector("#toolStatus");
  const output = document.querySelector("#toolOutput");
  if (scenario.id === "safe") {
    status.textContent = "ALLOWED · truncated=false";
    status.classList.remove("error");
    output.textContent = tool.output;
  } else if (scenario.id === "truncated") {
    status.textContent = "ALLOWED · truncated=true";
    status.classList.remove("error");
    output.textContent = `[${scenario.code}]\n${scenario.output}`;
  } else {
    status.textContent = `REJECTED · ${scenario.code}`;
    status.classList.add("error");
    output.textContent = `[ToolError: ${scenario.code}]\n${scenario.output}\n\nNo file content was read.`;
  }
});
renderTool();

const loopRail = document.querySelector("#loopRail");
loopSteps.forEach((step, index) => {
  const button = document.createElement("button");
  button.type = "button";
  button.role = "tab";
  button.dataset.loop = String(index);
  button.setAttribute("aria-selected", String(index === 0));
  button.innerHTML = `<span>${String(index + 1).padStart(2, "0")}</span><strong>${step.title}</strong>`;
  button.addEventListener("click", () => selectLoopStep(index));
  loopRail.append(button);
});

function selectLoopStep(index) {
  const step = loopSteps[index] || loopSteps[0];
  loopRail.querySelectorAll("button").forEach((button) => button.setAttribute("aria-selected", String(Number(button.dataset.loop) === index)));
  document.querySelector("#loopDetail").innerHTML = `
    <span>${step.state}</span>
    <h3>${step.title}</h3>
    <p>${step.body}</p>
    <div class="loop-decision"><div><span>CURRENT HYPOTHESIS</span><strong>${step.hypothesis}</strong></div><div><span>NEXT DECISION</span><strong>${step.next}</strong></div></div>
    <span class="capability-chip ${step.capability === "planned" ? "planned" : ""}">${step.capability === "planned" ? "Planned capability" : "Implemented foundation"}</span>`;
  document.querySelector("#eventSequence").textContent = `SEQ ${String(index).padStart(3, "0")}`;
  const event = {
    schema_version: 1,
    run_id: "learning-demo",
    sequence: index,
    timestamp: "2026-08-08T10:00:00+10:00",
    artifact_refs: [],
    ...step.event,
  };
  document.querySelector("#eventJson").textContent = JSON.stringify(event, null, 2);
}
selectLoopStep(0);

const journeyNav = document.querySelector("#journeyNav");
milestones.forEach((item, index) => {
  const entry = document.createElement("li");
  entry.innerHTML = `<button type="button" data-milestone="${item.id}" data-step="${item.id}" aria-selected="${index === 0}"><span>${item.state}</span><strong>${item.title}</strong></button>`;
  entry.querySelector("button").addEventListener("click", () => selectMilestone(item.id));
  journeyNav.append(entry);
});

function selectMilestone(id) {
  const item = milestones.find((candidate) => candidate.id === id) || milestones[0];
  journeyNav.querySelectorAll("button").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.milestone === item.id)));
  document.querySelector("#journeyDetail").innerHTML = `
    <span>${item.state}</span>
    <h3>${item.id} · ${item.title}</h3>
    <p>${item.story}</p>
    <div class="journey-evidence"><div><span>OBSERVED EVIDENCE</span><strong>${item.evidence}</strong></div><div><span>DECISION</span><strong>${item.decision}</strong></div></div>`;
}
selectMilestone("005");

const configurationSelector = document.querySelector("#configurationSelector");
configurations.forEach((configuration, index) => {
  const button = document.createElement("button");
  button.type = "button";
  button.role = "tab";
  button.dataset.configuration = configuration.id;
  button.setAttribute("aria-selected", String(index === 0));
  button.innerHTML = `<span>${configuration.id}</span><strong>${configuration.label}</strong>`;
  button.addEventListener("click", () => selectConfiguration(configuration.id));
  configurationSelector.append(button);
});

function selectConfiguration(id) {
  const configuration = configurations.find((item) => item.id === id) || configurations[0];
  configurationSelector.querySelectorAll("button").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.configuration === configuration.id)));
  document.querySelector("#configurationDetail").innerHTML = `
    <span>${configuration.id} · CONTROLLED TREATMENT</span>
    <h3>${configuration.label}</h3>
    <p>${configuration.body}</p>
    <div class="capability-delta"><span>ONLY NAMED CHANGE</span><strong>${configuration.change}</strong></div>`;
}
selectConfiguration("B0");

document.querySelector("#scoreBars").innerHTML = configurations.map((configuration) => `
  <div class="score-bar"><div><i style="--height:${Math.max(3, configuration.score * 9)}%"></i><strong>${configuration.score}/20</strong></div><span>${configuration.id} · ${configuration.label}</span></div>`).join("");

const fairnessChecklist = document.querySelector("#fairnessChecklist");
fairnessChecklist.innerHTML = fairnessControls.map((control, index) => `<label><input type="checkbox" data-control="${index}"><span>${control}</span></label>`).join("");
fairnessChecklist.addEventListener("change", () => {
  const inputs = [...fairnessChecklist.querySelectorAll("input")];
  const checked = inputs.filter((input) => input.checked).length;
  const verdict = document.querySelector("#fairnessVerdict");
  verdict.classList.toggle("ready", checked === inputs.length);
  verdict.textContent = checked === inputs.length
    ? "Comparison contract complete: the named capability can be interpreted."
    : `${checked}/${inputs.length} controls frozen. Unchecked differences can confound the result.`;
});

const failureTypes = ["all", ...new Set(failures.map((failure) => failure.type))];
let activeFailureType = "all";
const failureFilters = document.querySelector("#failureFilters");
failureTypes.forEach((type) => {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.failureType = type;
  button.textContent = type;
  button.classList.toggle("active", type === "all");
  button.addEventListener("click", () => {
    activeFailureType = type;
    failureFilters.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item.dataset.failureType === type));
    renderFailures();
  });
  failureFilters.append(button);
});

function renderFailures() {
  const visible = failures.filter((failure) => activeFailureType === "all" || failure.type === activeFailureType);
  document.querySelector("#failureList").innerHTML = visible.map((failure, index) => `
    <article class="failure-item">
      <button type="button" aria-expanded="false" aria-controls="failure-${index}">
        <span class="failure-type">${failure.type}</span><span class="failure-title">${failure.title}</span><span class="failure-toggle">+</span>
      </button>
      <div class="failure-body" id="failure-${index}" hidden>
        <div><span>SYMPTOM</span><p>${failure.symptom}</p></div>
        <div><span>DIAGNOSIS</span><p>${failure.diagnosis}</p></div>
        <div><span>WHAT TO REUSE</span><p>${failure.lesson}</p></div>
      </div>
    </article>`).join("");
  document.querySelectorAll(".failure-item > button").forEach((button) => button.addEventListener("click", () => {
    const open = button.getAttribute("aria-expanded") === "true";
    button.setAttribute("aria-expanded", String(!open));
    button.querySelector(".failure-toggle").textContent = open ? "+" : "−";
    button.nextElementSibling.hidden = open;
  }));
}
renderFailures();

let flashcardIndex = 0;
function renderFlashcard() {
  const [question, answer] = flashcards[flashcardIndex];
  document.querySelector("#flashcardNumber").textContent = `${String(flashcardIndex + 1).padStart(2, "0")} / ${String(flashcards.length).padStart(2, "0")}`;
  document.querySelector("#flashcardQuestion").textContent = question;
  document.querySelector("#flashcardAnswer").innerHTML = `<p>${answer}</p>`;
  document.querySelector("#flashcardAnswer").hidden = true;
  document.querySelector("#revealFlashcard").textContent = "Reveal answer";
}
document.querySelector("#revealFlashcard").addEventListener("click", (event) => {
  const answer = document.querySelector("#flashcardAnswer");
  answer.hidden = !answer.hidden;
  event.currentTarget.textContent = answer.hidden ? "Reveal answer" : "Hide answer";
});
document.querySelector("#nextFlashcard").addEventListener("click", () => {
  flashcardIndex = (flashcardIndex + 1) % flashcards.length;
  renderFlashcard();
});
renderFlashcard();

let quizIndex = 0;
let quizScore = 0;
let quizLocked = false;
function renderQuiz() {
  const card = document.querySelector("#quizCard");
  if (quizIndex >= quiz.length) {
    const percent = Math.round((quizScore / quiz.length) * 100);
    state.bestQuiz = Math.max(state.bestQuiz, percent);
    saveState();
    document.querySelector("#quizProgress").style.width = "100%";
    card.innerHTML = `<div class="quiz-score"><span class="quiz-count">ASSESSMENT COMPLETE · BEST ${state.bestQuiz}%</span><strong>${percent}%</strong><h3>${percent >= 75 ? "You can explain the boundaries." : "Review the trace, then try again."}</h3><button class="primary-action small" id="restartQuiz" type="button">Restart quiz</button></div>`;
    document.querySelector("#restartQuiz").addEventListener("click", () => {
      quizIndex = 0;
      quizScore = 0;
      renderQuiz();
    });
    return;
  }
  quizLocked = false;
  const item = quiz[quizIndex];
  document.querySelector("#quizProgress").style.width = `${(quizIndex / quiz.length) * 100}%`;
  card.innerHTML = `<span class="quiz-count">QUESTION ${quizIndex + 1} OF ${quiz.length}</span><h3>${item.q}</h3><div class="quiz-options">${item.options.map((option, index) => `<button type="button" data-option="${index}">${option}</button>`).join("")}</div><div class="quiz-feedback" hidden></div><button class="quiz-next" type="button" hidden>Next question →</button>`;
  card.querySelectorAll(".quiz-options button").forEach((button) => button.addEventListener("click", () => answerQuiz(Number(button.dataset.option))));
}

function answerQuiz(choice) {
  if (quizLocked) return;
  quizLocked = true;
  const item = quiz[quizIndex];
  if (choice === item.answer) quizScore += 1;
  const card = document.querySelector("#quizCard");
  card.querySelectorAll(".quiz-options button").forEach((button) => {
    const option = Number(button.dataset.option);
    if (option === item.answer) button.classList.add("correct");
    else if (option === choice) button.classList.add("wrong");
    else button.classList.add("muted");
    button.disabled = true;
  });
  const feedback = card.querySelector(".quiz-feedback");
  feedback.hidden = false;
  feedback.innerHTML = `<strong>${choice === item.answer ? "Correct." : "Not quite."}</strong> ${item.why}`;
  const next = card.querySelector(".quiz-next");
  next.hidden = false;
  next.addEventListener("click", () => {
    quizIndex += 1;
    renderQuiz();
  });
}
renderQuiz();

function renderGlossary(query = "") {
  const normalized = query.trim().toLowerCase();
  const filtered = glossary.filter(([term, definition]) => `${term} ${definition}`.toLowerCase().includes(normalized));
  document.querySelector("#glossaryGrid").innerHTML = filtered.length
    ? filtered.map(([term, definition]) => `<article class="glossary-item"><h3>${term}</h3><p>${definition}</p></article>`).join("")
    : '<p class="glossary-empty">No matching term. Try a shorter word such as “tool” or “test.”</p>';
}
document.querySelector("#glossarySearch").addEventListener("input", (event) => renderGlossary(event.target.value));
renderGlossary();

const trackedSections = [...document.querySelectorAll("[data-track]")];
if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting && entry.intersectionRatio >= .18) {
        state.last = `#${entry.target.id}`;
        saveState();
      }
    });
  }, { threshold: [.18] });
  trackedSections.forEach((section) => observer.observe(section));
}

document.querySelector("#resumeButton").addEventListener("click", () => {
  document.querySelector(state.last || "#anatomy")?.scrollIntoView({ behavior: "smooth" });
});

document.querySelector("#resetProgress").addEventListener("click", () => {
  state = { completed: [], deep: false, last: "#anatomy", bestQuiz: 0 };
  saveState();
  applyDepth();
  renderLessonProgress();
  document.querySelector("#glossarySearch").value = "";
  renderGlossary();
});

if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  const heroEvents = [...document.querySelectorAll(".hero-events li:not(.waiting)")];
  let activeHeroEvent = 0;
  window.setInterval(() => {
    heroEvents[activeHeroEvent].classList.remove("active");
    activeHeroEvent = (activeHeroEvent + 1) % heroEvents.length;
    heroEvents[activeHeroEvent].classList.add("active");
  }, 2400);
}
