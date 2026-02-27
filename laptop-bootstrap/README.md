# From a Laptop

## Prerequisites
* [kubectl (Linux/macOS)](https://kubernetes.io/docs/tasks/tools/#kubectl)
* [kustomize (Linux/macOS)](https://kustomize.io/)
* [kind (Linux/macOS)](https://kind.sigs.k8s.io/) (v0.9.0+)
* [podman (Linux](https://podman.io/docs/installation) / [macOS)](https://podman.io/docs/installation/macos) - **WSL users only**

## Quick Start

See [OCM Quickstart](https://ocm.io/getting-started/quick-start/) for more details.

```bash
# Install clusteradm
curl -L https://raw.githubusercontent.com/open-cluster-management-io/clusteradm/main/install.sh | bash

# Setup OCM hub and managed clusters (creates kind clusters with podman)
# WSL ONLY: Start the podman machine before running the setup
podman machine start

# Run the setup script (works on macOS, Linux, and WSL with podman machine started)
curl -L https://raw.githubusercontent.com/open-cluster-management-io/OCM/main/solutions/setup-dev-environment/local-up.sh | bash
```

## Console (Optional)

See [OCM Lab Dashboard](https://github.com/open-cluster-management-io/lab) for more details.

```bash
git clone git@github.com:open-cluster-management-io/lab.git
cd lab/dashboard

export DASHBOARD_BYPASS_AUTH=true
export KUBECONFIG=$(mktemp)
kind get kubeconfig --name hub > $KUBECONFIG

make dev-apiserver-real

# In another terminal, run the dev server
npm install
npm run dev

# In another terminal, create a token for authentication
kubectl create serviceaccount dashboard-user -n default
kubectl create clusterrolebinding dashboard-user --clusterrole=cluster-admin --serviceaccount=default:dashboard-user
kubectl create token dashboard-user --duration=24h
```
