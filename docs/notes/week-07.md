# Week 7: GitOps CI/CD (GitHub Actions, GHCR, ArgoCD)

**Deliverable:** a push to `development` is tested, built, published and deployed by itself. ✅ (#11, CI half of #4)

## What runs
- **ci.yml** on every push/PR: pytest (42 tests), kubeconform, ShellCheck, PSScriptAnalyzer, an
  n8n workflow consistency check.
- **build.yml** on code changes: `ml-base`, then 8 images in parallel to
  `ghcr.io/nixvarghese01/local-ai-<name>` (public); a bump job pins the new digests in
  `infra/k3s` and commits them. **cleanup.yml** weekly keeps 10 versions per image.
- **ArgoCD** v3.5.4 (profile `gitops`, 204 MB): Application `platform` syncs `infra/k3s` from
  `development` every ~3 minutes. https://argocd.ai.local.

## Decisions
- **Digest pinning + reproducible builds** (`SOURCE_DATE_EPOCH=0`, no attestations): unchanged
  images keep their digest, so a commit only restarts what actually changed.
- **No prune, no self-heal:** a removed manifest never deletes a PVC; a local test image or a
  profile switch isn't reverted until the next commit touches that resource.
- **Trimmed ArgoCD** (no Dex, notifications, ApplicationSet): 204 MB instead of ~1.3 GB.
- **Shared `ml-base`** for mlflow, pipelines, serving: their layers 3.5 → 2.0 GB.
- **Public images:** no GHCR size limit, no pull secret (verified with anonymous pulls).

## Fixed on the way
- PSScriptAnalyzer: a `-Profile` parameter overwrote PowerShell's own `$PROFILE` (renamed,
  alias kept); BOM-less non-ASCII `.ps1` files (made ASCII or given a BOM).
- ArgoCD showed the platform "Progressing" forever: Traefik didn't publish an Ingress address
  (k3s's `publishedService` copied an empty ClusterIP). Now `127.0.0.1`; app Healthy.

## Measured
- First run: ci 2 min 23 s, build 4 min 4 s; ArgoCD deployed the bump commit; all 9 deployments
  run GHCR images by digest. `k3s crictl rmi --prune`: image store 26 → 19 GB.
