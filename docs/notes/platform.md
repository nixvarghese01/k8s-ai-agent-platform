# Platform: Headlamp, single sign-on, HTTPS, profiles

Work between the build weeks that makes the platform usable every day. (#24, #25)

## Headlamp (https://headlamp.ai.local)
Kubernetes dashboard; logs in with a cluster-admin ServiceAccount token
(`.\infra\scripts\platform.ps1 headlamp-token`). Every `up` replaces the previous run's pods, so
`RESTARTS` counts only real crashes; probe delays match measured cold-start times, so a start
logs no `Unhealthy` noise.

## Single sign-on + HTTPS (https://auth.ai.local)
- Authelia in front of every UI (Traefik forwardAuth): sign in once, every `*.ai.local` opens;
  12 h session, 2 h idle, lockout after 5 failures. Apps with their own login keep it.
- A local CA (in WSL, root-only) signs `*.ai.local`; Windows trusts it, so Chrome/Edge show a
  padlock. Names moved from `*.local` to `*.ai.local` because one session cookie must cover all
  UIs and browsers won't share one across bare `.local`.
- Fixed on the way: Kubernetes' `AUTHELIA_*` service env vars broke Authelia's config;
  Authelia needs a writable root (`/app/.healthcheck.env`); Traefik on the host network needed
  `dnsPolicy: ClusterFirstWithHostNet` to resolve in-cluster names.

## Profiles (laptop budget)
- The core (chat, agent, document search, sign-on, Headlamp) always runs; `mlops`,
  `observability`, `automation` and `voice` run only when switched on
  (`.\local-up -Profile mlops`, `.\infra\scripts\platform.ps1 profile mlops`). Off = scaled to 0.
- Measured: core only 3.4 GB in WSL (pods 1.8 GB); core + mlops 4.9 GB; switching mlops on ~40 s.
- Tracing uses Phoenix (~0.5 GB) instead of Langfuse v3 (~1.5–2 GB) for the same reason.
- All profiles on (2026-10-07): 6.9 GB used in WSL, 11.1 GB available.

## Reaching the UIs on any network
Hosts entries point at `127.0.0.1`; Windows port proxies forward 80/443 to `[::1]`, where WSL
relays Traefik. Pointing them at `::1` directly broke every page in Chrome on networks without
IPv6 (Chrome then skips IPv6-only names).
