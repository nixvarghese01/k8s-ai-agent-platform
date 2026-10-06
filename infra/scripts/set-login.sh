#!/bin/bash
# Set the single sign-on user for every *.ai.local UI (README §6.14). Asks for a username and a
# password (twice, not shown), stores only an argon2 hash in Secret auth/authelia-users, and
# restarts Authelia so it applies at once (everyone signs in again).
#
#   From Windows:  .\infra\scripts\platform.ps1 set-login
#   Inside Ubuntu: make set-login            (or: bash infra/scripts/set-login.sh)
#   --bootstrap    (deploy.sh) first install only: user "admin" with a random password, kept in
#                  Secret auth/authelia-initial until set-login replaces it
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-$([ "$EUID" -eq 0 ] && echo /etc/rancher/k3s/k3s.yaml || echo ~/.kube/config)}
cd "$(dirname "$0")/../.."

IMAGE=$(grep -o 'ghcr.io/authelia/authelia:[^ ]*' infra/k3s/auth/authelia.yaml | head -1)

hash() { # argon2id hash with Authelia's own tool, in a throwaway pod (works before Authelia runs)
  kubectl -n auth run "authelia-hash-$RANDOM" --rm -i --quiet --restart=Never --image="$IMAGE" \
    --command -- authelia crypto hash generate argon2 --password "$1" | sed -n 's/^Digest: //p'
}

store() { # $1 username, $2 display name, $3 hash
  printf 'users:\n  %s:\n    disabled: false\n    displayname: "%s"\n    password: "%s"\n    groups: [admins]\n' "$1" "$2" "$3" |
    kubectl -n auth create secret generic authelia-users --from-file=users_database.yml=/dev/stdin \
      --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

if [ "${1:-}" = "--bootstrap" ]; then
  pw=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 20)
  store admin "Admin" "$(hash "$pw")"
  kubectl -n auth create secret generic authelia-initial --from-literal=username=admin \
    --from-literal=password="$pw" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo "Created sign-on user 'admin' with a random password (run set-login to choose your own)."
  exit 0
fi

default_user=${SUDO_USER:-$(id -un 1000 2>/dev/null || echo admin)}
read -rp "Username [$default_user]: " user
user=${user:-$default_user}
[[ "$user" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo "use letters, digits, . _ - only" >&2; exit 1; }
while true; do
  read -rsp "New password (12+ characters): " pw; echo
  [ ${#pw} -ge 12 ] || { echo "too short"; continue; }
  read -rsp "Same password again: " pw2; echo
  [ "$pw" = "$pw2" ] && break
  echo "they don't match; try again"
done

echo "Hashing..."
digest=$(hash "$pw")
[ -n "$digest" ] || { echo "hashing failed (is the platform up?)" >&2; exit 1; }
store "$user" "$user" "$digest"
kubectl -n auth delete secret authelia-initial --ignore-not-found >/dev/null
kubectl -n auth rollout restart deploy/authelia >/dev/null
kubectl -n auth rollout status deploy/authelia --timeout=2m >/dev/null
echo "Done. Sign in at https://auth.ai.local (or open any *.ai.local site) as '$user'."
