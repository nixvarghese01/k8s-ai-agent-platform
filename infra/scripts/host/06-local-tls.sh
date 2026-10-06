#!/bin/bash
# README §6.14: HTTPS for every *.ai.local UI. Creates a private certificate authority (once),
# issues a wildcard certificate for *.ai.local from it, and stores the certificate in k3s as
# Secret kube-system/platform-tls, which Traefik serves for every ingress (ingress/tls.yaml).
# Windows trusts the CA after windows-trust-ca.ps1, so Chrome/Edge show a normal padlock.
#
# Run as root inside Ubuntu (or deploy.sh runs it):
#   wsl -u root -- bash /mnt/e/Github/local-ai-platform/infra/scripts/host/06-local-tls.sh [--renew]
# Safe to re-run: keeps the CA and a certificate that is still valid for 30+ days.
#   --renew  issue a new certificate now (it lasts 397 days; the CA lasts 10 years)
set -euo pipefail
[ "$EUID" -eq 0 ] || { echo "run as root (wsl -u root)" >&2; exit 1; }
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

DIR=/var/lib/local-ai-ca # private key of the CA: root-only, never in Git
DOMAIN=ai.local
mkdir -p "$DIR" && chmod 700 "$DIR" && cd "$DIR"

if [ ! -f ca.key ]; then
  echo "== creating the local CA"
  openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes -keyout ca.key -out ca.crt \
    -subj "/CN=Local AI Platform CA ($(hostname))" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" -addext "keyUsage=critical,keyCertSign,cRLSign"
  chmod 600 ca.key
fi

if [ "${1:-}" = "--renew" ] || [ ! -f tls.crt ] || ! openssl x509 -checkend $((30 * 86400)) -noout -in tls.crt >/dev/null; then
  echo "== issuing *.$DOMAIN"
  openssl req -newkey rsa:2048 -nodes -keyout tls.key -out tls.csr -subj "/CN=*.$DOMAIN"
  openssl x509 -req -in tls.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out tls.crt -days 397 -sha256 \
    -extfile <(printf "subjectAltName=DNS:*.%s,DNS:%s\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature,keyEncipherment" "$DOMAIN" "$DOMAIN")
  chmod 600 tls.key
  rm -f tls.csr
fi

kubectl -n kube-system create secret tls platform-tls --cert=tls.crt --key=tls.key --dry-run=client -o yaml | kubectl apply -f -
openssl x509 -noout -subject -enddate -ext subjectAltName -in tls.crt
echo "CA certificate for Windows: $DIR/ca.crt (windows-trust-ca.ps1 imports it)"
