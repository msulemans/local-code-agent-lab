# GitHub Pages deployment

The public Pages site contains only the dependency-free files under
`learning/`. It does not expose a Python server, repository tools, Ollama,
model artifacts, compatibility run evidence, or the local filesystem.

## Deployment contract

- Source repository: `msulemans/local-code-agent-lab`
- Source branch: `main`
- Published artifact root: `learning/`
- Workflow: `.github/workflows/pages.yml`
- Trigger: relevant pushes to `main` or an explicit manual dispatch
- Required checks: JavaScript syntax and the rendered HTML contract
- Deployment environment: `github-pages`
- Permissions: read repository contents, write Pages, and mint the deployment
  identity token

The official GitHub Actions are pinned to immutable commit SHAs. Dependabot or
a deliberate maintenance change should update them; the deployment must not
silently float to new action code.

## Local verification

```bash
node --check learning/app.js
node tests/ui/rendered-html.test.mjs
python3.11 scripts/serve_learning_lab.py
```

Local browser progress and deployed browser progress are separate because both
are stored in the current browser's local storage.

## Publication evidence

Verified on 2026-08-09 Australia/Sydney:

- Public URL: `https://msulemans.github.io/local-code-agent-lab/`
- Pages source: GitHub Actions
- HTTPS enforcement: enabled
- Successful workflow run: `31306104742`
- Deployment job duration: 17 seconds
- Independent fetch: HTTP/2 200 from GitHub Pages
- Fetched document: 15,773 bytes
- Content marker: `LocalCode Field Manual — Learn the Agent You Are Building`

The first push-triggered run (`31305813210`) failed at `configure-pages`
because the repository Pages site had not yet been enabled. No artifact was
deployed by that run. After Pages was explicitly enabled with workflow
publishing, an unchanged manual dispatch succeeded. This preserves the initial
failure as diagnosable deployment evidence.
