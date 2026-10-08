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
  from `development` (a release) or `hotfix/*`, enforced by the `branch policy` check. Only the
  maintainer has write access, so only the maintainer merges into `main`; [`CODEOWNERS`](.github/CODEOWNERS)
  requests their review on every PR. CI must pass; releases use a merge commit so `main` keeps
  the history of `development`. No approval count is required (GitHub doesn't let an author
  approve their own PR) and nobody bypasses the rules, admins included.
- **`development`:** no direct pushes, force pushes or deletion. Pull requests from the prefixes
  above, CI must pass, squash merge (a merge commit for the `main` back-merge). The build
  workflow's image-pin commits (`Deploy images built from …`) are the one exception: they're
  pushed with a write deploy key (secret `DEPLOY_KEY`), the ruleset's only direct-push bypass.

Required checks on both: `unit tests (pytest)`, `lint (manifests, shell, PowerShell, workflows)`,
`branch policy`. Release tags `v*` can't be moved or deleted.

## Pipelines

| Workflow | Runs on | Does |
|---|---|---|
| [`ci`](.github/workflows/ci.yml) | every pull request and push to `development`/`main` | unit tests; lint manifests, shell, PowerShell, n8n workflows |
| [`branch-policy`](.github/workflows/branch-policy.yml) | pull requests into `development`/`main` | source branch allowed for the target; into `main` also a new, untagged `CHANGELOG.md` version |
| [`build`](.github/workflows/build.yml) | pushes to `development` and `hotfix/*` touching image sources | builds the images to GHCR, pins their digests in `infra/k3s` (Argo CD deploys `development`) |
| [`release`](.github/workflows/release.yml) | every merge into `main` | tags the merge commit `vX.Y.Z`, tags the pinned images `vX.Y.Z` and `latest`, publishes the GitHub release |
| [`cleanup`](.github/workflows/cleanup.yml) | weekly | prunes old image versions; released images are kept |
| Dependabot | weekly | grouped updates for Actions, pip and base images, as pull requests into `development` |

Images are built once and promoted: `main` runs exactly the digests tested on `development` (or
the hotfix branch); the release only adds version tags to them.

## Releases

Versions follow [Semantic Versioning](https://semver.org/): `MAJOR` for breaking changes (manifests
or APIs that need manual migration), `MINOR` for new features, `PATCH` for fixes. The version is
the newest `## [X.Y.Z]` section of `CHANGELOG.md`.

1. On a `chore/release-X.Y.Z` branch, rename `[Unreleased]` in `CHANGELOG.md` to
   `[X.Y.Z] - <date>` (and add a new empty `[Unreleased]`); merge it into `development`.
2. The maintainer opens a pull request `development` → `main` titled `Release vX.Y.Z`, with the
   changelog section as its description, and merges it with a **merge commit**.
3. The `release` workflow tags the merge commit `vX.Y.Z` and publishes the release with the
   changelog section as notes. Nothing to do by hand.

## Hotfixes

For an urgent fix to the released version on `main`:

1. Branch `hotfix/<issue>-<topic>` from `main`; fix, add tests, and add a `PATCH` version section
   (`[X.Y.Z+1] - <date>`) to `CHANGELOG.md`.
2. Push. If image sources changed, `build` builds them on the hotfix branch and pins the digests
   there; that push re-runs the pull request checks.
3. Open a pull request into `main`; the maintainer merges it and `release` publishes `vX.Y.Z+1`.
4. Open a pull request `main` → `development` so the fix isn't lost (keep `development`'s image
   digests if both changed the same manifest; `build` re-pins on the next push anyway).

A fix for something only on `development` is a `bugfix/` branch, not a hotfix.

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
