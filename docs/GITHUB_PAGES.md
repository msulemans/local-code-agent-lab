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

Do not call the site deployed merely because the workflow exists. Record the
successful workflow run and an HTTP 200 response from the final Pages URL in
`AGENT_STATE.md` after both are observed.
