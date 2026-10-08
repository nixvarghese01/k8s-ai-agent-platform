# Contributing

Thanks for your interest. Issues and pull requests are welcome.

## Workflow

1. Open an issue first for anything bigger than a small fix, so the approach can be agreed.
2. Branch from **`development`** (the default branch; Argo CD deploys it) and open the pull
   request against it. `main` is updated from `development` in releases.
3. Keep a pull request to one change, with tests and the README updated alongside.

## Development setup

The platform runs on Windows 11 + WSL2 (Ubuntu) with k3s; see [README 6. Installation](README.md#6-installation).
For code changes alone you need Python 3.13 and Docker.

| Task | Command |
|---|---|
| Unit tests (no cluster needed) | `make test` (runs pytest in a `python:3.13-slim` container) |
| Build your images into k3s | `make images` (or `bash infra/scripts/build-images.sh <name>`) |
| Check every feature end to end | `make e2e` (needs the platform up, all profiles on) |
| Score the models on the golden set | `make eval` |

CI runs the unit tests and lints the manifests (kubeconform), shell scripts (ShellCheck),
PowerShell (PSScriptAnalyzer) and the n8n workflows on every push and pull request.

## Conventions

- **Manifests** live under `infra/k3s/<namespace>/`; images are pinned by tag and digest.
- **Secrets** never go into Git: create them in `infra/scripts/deploy.sh`.
- **New agent tools** are MCP servers in `mcp-servers/<name>/`, added to `MCP_SERVERS` in
  `infra/k3s/agent/agent.yaml` and to the build matrix in `.github/workflows/build.yml`.
- **Changes to the laptop** (host setup) go in `infra/scripts/host/` scripts that are safe to re-run.
- **Docs:** update the README section you touched; measured numbers beat estimates.
- Commit messages: a short summary line, then what changed and why.

## Code of conduct

Be respectful and constructive. Harassment or abuse isn't tolerated.
