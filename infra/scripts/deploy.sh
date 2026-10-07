#!/bin/bash
# README §6.5: apply every manifest under infra/k3s and wait for the workloads.
# Run inside Ubuntu from the repo root:  bash infra/scripts/deploy.sh
set -euxo pipefail
export KUBECONFIG=${KUBECONFIG:-~/.kube/config}
cd "$(dirname "$0")/../.."

kubectl apply -f infra/k3s/namespaces.yaml

# Secrets live only in the cluster, never in Git. Create each one once; keep it on re-deploy.
set +x
if ! kubectl -n ui get secret open-webui-secret >/dev/null 2>&1; then
  # Signs Open WebUI login sessions; a stable key keeps users logged in across restarts
  kubectl -n ui create secret generic open-webui-secret \
    --from-literal=WEBUI_SECRET_KEY="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
fi

rand() { head -c "${1:-24}" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
get() { kubectl -n "$1" get secret "$2" -o "jsonpath={.data.$3}" | base64 -d; }

# Postgres passwords (README §6.13). The storage copy feeds Postgres; mlops gets the app ones.
if ! kubectl -n storage get secret postgres-secret >/dev/null 2>&1; then
  kubectl -n storage create secret generic postgres-secret --from-literal=POSTGRES_PASSWORD="$(rand)" \
    --from-literal=MLFLOW_DB_PASSWORD="$(rand)" --from-literal=DAGSTER_DB_PASSWORD="$(rand)"
fi
if ! kubectl -n mlops get secret mlops-db >/dev/null 2>&1; then
  kubectl -n mlops create secret generic mlops-db \
    --from-literal=MLFLOW_DB_PASSWORD="$(get storage postgres-secret MLFLOW_DB_PASSWORD)" \
    --from-literal=DAGSTER_DB_PASSWORD="$(get storage postgres-secret DAGSTER_DB_PASSWORD)"
fi

# SeaweedFS: one S3 key pair for the platform, and the admin UI password
if ! kubectl -n storage get secret seaweedfs-secret >/dev/null 2>&1; then
  key=$(rand 10); secret=$(rand 20)
  s3json=$(printf '{"identities":[{"name":"platform","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Admin","Read","List","Tagging","Write"]}]}' "$key" "$secret")
  kubectl -n storage create secret generic seaweedfs-secret --from-literal=s3.json="$s3json" \
    --from-literal=admin-password="$(rand 12)" --from-literal=access-key="$key" --from-literal=secret-key="$secret"
fi
if ! kubectl -n mlops get secret s3-credentials >/dev/null 2>&1; then
  kubectl -n mlops create secret generic s3-credentials \
    --from-literal=AWS_ACCESS_KEY_ID="$(get storage seaweedfs-secret access-key)" \
    --from-literal=AWS_SECRET_ACCESS_KEY="$(get storage seaweedfs-secret secret-key)"
fi

# HTTPS certificate for *.ai.local (README §6.14), from the local CA; root reads the CA key
if ! kubectl -n kube-system get secret platform-tls >/dev/null 2>&1; then
  if [ "$EUID" -eq 0 ]; then
    bash infra/scripts/host/06-local-tls.sh
  else
    echo "No TLS certificate yet: run  wsl -u root -- bash infra/scripts/host/06-local-tls.sh  then deploy again" >&2
    exit 1
  fi
fi

# Single sign-on (Authelia): its own signing/encryption secrets, and a first user to replace
if ! kubectl -n auth get secret authelia-secrets >/dev/null 2>&1; then
  kubectl -n auth create secret generic authelia-secrets --from-literal=session-secret="$(rand 32)" \
    --from-literal=storage-encryption-key="$(rand 32)" --from-literal=jwt-secret="$(rand 32)"
fi
if ! kubectl -n auth get secret authelia-users >/dev/null 2>&1; then
  bash infra/scripts/set-login.sh --bootstrap
fi
set -x

kubectl apply -R -f infra/k3s/
kubectl -n llm rollout status deploy/litellm --timeout=10m
kubectl -n storage rollout status deploy/qdrant --timeout=10m
kubectl -n auth rollout status deploy/authelia --timeout=5m
kubectl -n storage rollout status deploy/postgres --timeout=5m
kubectl -n storage rollout status deploy/seaweedfs --timeout=5m
kubectl -n ui rollout status deploy/open-webui --timeout=15m
kubectl -n ui rollout status deploy/headlamp --timeout=5m
# Built locally: run `make images` first (infra/scripts/build-images.sh)
kubectl -n agent rollout status deploy/mcp-filesystem --timeout=5m
kubectl -n agent rollout status deploy/mcp-rag --timeout=5m
kubectl -n agent rollout status deploy/agent --timeout=5m
kubectl -n ui rollout status deploy/agent-ui --timeout=5m
kubectl -n mlops rollout status deploy/mlflow --timeout=5m
kubectl -n mlops rollout status deploy/dagster-webserver --timeout=5m
kubectl -n mlops rollout status deploy/dagster-daemon --timeout=5m
# `apply` may have started optional services again: keep only the active profiles running
bash infra/scripts/profiles.sh apply
kubectl get pods,pvc,ingress -A --field-selector metadata.namespace!=kube-system
