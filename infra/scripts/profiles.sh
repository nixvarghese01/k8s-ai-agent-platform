#!/bin/bash
# On-demand profiles (README §6.6): the core (chat, agent, document search, sign-on) always runs;
# everything labelled `local-ai/profile` runs only while one of its profiles is active. A profile
# that is off has its Deployments scaled to 0, so it costs no RAM or CPU; data stays on volumes.
#
#   profiles.sh               show profiles and what each Deployment is doing
#   profiles.sh set mlops,observability   activate exactly these (core = none of them)
#   profiles.sh set core      only the core
#   profiles.sh apply         re-apply the stored choice (deploy.sh and `up` run this)
#
# Profiles: mlops (Postgres, SeaweedFS, MLflow, Dagster, model serving), observability
# (tracing, metrics), automation (n8n), voice (speech-to-text, text-to-speech).
# A label value lists every profile that needs the Deployment, dot-separated (mlops.automation).
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-$([ "$EUID" -eq 0 ] && echo /etc/rancher/k3s/k3s.yaml || echo ~/.kube/config)}
KNOWN="mlops observability automation voice"

stored() { kubectl -n kube-system get configmap platform-profiles -o jsonpath='{.data.active}' 2>/dev/null || true; }

store() {
  kubectl -n kube-system create configmap platform-profiles --from-literal=active="$1" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

# "<namespace> <deployment> <profiles>" for every labelled Deployment
labelled() {
  kubectl get deploy -A -l local-ai/profile -L local-ai/profile --no-headers | awk '{print $1, $2, $NF}'
}

apply() {
  local s; s=$(stored)
  local active=",$s,"
  echo "== profiles: core${s:+,$s}"
  labelled | while read -r ns name profs; do
    want=0
    for p in ${profs//./ }; do [[ "$active" == *",$p,"* ]] && want=1; done
    have=$(kubectl -n "$ns" get deploy "$name" -o jsonpath='{.spec.replicas}')
    [ "$have" = "$want" ] || kubectl -n "$ns" scale deploy "$name" --replicas="$want" >/dev/null
    printf "  %-4s %-30s %s\n" "$([ "$want" = 1 ] && echo on || echo off)" "$ns/$name" "$profs"
  done
}

wait_ready() { # every Deployment that should run is available
  labelled | while read -r ns name _; do
    [ "$(kubectl -n "$ns" get deploy "$name" -o jsonpath='{.spec.replicas}')" = 1 ] &&
      kubectl -n "$ns" rollout status deploy "$name" --timeout=10m >/dev/null && echo "  ready $ns/$name"
  done
  true
}

case "${1:-show}" in
  show)
    labelled | while read -r ns name profs; do
      printf "  %-4s %-30s %s\n" "$([ "$(kubectl -n "$ns" get deploy "$name" -o jsonpath='{.spec.replicas}')" = 1 ] && echo on || echo off)" "$ns/$name" "$profs"
    done
    s=$(stored); echo "active: core${s:+,$s}"
    ;;
  set)
    want=${2:-core}
    [ "$want" = core ] && want=""
    for p in ${want//,/ }; do [[ " $KNOWN " == *" $p "* ]] || { echo "unknown profile: $p (known: $KNOWN)" >&2; exit 2; }; done
    store "$want"
    apply
    wait_ready
    ;;
  apply) apply ;;
  wait) wait_ready ;;
  *) echo "usage: $0 [show | set <p1,p2|core> | apply]" >&2; exit 2 ;;
esac
