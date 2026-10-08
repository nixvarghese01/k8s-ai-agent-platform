# Contributing

Thanks for your interest. Issues and pull requests are welcome.

## Workflow

1. Open an issue first for anything bigger than a small fix, so the approach can be agreed.
2. Branch from **`development`** with a prefix from the table below, and open the pull request
   against `development`.
3. Keep a pull request to one change, with tests, the README and `CHANGELOG.md` (`[Unreleased]`)
   updated alongside.
4. CI must pass; the pull request is squash-merged and its branch deleted.

## Branching model

| Branch | Purpose | Branches from | Merges into |
|---|---|---|---|
| `main` | Released code; every release is a tag `vX.Y.Z` on it | — | — |
| `development` | Integration branch, the default; Argo CD deploys it | `main` | `main` (release) |
| `feature/<issue>-<topic>` | New behaviour | `development` | `development` |
| `bugfix/<issue>-<topic>` | A fix for something not yet released | `development` | `development` |
| `hotfix/<issue>-<topic>` | An urgent fix for a release | `main` | `main`, then `main` back into `development` |
| `docs/`, `chore/`, `refactor/`, `test/`, `ci/` | Docs, upkeep, restructuring, tests, pipelines | `development` | `development` |

Examples: `feature/42-calendar-reminders`, `bugfix/31-phishing-recall`, `docs/install-wsl`.

**Branch protection** (repository rulesets):

- **`main`:** no direct pushes, force pushes or deletion. Changes arrive only as pull requests
  from `development` (a release) or `hotfix/*`, enforced by the `branch policy` check. They need
  the code owner ([`CODEOWNERS`](.github/CODEOWNERS)), so only the maintainer merges into `main`.
  CI must pass; releases use a merge commit so `main` keeps the history of `development`.
- **`development`:** no direct pushes, force pushes or deletion. Pull requests from the prefixes
  above, CI must pass, squash merge. The build workflow's image-pin commits (`Deploy images built
  from …`) are the one exception: GitHub Actions may push them directly.

Required checks on both: `unit tests (pytest)`, `lint (manifests, shell, PowerShell, workflows)`,
`branch policy`.

## Releases

Versions follow [Semantic Versioning](https://semver.org/): `MAJOR` for breaking changes (manifests
or APIs that need manual migration), `MINOR` for new features, `PATCH` for fixes.

1. On a `chore/release-X.Y.Z` branch, move `[Unreleased]` in `CHANGELOG.md` to `[X.Y.Z] - <date>`;
   merge it into `development`.
2. The maintainer opens a pull request `development` → `main` titled `Release vX.Y.Z`, with the
   changelog section as its description, and merges it with a merge commit.
3. Tag the merge commit and publish the release:
   `gh release create vX.Y.Z --target main --title "vX.Y.Z" --notes-file <changelog section>`.

**Hotfix:** branch `hotfix/…` from `main`, pull request into `main`, release a `PATCH` version,
then open a pull request `main` → `development` so the fix isn't lost.

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
- Commit messages: a short summary line in the imperative ("Add …", "Fix …"), then what changed
  and why. Reference the issue (`Closes #42`) in the pull request.

## Code of conduct

Be respectful and constructive. Harassment or abuse isn't tolerated.
