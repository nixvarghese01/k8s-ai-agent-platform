## What and why

<!-- The change and the reason for it. Link the issue: Closes #... -->

## Type

<!-- Matches the branch prefix (CONTRIBUTING.md "Branching model"). -->

- [ ] `feature/` new behaviour
- [ ] `bugfix/` fix on development
- [ ] `hotfix/` urgent fix for a release on main
- [ ] `docs/` / `chore/` / `refactor/` / `test/` / `ci/`
- [ ] Release: `development` → `main`

## Checks

- [ ] Targets `development` (only releases and hotfixes target `main`)
- [ ] `make test` passes
- [ ] `make e2e` passes (if it touches the running platform)
- [ ] README / notes updated where behaviour changed
- [ ] `CHANGELOG.md` updated under `[Unreleased]` for user-visible changes
- [ ] No secrets in the diff
