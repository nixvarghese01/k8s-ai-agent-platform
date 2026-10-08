# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub: **Security → Report a vulnerability** on
this repository (private vulnerability reporting). Don't open a public issue for them. Expect a
first answer within a week.

## Supported versions

| Branch | Supported |
|---|---|
| `development` (default; deployed by Argo CD) | ✅ |
| `main` | ✅ after each merge |

## Security model

The platform is designed to run on one machine, reachable only from that machine (WSL2 NAT).
What protects it:

| Area | How | Details |
|---|---|---|
| Access to every UI | Single sign-on with Authelia (forward auth on every ingress), HTTPS only, brute-force lockout | [README 6.14](README.md#614-single-sign-on-and-https-authelia) |
| Apps with their own accounts | Signed in from Authelia: OpenID Connect (Argo CD), trusted headers (Grafana, Open WebUI, n8n), a Traefik-added token (Headlamp) | README 6.14 |
| Forged sign-in headers | Accepted only from Traefik: network policies and source-address checks; `make e2e` tests it | README 6.14 |
| Secrets | Created in the cluster by `deploy.sh`, never committed; GitHub Actions uses only its own token | [`deploy.sh`](infra/scripts/deploy.sh) |
| Container images | Built by CI, pinned by digest, non-root, read-only root filesystems where possible | [`build.yml`](.github/workflows/build.yml) |
| Agent tools | Read-only file access, web fetches to public addresses only, model changes audited | README 6.10, 6.19, 6.9 |
| Data | Models run locally; only the optional web research (`research` profile) sends queries off the machine | README 11 |

## Before exposing it beyond one machine

Switch the sign-on rule to two-factor, give Headlamp a read-only role, add a LiteLLM master key,
and encrypt Kubernetes secrets at rest. The README's [Known limitations](README.md#15-known-limitations-and-risks)
lists these.
