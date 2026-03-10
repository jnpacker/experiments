#!/usr/bin/env bash
# setup.sh — Single-command setup: OCM hub + managed clusters + CAPOA + dashboard.
# Installs all prerequisites, creates clusters, and starts services.
# Idempotent: safe to re-run. Works standalone or as a VM provisioner.
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/<you>/laptop-bootstrap/main/setup.sh | bash
#
# Or locally:
#   ./setup.sh              # full setup (clusters + CAPOA + CAPA + dashboard)
#   ./setup.sh --clusters   # KIND clusters only
#   ./setup.sh --capoa      # CAPOA on hub (assumes clusters exist)
#   ./setup.sh --capa       # CAPI-AWS on hub (assumes clusters exist)
#   ./setup.sh --dashboard  # dashboard only (assumes clusters exist)
#   ./setup.sh --ui         # show token + URL, start port-forward
#   ./setup.sh --status     # show what's running
#   ./setup.sh --teardown   # delete everything

set -euo pipefail

# When piped via curl|bash, SCRIPT_DIR won't resolve — default to $HOME/ocm-lab
if [[ "${BASH_SOURCE[0]:-}" == "" ]] || [[ ! -f "${BASH_SOURCE[0]}" ]]; then
    SCRIPT_DIR="${HOME}/ocm-lab"
    mkdir -p "${SCRIPT_DIR}"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

LOCAL_BIN="${SCRIPT_DIR}/.local/bin"
DASHBOARD_NS="ocm-dashboard"
OCM_LAB_DIR="${SCRIPT_DIR}/lab"
OCM_LAB_REPO="https://github.com/open-cluster-management-io/lab.git"

# Versions
CLUSTERCTL_VERSION="v1.11.3"
CERT_MANAGER_VERSION="v1.14.0"
CAPOA_VERSION="v0.4.0"
CAPA_PROVIDER_VERSION="v2.10.2"
KIND_VERSION="v0.27.0"
ASSISTED_SERVICE_DIR="/tmp/assisted-service"

# Architecture detection
ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)  ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
esac
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"

##############################################################################
# Hub kubeconfig — single source of truth for the entire script
##############################################################################
HUB_KUBECONFIG="${SCRIPT_DIR}/hub"

##############################################################################
# Helpers
##############################################################################
log()  { echo ""; echo "==> $*"; }
info() { echo "    $*"; }
err()  { echo "ERROR: $*" >&2; exit 1; }

have() { command -v "$1" &>/dev/null; }

# Accumulator for per-phase timings (printed in the final summary).
TIMINGS=()

# Run a function and print how long it took.
# Usage: timed "Label" some_function [args...]
timed() {
    local label="$1"; shift
    local start end elapsed m s
    start="$(date +%s)"
    "$@"
    end="$(date +%s)"
    elapsed=$(( end - start ))
    m=$(( elapsed / 60 ))
    s=$(( elapsed % 60 ))
    TIMINGS+=("$(printf '%-40s %dm %02ds' "${label}" "${m}" "${s}")")
    info "$(printf '%-40s %dm %02ds' "${label}" "${m}" "${s}")"
}

# Add local bin to PATH
ensure_path() {
    mkdir -p "${LOCAL_BIN}"
    case ":${PATH}:" in
        *":${LOCAL_BIN}:"*) ;;
        *) export PATH="${LOCAL_BIN}:${PATH}" ;;
    esac
}

# Export hub kubeconfig from KIND and set it for the rest of the script.
# Call this after the hub cluster exists.
set_hub_kubeconfig() {
    kind get kubeconfig --name hub > "${HUB_KUBECONFIG}" 2>/dev/null || \
        err "Hub cluster not found. Run './setup.sh --clusters' first."
    chmod 600 "${HUB_KUBECONFIG}"
    export KUBECONFIG="${HUB_KUBECONFIG}"
    info "KUBECONFIG set to ${KUBECONFIG} (hub cluster)"
    # Verify connectivity
    kubectl cluster-info --request-timeout=10s &>/dev/null || \
        err "Cannot reach the hub cluster. Is it running?"
}

##############################################################################
# Phase 0: Check prerequisites
##############################################################################
phase_prereqs() {
    log "Phase 0: Checking prerequisites"
    ensure_path

    local missing=()

    # --- Container runtime (docker or podman) ---
    if ! have docker && ! have podman; then
        missing+=("  docker or podman  — container runtime required by KIND
      Docker:  https://docs.docker.com/engine/install/
      Podman:  https://podman.io/docs/installation")
    fi

    # --- curl ---
    if ! have curl; then
        missing+=("  curl               — sudo dnf/apt install curl")
    fi

    # --- git ---
    if ! have git; then
        missing+=("  git                — sudo dnf/apt install git")
    fi

    # --- kubectl ---
    if ! have kubectl; then
        missing+=("  kubectl            — https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/
      curl -fsSL https://dl.k8s.io/release/\$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/${OS}/${ARCH}/kubectl -o /usr/local/bin/kubectl && chmod +x /usr/local/bin/kubectl")
    fi

    # --- kind ---
    if ! have kind; then
        missing+=("  kind               — https://kind.sigs.k8s.io/docs/user/quick-start/#installation
      curl -fsSL https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-${OS}-${ARCH} -o /usr/local/bin/kind && chmod +x /usr/local/bin/kind")
    fi

    # --- helm ---
    if ! have helm; then
        missing+=("  helm               — https://helm.sh/docs/intro/install/
      curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash")
    fi

    # --- clusteradm ---
    if ! have clusteradm; then
        missing+=("  clusteradm         — https://open-cluster-management.io/docs/getting-started/installation/start-the-control-plane/
      curl -fsSL https://raw.githubusercontent.com/open-cluster-management-io/clusteradm/main/install.sh | bash")
    fi

    # --- kustomize ---
    if ! have kustomize; then
        missing+=("  kustomize          — https://kubectl.docs.kubernetes.io/installation/kustomize/
      curl -fsSL https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh | bash")
    fi

    if (( ${#missing[@]} > 0 )); then
        echo ""
        echo "ERROR: The following required tools are missing:" >&2
        echo "" >&2
        for item in "${missing[@]}"; do
            echo "${item}" >&2
            echo "" >&2
        done
        err "Install the tools above and re-run this script."
    fi

    # --- Report versions ---
    info "curl:       $(curl --version 2>/dev/null | head -1)"
    info "git:        $(git --version 2>/dev/null)"
    info "kubectl:    $(kubectl version --client -o json 2>/dev/null | grep -o '"gitVersion": "[^"]*"' || echo 'ok')"
    info "kind:       $(kind version 2>/dev/null || echo 'ok')"
    info "helm:       $(helm version --short 2>/dev/null || echo 'ok')"
    info "clusteradm: $(clusteradm version 2>/dev/null | head -1 || echo 'ok')"
    info "kustomize:  $(kustomize version 2>/dev/null || echo 'ok')"

    if have docker; then
        info "runtime:    docker $(docker --version 2>/dev/null | grep -o '[0-9][0-9.]*' | head -1)"
    elif have podman; then
        info "runtime:    podman $(podman --version 2>/dev/null | grep -o '[0-9][0-9.]*' | head -1)"
    fi

    # --- WSL: ensure podman machine is started ---
    if grep -qi microsoft /proc/version 2>/dev/null; then
        info "WSL detected"
        if have podman; then
            if ! podman machine inspect &>/dev/null 2>&1; then
                info "Starting podman machine..."
                podman machine start || true
            fi
        fi
    fi

    info "All prerequisites ready"
}

##############################################################################
# Phase 1: KIND clusters (hub + cluster1 + cluster2)
##############################################################################
phase_clusters() {
    log "Phase 1: Creating KIND clusters (hub + 2 managed)"

    local existing
    existing="$(kind get clusters 2>/dev/null || true)"

    if echo "${existing}" | grep -q "^hub$" && \
       echo "${existing}" | grep -q "^cluster1$" && \
       echo "${existing}" | grep -q "^cluster2$"; then
        info "All three KIND clusters already exist — skipping"
    else
        info "Running OCM local-up.sh (this takes a few minutes)..."
        curl -fsSL https://raw.githubusercontent.com/open-cluster-management-io/OCM/main/solutions/setup-dev-environment/local-up.sh | bash
    fi

    # Export and verify hub kubeconfig for all subsequent phases
    set_hub_kubeconfig
}

##############################################################################
# Phase 2: CAPOA on the hub
##############################################################################
ASSISTED_SERVICE_RAW="https://raw.githubusercontent.com/openshift/assisted-service/master"

phase_capoa() {
    log "Phase 2: Setting up CAPOA on hub cluster"
    ensure_kubeconfig

    # --- clusterctl binary ---
    local CLUSTERCTL="${LOCAL_BIN}/clusterctl"
    if [[ ! -x "${CLUSTERCTL}" ]]; then
        info "Installing clusterctl ${CLUSTERCTL_VERSION}..."
        curl -fsSL "https://github.com/kubernetes-sigs/cluster-api/releases/download/${CLUSTERCTL_VERSION}/clusterctl-${OS}-${ARCH}" \
            -o "${CLUSTERCTL}"
        chmod +x "${CLUSTERCTL}"
    fi

    # --- cert-manager ---
    info "cert-manager ${CERT_MANAGER_VERSION}..."
    if kubectl get deployment cert-manager -n cert-manager &>/dev/null; then
        info "Already installed"
    else
        kubectl apply -f "https://github.com/cert-manager/cert-manager/releases/download/${CERT_MANAGER_VERSION}/cert-manager.yaml"
    fi
    kubectl wait --for=condition=available --timeout=300s deployment/cert-manager -n cert-manager
    kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-webhook -n cert-manager
    kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-cainjector -n cert-manager

    # --- nginx ingress (kind-specific) ---
    info "nginx ingress controller..."
    if kubectl get deployment ingress-nginx-controller -n ingress-nginx &>/dev/null; then
        info "Already installed"
    else
        kubectl apply -f "https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml"
    fi
    kubectl wait --for=condition=available --timeout=300s deployment/ingress-nginx-controller -n ingress-nginx

    # --- dependency CRDs (fetched directly, no repo clone needed) ---
    info "Applying dependency CRDs (hive, metal3, mce)..."
    kubectl apply -f "${ASSISTED_SERVICE_RAW}/hack/crds/hive/hive.openshift.io_clusterdeployments.yaml"
    kubectl apply -f "${ASSISTED_SERVICE_RAW}/hack/crds/hive/hive.openshift.io_clusterimagesets.yaml"
    kubectl apply -f "${ASSISTED_SERVICE_RAW}/hack/crds/metal3/metal3.io_baremetalhosts.yaml"
    kubectl apply -f "${ASSISTED_SERVICE_RAW}/hack/crds/metal3/metal3.io_preprovisioningimages.yaml"
    kubectl apply -f "${ASSISTED_SERVICE_RAW}/hack/crds/mce/managedclusters.cluster.open-cluster-management.io.yaml"

    # --- Infrastructure Operator (kustomize build requires the repo) ---
    info "Infrastructure Operator..."
    if kubectl get deployment infrastructure-operator -n assisted-installer &>/dev/null; then
        info "Already deployed"
    else
        if [[ ! -d "${ASSISTED_SERVICE_DIR}" ]]; then
            info "Cloning assisted-service (shallow, for operator manifests)..."
            git clone --depth 1 --filter=blob:none --sparse \
                https://github.com/openshift/assisted-service.git "${ASSISTED_SERVICE_DIR}"
            (cd "${ASSISTED_SERVICE_DIR}" && git sparse-checkout set config/)
        fi
        kustomize build "${ASSISTED_SERVICE_DIR}/config/default/" | kubectl apply -f -
    fi
    kubectl wait --for=condition=available --timeout=300s deployment/infrastructure-operator -n assisted-installer

    # --- AgentServiceConfig (starts the actual assisted-service) ---
    info "AgentServiceConfig..."
    if kubectl get agentserviceconfig agent -n assisted-installer &>/dev/null 2>&1; then
        info "Already exists"
    else
        info "Creating AgentServiceConfig..."
        kubectl apply -f - <<'AGENTCFG'
apiVersion: agent-install.openshift.io/v1beta1
kind: AgentServiceConfig
metadata:
  name: agent
spec:
  ingress:
    className: nginx
    assistedServiceHostname: assisted-service.kind.local
    imageServiceHostname: image-service.kind.local
  databaseStorage:
    accessModes: [ReadWriteOnce]
    resources:
      requests:
        storage: 8Gi
  filesystemStorage:
    accessModes: [ReadWriteOnce]
    resources:
      requests:
        storage: 8Gi
  imageStorage:
    accessModes: [ReadWriteOnce]
    resources:
      requests:
        storage: 10Gi
AGENTCFG
    fi

    # Wait for the assisted-service to create the CA secret
    info "Waiting for assisted-installer-ca secret..."
    local retries=0
    while ! kubectl get secret assisted-installer-ca -n assisted-installer &>/dev/null; do
        retries=$((retries + 1))
        if (( retries > 60 )); then
            err "Timed out waiting for assisted-installer-ca secret (5 min)"
        fi
        sleep 5
    done
    info "assisted-installer-ca secret is ready"

    # --- CAPI core ---
    info "CAPI core..."
    if kubectl get deployment capi-controller-manager -n capi-system &>/dev/null; then
        info "Already installed"
    else
        "${CLUSTERCTL}" init --core "cluster-api:${CLUSTERCTL_VERSION}" --bootstrap - --control-plane -
    fi
    kubectl wait --for=condition=available --timeout=300s deployment/capi-controller-manager -n capi-system

    # --- CAPOA providers ---
    local CAPOA_BASE_URL="https://github.com/openshift-assisted/cluster-api-provider-openshift-assisted/releases/download/${CAPOA_VERSION}"
    info "CAPOA providers ${CAPOA_VERSION}..."
    kubectl apply -f "${CAPOA_BASE_URL}/bootstrap-components.yaml"
    kubectl apply -f "${CAPOA_BASE_URL}/controlplane-components.yaml"
    kubectl wait --for=condition=available --timeout=180s \
        deployment/capoa-bootstrap-controller-manager -n capoa-bootstrap-system
    kubectl wait --for=condition=available --timeout=180s \
        deployment/capoa-controlplane-controller-manager -n capoa-controlplane-system

    info "CAPOA setup complete"
}

##############################################################################
# Phase 3: CAPI-AWS (CAPA) on the hub
##############################################################################
phase_capa() {
    log "Phase 3: Setting up CAPI-AWS (CAPA) on hub cluster"
    ensure_kubeconfig

    # --- CAPA provider ---
    info "CAPA provider ${CAPA_PROVIDER_VERSION}..."
    if kubectl get deployment capa-controller-manager -n capa-system &>/dev/null; then
        info "Already installed"
    else
        info "Deploying CAPA ${CAPA_PROVIDER_VERSION}..."
        local CAPA_BASE_URL="https://github.com/kubernetes-sigs/cluster-api-provider-aws/releases/download/${CAPA_PROVIDER_VERSION}"
        local TEMP_MANIFEST="/tmp/capa-components-${RANDOM}.yaml"

        # Download and substitute variables in the manifest for KIND/local deployment
        # Use environment variables if set, otherwise use reasonable defaults
        local AWS_CONTROLLER_IAM_ROLE="${AWS_CONTROLLER_IAM_ROLE:-}"
        local AWS_B64ENCODED_CREDENTIALS="${AWS_B64ENCODED_CREDENTIALS:-Zm9vYmFy}"
        local K8S_CP_LABEL="${K8S_CP_LABEL:-node-role.kubernetes.io/control-plane}"

        curl -fsSL "${CAPA_BASE_URL}/infrastructure-components.yaml" | \
            sed "s|\\\${AWS_CONTROLLER_IAM_ROLE[^}]*}|${AWS_CONTROLLER_IAM_ROLE}|g" | \
            sed "s|\\\${AWS_B64ENCODED_CREDENTIALS}|${AWS_B64ENCODED_CREDENTIALS}|g" | \
            sed "s|\\\${K8S_CP_LABEL:=[^}]*}|${K8S_CP_LABEL}|g" | \
            sed "s|\\\${K8S_CP_LABEL}|${K8S_CP_LABEL}|g" \
            > "${TEMP_MANIFEST}" || \
            err "Failed to download CAPA manifest"

        kubectl apply -f "${TEMP_MANIFEST}" || \
            err "Failed to deploy CAPA provider"

        rm -f "${TEMP_MANIFEST}"
    fi

    # Wait for CAPA controller to be ready
    kubectl wait --for=condition=available --timeout=300s deployment/capa-controller-manager -n capa-system 2>/dev/null || true

    info "CAPA setup complete"
}

##############################################################################
# Phase 4: OCM Lab Dashboard (Helm chart from GitHub)
##############################################################################
phase_dashboard() {
    log "Phase 4: Setting up OCM Dashboard on hub"
    ensure_kubeconfig

    # Clone the lab repo (sparse checkout — just the helm chart)
    local CHART_DIR="${OCM_LAB_DIR}/dashboard/charts/ocm-dashboard"
    if [[ ! -d "${CHART_DIR}" ]]; then
        info "Fetching OCM Dashboard chart from GitHub..."
        git clone --depth 1 --filter=blob:none --sparse \
            "${OCM_LAB_REPO}" "${OCM_LAB_DIR}"
        (cd "${OCM_LAB_DIR}" && git sparse-checkout set dashboard/charts/)
    fi

    # Install or upgrade the dashboard
    if helm status ocm-dashboard -n "${DASHBOARD_NS}" &>/dev/null; then
        info "Dashboard already installed — upgrading"
        helm upgrade ocm-dashboard "${CHART_DIR}" \
            --namespace "${DASHBOARD_NS}" \
            --set api.replicaCount=1 \
            --set ui.replicaCount=1 \
            --set api.image.repository=jpacker/dashboard-api \
            --set api.image.tag=latest \
            --set ui.image.repository=jpacker/dashboard-ui \
            --set ui.image.tag=latest \
            --set api.env.DASHBOARD_BYPASS_AUTH=true \
            --set ingress.enabled=false
    else
        info "Installing OCM Dashboard via Helm..."
        helm install ocm-dashboard "${CHART_DIR}" \
            --namespace "${DASHBOARD_NS}" --create-namespace \
            --set api.replicaCount=1 \
            --set ui.replicaCount=1 \
            --set api.image.repository=jpacker/dashboard-api \
            --set api.image.tag=latest \
            --set ui.image.repository=jpacker/dashboard-ui \
            --set ui.image.tag=latest \
            --set api.env.DASHBOARD_BYPASS_AUTH=true \
            --set ingress.enabled=false
    fi

    # Wait for pods
    kubectl wait --for=condition=available --timeout=120s \
        deployment -l app.kubernetes.io/instance=ocm-dashboard -n "${DASHBOARD_NS}"

    echo ""
    info "Dashboard deployed to namespace: ${DASHBOARD_NS}"
    info ""
    info "Access via port-forward:"
    info "  kubectl port-forward -n ${DASHBOARD_NS} svc/ocm-dashboard 3000:80"
    info "  Then open http://localhost:3000"
}

##############################################################################
# Utility: ensure KUBECONFIG points at the hub
##############################################################################
ensure_kubeconfig() {
    if [[ "${KUBECONFIG:-}" == "${HUB_KUBECONFIG}" ]] && [[ -f "${HUB_KUBECONFIG}" ]]; then
        return  # already set by set_hub_kubeconfig
    fi
    set_hub_kubeconfig
}

##############################################################################
# UI: generate token, show URL, run port-forward
##############################################################################
phase_ui() {
    log "OCM Dashboard"
    ensure_kubeconfig

    # Ensure the dashboard is deployed
    if ! helm status ocm-dashboard -n "${DASHBOARD_NS}" &>/dev/null; then
        err "Dashboard not installed. Run './setup.sh --dashboard' first."
    fi

    # Create ServiceAccount + ClusterRoleBinding if needed
    if ! kubectl get serviceaccount dashboard-user -n default &>/dev/null; then
        info "Creating dashboard-user service account..."
        kubectl create serviceaccount dashboard-user -n default
    fi
    if ! kubectl get clusterrolebinding dashboard-user &>/dev/null; then
        info "Creating cluster-admin binding..."
        kubectl create clusterrolebinding dashboard-user \
            --clusterrole=cluster-admin \
            --serviceaccount=default:dashboard-user
    fi

    # Generate token
    local token
    token="$(kubectl create token dashboard-user --duration=24h -n default)"

    echo ""
    info "URL:   http://localhost:3000"
    info ""
    info "Token (valid 24h):"
    echo ""
    echo "${token}"
    echo ""
    info "Paste the token into the login page, then click Sign In."
    info "Press Ctrl+C to stop port-forwarding."
    echo ""

    kubectl port-forward -n "${DASHBOARD_NS}" svc/ocm-dashboard 3000:80
}

##############################################################################
# Status
##############################################################################
phase_status() {
    log "Status"
    echo ""
    echo "KIND clusters:"
    kind get clusters 2>/dev/null || echo "  (none)"
    echo ""

    if [[ -f "${HUB_KUBECONFIG}" ]]; then
        export KUBECONFIG="${HUB_KUBECONFIG}"
        echo "Hub deployments:"
        for ns in cert-manager ingress-nginx assisted-installer capi-system capa-system capoa-bootstrap-system capoa-controlplane-system "${DASHBOARD_NS}"; do
            kubectl get deployment -n "${ns}" 2>/dev/null || true
        done
        echo ""
        echo "Managed clusters:"
        kubectl get managedclusters 2>/dev/null || echo "  (none)"
    fi
}

##############################################################################
# Teardown
##############################################################################
phase_teardown() {
    log "Tearing down everything"
    info "This will delete all KIND clusters and local state."
    read -r -p "    Continue? [y/N] " confirm
    [[ "${confirm}" =~ ^[Yy]$ ]] || { info "Aborted."; exit 0; }

    # Delete KIND clusters
    for cluster in hub cluster1 cluster2; do
        if kind get clusters 2>/dev/null | grep -q "^${cluster}$"; then
            info "Deleting KIND cluster: ${cluster}"
            kind delete cluster --name "${cluster}"
        fi
    done

    # Clean local state
    rm -f "${HUB_KUBECONFIG}"
    [[ -d "${ASSISTED_SERVICE_DIR}" ]] && info "Removing ${ASSISTED_SERVICE_DIR}" && rm -rf "${ASSISTED_SERVICE_DIR}"
    [[ -d "${OCM_LAB_DIR}" ]]         && info "Removing ${OCM_LAB_DIR}"          && rm -rf "${OCM_LAB_DIR}"

    info "Teardown complete"
}

##############################################################################
# Main
##############################################################################
main() {
    local mode="${1:-all}"

    case "${mode}" in
        --clusters)
            phase_prereqs
            timed "OCM + KIND clusters" phase_clusters
            ;;
        --capoa)
            phase_prereqs
            timed "CAPOA"               phase_capoa
            ;;
        --capa)
            phase_prereqs
            ensure_kubeconfig
            timed "CAPA"                phase_capa
            ;;
        --dashboard)
            phase_prereqs
            timed "Dashboard" phase_dashboard
            ;;
        --ui)
            phase_ui
            ;;
        --status)
            phase_status
            ;;
        --teardown)
            phase_teardown
            ;;
        all|"")
            local total_start
            total_start="$(date +%s)"

            phase_prereqs
            timed "OCM + KIND clusters" phase_clusters
            timed "CAPOA"               phase_capoa
            timed "CAPA"                phase_capa
            timed "Dashboard"           phase_dashboard

            local total_end total_elapsed total_m total_s
            total_end="$(date +%s)"
            total_elapsed=$(( total_end - total_start ))
            total_m=$(( total_elapsed / 60 ))
            total_s=$(( total_elapsed % 60 ))

            echo ""
            log "Setup complete!"
            echo ""
            echo "  Timing:"
            for t in "${TIMINGS[@]}"; do
                echo "    ${t}"
            done
            echo "    $(printf '%-40s %dm %02ds' 'Total' "${total_m}" "${total_s}")"
            echo ""
            echo "  Hub kubeconfig:  export KUBECONFIG=${HUB_KUBECONFIG}"
            echo "  Dashboard:       ./setup.sh --ui"
            echo ""
            echo "  ./setup.sh --ui         open dashboard"
            echo "  ./setup.sh --status     check status"
            echo "  ./setup.sh --teardown   delete everything"
            ;;
        *)
            echo "Usage: $0 [--clusters|--capoa|--capa|--dashboard|--ui|--status|--teardown]"
            exit 1
            ;;
    esac
}

main "$@"
