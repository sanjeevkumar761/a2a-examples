# A2A Multi-Agent KEDA Scaling — Full Setup Guide

This document walks through every step taken to set up the A2A multi-agent procurement demo on Azure Kubernetes Service with KEDA event-driven autoscaling. It covers both the code implementation and the Azure infrastructure deployment.

---

## Table of Contents

1. [What We Built](#1-what-we-built)
2. [Code Changes — Service Bus Integration](#2-code-changes--service-bus-integration)
3. [Kubernetes Manifests — KEDA + Workload Identity](#3-kubernetes-manifests--keda--workload-identity)
4. [Azure Infrastructure Provisioning](#4-azure-infrastructure-provisioning)
5. [Building and Pushing Container Images](#5-building-and-pushing-container-images)
6. [Deploying to AKS](#6-deploying-to-aks)
7. [Configuring KEDA with Workload Identity](#7-configuring-keda-with-workload-identity)
8. [Running the KEDA Scaling Demo](#8-running-the-keda-scaling-demo)
9. [Troubleshooting Notes](#9-troubleshooting-notes)
10. [Resource Summary](#10-resource-summary)

---

## 1. What We Built

The project started with three A2A agents (Orchestrator, Invoice, PO) that communicate over synchronous HTTP. We added:

- **Azure Service Bus transport** — agents can now communicate via queues instead of HTTP, toggled by `USE_SERVICEBUS=true`
- **KEDA ScaledObjects** — agent pods scale from 0 to N based on Service Bus queue depth
- **Load test script** — floods queues with fake invoices to trigger scaling in real-time
- **Azure infrastructure automation** — one-command setup for AKS, ACR, Service Bus, KEDA, and Managed Identity

### Architecture

```
    User → Orchestrator → Service Bus Queue (invoice-requests) → Invoice Agent (KEDA: 0→10)
                        → Service Bus Queue (po-requests)      → PO Agent     (KEDA: 0→5)

    Invoice Agent → Service Bus Queue (invoice-responses) → Orchestrator
    PO Agent      → Service Bus Queue (po-responses)      → Orchestrator
```

The key insight: KEDA monitors the **request queues**. When messages accumulate, it scales up agent pods. When the queues drain, pods scale back to zero. Zero traffic = zero compute cost.

---

## 2. Code Changes — Service Bus Integration

### 2.1 Shared Transport Helper (`agents/common/servicebus.py`)

We created a reusable async Service Bus client that all agents share. It provides three methods:

| Method | Purpose |
|--------|---------|
| `send_message(queue, payload, correlation_id)` | Send a JSON message to a queue |
| `receive_response(queue, correlation_id, timeout)` | Wait for a response matching a correlation ID |
| `consume_queue(queue, handler, response_queue)` | Continuously consume messages and call a handler |

Key design decisions:
- Uses `azure.identity.aio.DefaultAzureCredential` for passwordless auth (works with Workload Identity on AKS and `az login` locally)
- Correlation IDs (UUIDs) tie requests to responses so the orchestrator knows which reply belongs to which request
- Failed messages are dead-lettered to prevent poison messages from blocking the queue
- The `SERVICEBUS_FQDN` environment variable configures the connection (e.g., `sb-a2a-demo.servicebus.windows.net`)

### 2.2 Orchestrator Agent (`agents/orchestrator/agent.py`)

Added a transport toggle controlled by the `USE_SERVICEBUS` environment variable:

```python
self.use_servicebus = os.getenv("USE_SERVICEBUS", "false").lower() == "true"
if self.use_servicebus:
    self._sb_transport = ServiceBusTransport()
```

When enabled, the orchestrator's `_validate_invoice()` and `_create_po()` methods send to Service Bus queues instead of making HTTP calls:

```python
if self.use_servicebus:
    response_text = await self._send_via_servicebus(
        INVOICE_REQUEST_QUEUE, INVOICE_RESPONSE_QUEUE, invoice_data
    )
else:
    await self._ensure_clients()
    response_text = await self._send_a2a_message(self.invoice_client, json.dumps(invoice_data))
```

The `_send_via_servicebus()` method sends a message to the request queue with a correlation ID, then polls the response queue until a matching reply arrives (or times out after 120 seconds).

**Why a toggle?** HTTP remains the default for local development (no Azure dependency). Service Bus is enabled only in AKS production where KEDA scaling is needed.

### 2.3 Invoice Agent Server (`agents/invoice_agent/server.py`)

Added a background Service Bus consumer that runs alongside the HTTP server:

```python
if use_servicebus:
    async def _run():
        config = uvicorn.Config(app, host="0.0.0.0", port=port)
        server = uvicorn.Server(config)
        await asyncio.gather(
            server.serve(),                  # HTTP server (for health checks)
            _start_servicebus_consumer(),    # Service Bus consumer loop
        )
    asyncio.run(_run())
```

The consumer:
1. Picks up messages from the `invoice-requests` queue
2. Runs them through the existing `validate_invoice()` LangGraph workflow (no changes needed to business logic)
3. Publishes the result to `invoice-responses` with the same correlation ID

**Why keep the HTTP server running?** Kubernetes liveness/readiness probes hit the `/.well-known/agent.json` endpoint. Without the HTTP server, K8s would think the pod is unhealthy and kill it.

### 2.4 PO Agent Server (`agents/po_agent/server.py`)

Same pattern as the Invoice Agent — consumes from `po-requests`, publishes to `po-responses`.

### 2.5 Dockerfiles

Each Dockerfile was updated to copy the shared `agents/common/` module:

```dockerfile
COPY agents/invoice_agent/ .
COPY agents/common/ /common/     # <-- Added this line
```

The `common/` folder is placed at `/common/` in the container because the `sys.path.insert` in the agent code resolves to the parent of `/app/`:
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# __file__ = /app/server.py → dirname = /app → parent = /
# So "from common.servicebus import ..." finds /common/servicebus.py
```

### 2.6 Dependencies

Added `aiohttp` to `requirements.txt` — required by `azure-identity` for async HTTP transport:

```
aiohttp>=3.9.0
```

This was discovered when the container crashed with `ImportError: aiohttp package is not installed`. The `azure.identity.aio.DefaultAzureCredential` uses aiohttp internally.

---

## 3. Kubernetes Manifests — KEDA + Workload Identity

### 3.1 Namespace + Service Account (`k8s/namespace.yaml`)

Added a ServiceAccount annotated for Azure Workload Identity:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: default
  namespace: a2a-agents
  annotations:
    azure.workload.identity/client-id: "0241e5c1-83d6-4f23-9c86-97e61b5d038a"
  labels:
    azure.workload.identity/use: "true"
```

This annotation tells the AKS workload identity mutating webhook to inject `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_FEDERATED_TOKEN_FILE` environment variables into any pod using this service account.

### 3.2 ConfigMap (`k8s/configmap.yaml`)

Added Service Bus configuration:

```yaml
data:
  USE_SERVICEBUS: "true"
  SERVICEBUS_FQDN: "sb-a2a-demo.servicebus.windows.net"
```

### 3.3 Agent Deployments (`invoice-agent.yaml`, `po-agent.yaml`, `orchestrator.yaml`)

Each deployment was updated with:

1. **Workload Identity label** on the pod template:
   ```yaml
   labels:
     azure.workload.identity/use: "true"
   ```

2. **Service Bus env vars** from the ConfigMap:
   ```yaml
   - name: USE_SERVICEBUS
     valueFrom:
       configMapKeyRef:
         name: agent-config
         key: USE_SERVICEBUS
   - name: SERVICEBUS_FQDN
     valueFrom:
       configMapKeyRef:
         name: agent-config
         key: SERVICEBUS_FQDN
   ```

3. **serviceAccountName: default** — explicitly set so the workload identity webhook injects credentials

### 3.4 KEDA TriggerAuthentication (`k8s/keda/trigger-auth.yaml`)

```yaml
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: azure-servicebus-auth
  namespace: a2a-agents
spec:
  podIdentity:
    provider: azure-workload
    identityId: "0241e5c1-83d6-4f23-9c86-97e61b5d038a"
```

This tells KEDA to use Azure Workload Identity when connecting to Service Bus to read queue metrics. The `identityId` is the Managed Identity's client ID.

### 3.5 KEDA ScaledObjects (`k8s/keda/invoice-scaledobject.yaml`, `po-scaledobject.yaml`)

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: invoice-agent-scaler
  namespace: a2a-agents
spec:
  scaleTargetRef:
    name: invoice-agent          # Deployment to scale
  minReplicaCount: 0              # Scale to zero when idle
  maxReplicaCount: 10             # Maximum burst capacity
  cooldownPeriod: 300             # 5 minutes before scaling down
  pollingInterval: 15             # Check queue every 15 seconds
  triggers:
  - type: azure-servicebus
    metadata:
      queueName: invoice-requests
      namespace: sb-a2a-demo      # Service Bus namespace name
      messageCount: "5"           # Scale up when > 5 messages
    authenticationRef:
      name: azure-servicebus-auth
```

**How KEDA scaling works:**
- Every 15 seconds, KEDA checks the `invoice-requests` queue message count
- If `activeMessageCount > 5`, KEDA increases the replica count
- The formula: `desiredReplicas = ceil(activeMessageCount / messageCount)`
- So 30 messages → `ceil(30/5)` = 6 pods
- When the queue drains to 0, KEDA waits 300 seconds (cooldown), then scales to 0

---

## 4. Azure Infrastructure Provisioning

### 4.1 Resource Group

```powershell
az group create --name rg-a2a-keda-demo --location eastus2
```

### 4.2 Azure Container Registry

```powershell
az acr create --resource-group rg-a2a-keda-demo --name acra2ademo584 --sku Basic
```

Basic SKU is sufficient for a demo — it provides 10 GiB storage and 2 webhooks.

### 4.3 AKS Cluster

```powershell
az aks create `
  --resource-group rg-a2a-keda-demo `
  --name aks-a2a-demo `
  --node-count 3 `
  --enable-oidc-issuer `
  --enable-workload-identity `
  --attach-acr acra2ademo584 `
  --generate-ssh-keys
```

Key flags:
- `--enable-oidc-issuer` — enables the OpenID Connect issuer URL on the cluster (required for workload identity federation)
- `--enable-workload-identity` — installs the workload identity mutating webhook that injects credentials into pods
- `--attach-acr` — grants the AKS cluster pull access to the container registry
- `--node-count 3` — three nodes for distributing agent pods

After creation, get the kubeconfig:
```powershell
az aks get-credentials --resource-group rg-a2a-keda-demo --name aks-a2a-demo --overwrite-existing
```

### 4.4 Install KEDA via Helm

Helm wasn't installed on the machine, so we installed it first:
```powershell
winget install Helm.Helm
```

Then refreshed the PATH and installed KEDA:
```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
helm repo add kedacore https://kedacore.github.io/charts
helm repo update kedacore
helm upgrade --install keda kedacore/keda --namespace keda --create-namespace --wait
```

This deploys three pods in the `keda` namespace:
- `keda-operator` — the main KEDA controller that watches ScaledObjects and manages HPAs
- `keda-operator-metrics-apiserver` — exposes custom metrics to the Kubernetes metrics API
- `keda-admission-webhooks` — validates KEDA CRDs on creation

### 4.5 Azure Service Bus Namespace + Queues

```powershell
az servicebus namespace create `
  --resource-group rg-a2a-keda-demo `
  --name sb-a2a-demo `
  --sku Standard `
  --location eastus2
```

Standard SKU is required for queues (Basic doesn't support topics, but Standard supports everything we need).

Created four queues:
```powershell
$queues = @("invoice-requests", "invoice-responses", "po-requests", "po-responses")
foreach ($q in $queues) {
    az servicebus queue create `
      --resource-group rg-a2a-keda-demo `
      --namespace-name sb-a2a-demo `
      --name $q
}
```

**Why four queues?** Each agent type gets a request/response pair. This allows independent scaling — invoice processing load doesn't affect PO agent scaling, and vice versa.

### 4.6 Managed Identity + Federated Credentials

Created a user-assigned managed identity:
```powershell
az identity create --resource-group rg-a2a-keda-demo --name id-a2a-agents
```

Granted it `Azure Service Bus Data Owner` role:
```powershell
$IDENTITY_OBJECT_ID = az identity show --resource-group rg-a2a-keda-demo --name id-a2a-agents --query principalId -o tsv
$SB_RESOURCE_ID = az servicebus namespace show --resource-group rg-a2a-keda-demo --name sb-a2a-demo --query id -o tsv

az role assignment create `
  --role "Azure Service Bus Data Owner" `
  --assignee-object-id $IDENTITY_OBJECT_ID `
  --assignee-principal-type ServicePrincipal `
  --scope $SB_RESOURCE_ID
```

Created federated credentials that link Kubernetes service accounts to this identity:

**For agent pods** (in the `a2a-agents` namespace):
```powershell
az identity federated-credential create `
  --name "fed-a2a-agents" `
  --identity-name id-a2a-agents `
  --resource-group rg-a2a-keda-demo `
  --issuer $AKS_OIDC_ISSUER `
  --subject "system:serviceaccount:a2a-agents:default" `
  --audiences "api://AzureADTokenExchange"
```

**For the KEDA operator** (in the `keda` namespace):
```powershell
az identity federated-credential create `
  --name "fed-keda-operator" `
  --identity-name id-a2a-agents `
  --resource-group rg-a2a-keda-demo `
  --issuer $AKS_OIDC_ISSUER `
  --subject "system:serviceaccount:keda:keda-operator" `
  --audiences "api://AzureADTokenExchange"
```

**Why two federated credentials?** The agent pods and the KEDA operator run in different namespaces with different service accounts. Each needs its own federation to the same managed identity. The KEDA operator needs this so it can read queue metrics. The agent pods need it to send/receive messages.

### 4.7 Granting Data Plane Access for Load Testing

The load test script runs on the local machine, so we also granted the current user `Service Bus Data Owner`:
```powershell
$currentUser = az ad signed-in-user show --query id -o tsv
az role assignment create `
  --role "Azure Service Bus Data Owner" `
  --assignee-object-id $currentUser `
  --assignee-principal-type User `
  --scope $SB_RESOURCE_ID
```

---

## 5. Building and Pushing Container Images

We used ACR Tasks to build images remotely (no local Docker needed):

```powershell
az acr build --registry acra2ademo584 --image a2a-orchestrator:latest -f docker/Dockerfile.orchestrator .
az acr build --registry acra2ademo584 --image a2a-invoice-agent:latest -f docker/Dockerfile.invoice .
az acr build --registry acra2ademo584 --image a2a-po-agent:latest -f docker/Dockerfile.po .
```

Each build:
1. Tars the source code and uploads it to ACR (~18 MB)
2. ACR builds the Docker image on its own compute
3. Pushes the image to the registry
4. Takes about 50-60 seconds per image

We had to rebuild once after discovering the missing `aiohttp` dependency. The `--no-logs` flag was used with the rebuilds to avoid a Unicode encoding issue in the PowerShell terminal.

---

## 6. Deploying to AKS

Deployed in order (namespace first, then resources, then KEDA):

```powershell
# Namespace + service account
kubectl apply -f k8s/namespace.yaml

# Core resources
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/invoice-agent.yaml
kubectl apply -f k8s/po-agent.yaml
kubectl apply -f k8s/orchestrator.yaml

# KEDA ScaledObjects
kubectl apply -f k8s/keda/trigger-auth.yaml
kubectl apply -f k8s/keda/invoice-scaledobject.yaml
kubectl apply -f k8s/keda/po-scaledobject.yaml
```

After deployment, the initial state was:
- `redis` — 1/1 Running
- `orchestrator` — 1/1 Running (always on, serves the LoadBalancer endpoint)
- `invoice-agent` — 1/1 Running (before KEDA takes control)
- `po-agent` — 1/1 Running (before KEDA takes control)

Once KEDA ScaledObjects became `READY: True`, KEDA took over replica management and scaled invoice-agent and po-agent to **0 pods** (since the queues were empty).

---

## 7. Configuring KEDA with Workload Identity

This was the most involved step. KEDA needs to authenticate to Azure Service Bus to read queue metrics, and the Service Bus namespace in this subscription had **SAS (shared access key) authentication disabled** by policy. This forced us to use Azure AD / Workload Identity for KEDA.

### Problem: KEDA operator didn't have Workload Identity credentials

Initially, the KEDA TriggerAuthentication was configured with `podIdentity: azure-workload`, but the KEDA operator pod didn't have the Workload Identity environment variables injected (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_FEDERATED_TOKEN_FILE`).

### Root Cause

The AKS workload identity mutating webhook only injects credentials into pods that have the label `azure.workload.identity/use: "true"`. The KEDA Helm chart doesn't include this label by default.

### Solution

1. **Annotated the KEDA operator service account:**
```powershell
kubectl annotate serviceaccount keda-operator -n keda `
  "azure.workload.identity/client-id=0241e5c1-83d6-4f23-9c86-97e61b5d038a" --overwrite
kubectl label serviceaccount keda-operator -n keda `
  "azure.workload.identity/use=true" --overwrite
```

2. **Patched the KEDA operator deployment** to add the workload identity label to the pod template:
```powershell
$patch = '{"spec":{"template":{"metadata":{"labels":{"azure.workload.identity/use":"true"}}}}}'
kubectl patch deployment keda-operator -n keda --type=strategic -p $patch
```

This triggers a rolling restart. The new pod is created with the label, and the mutating webhook injects:
- `AZURE_CLIENT_ID=0241e5c1-83d6-4f23-9c86-97e61b5d038a`
- `AZURE_TENANT_ID=16b3c013-d300-468d-ac64-7eda0820b6d3`
- `AZURE_FEDERATED_TOKEN_FILE=/var/run/secrets/azure/tokens/azure-identity-token`
- A projected volume `azure-identity-token` mounted into the pod

3. **Verified the injection:**
```powershell
kubectl get pod -n keda -l app=keda-operator `
  -o jsonpath='{range .items[0].spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}'
```

After this, the KEDA ScaledObjects transitioned to `READY: True` and KEDA could successfully read queue metrics.

---

## 8. Running the KEDA Scaling Demo

### The Load Test Script (`scripts/demo-load.py`)

The script uses `AzureCliCredential` (picks up the local `az login` session) to send fake invoice messages to the Service Bus queue:

```powershell
$env:SERVICEBUS_FQDN = "sb-a2a-demo.servicebus.windows.net"
uv run python scripts/demo-load.py --count 30 --queue invoice-requests --delay 0.1
```

### What Happened

```
T+0s    0 invoice-agent pods (scale-to-zero)
        Only orchestrator + redis running

T+7s    Load test sent 30 invoices to Service Bus in 7.2 seconds
        Queue: 23+ active messages

T+15s   KEDA detected queue depth > 5
        → Scaled invoice-agent from 0 → 4 pods
        invoice-agent-6649c6ddf-6sqgw   ContainerCreating → Running
        invoice-agent-6649c6ddf-rfvlw   ContainerCreating
        invoice-agent-6649c6ddf-qkv56   ContainerCreating
        invoice-agent-6649c6ddf-95pcp   ContainerCreating

T+30s   KEDA scaled further → 6 pods total
        invoice-agent-6649c6ddf-z6dhd   Running
        invoice-agent-6649c6ddf-5rvdf   Running

T+75s   All 6 pods Running 1/1
        HPA target: 0/5 (avg) — queue is draining

T+5min  After cooldown, pods scale back to 0
```

### Monitoring Commands

```powershell
# Watch pods scale in real-time (leave running in a terminal)
kubectl get pods -n a2a-agents -w

# Check KEDA ScaledObject status
kubectl get scaledobjects -n a2a-agents

# Check HPA managed by KEDA
kubectl get hpa -n a2a-agents

# Verify queue message count
az servicebus queue show --resource-group rg-a2a-keda-demo --namespace-name sb-a2a-demo `
  --name invoice-requests --query "{activeMessages:countDetails.activeMessageCount}" -o json

# Check KEDA operator logs (for debugging)
kubectl logs -n keda deployment/keda-operator --tail=20
```

---

## 9. Troubleshooting Notes

Issues we encountered and how they were resolved:

### 9.1 Missing `aiohttp` dependency

**Symptom:** Invoice agent pod crashed with `ImportError: aiohttp package is not installed`

**Cause:** `azure-identity` async credential classes use `aiohttp` internally, but it's not a direct dependency.

**Fix:** Added `aiohttp>=3.9.0` to `requirements.txt` and rebuilt all container images.

### 9.2 SAS auth disabled on Service Bus

**Symptom:** KEDA logs showed `LocalAuthDisabled: Authorization failed because SAS authentication has been disabled`

**Cause:** The Azure subscription has a policy that enforces `disableLocalAuth=true` on Service Bus namespaces. SAS connection strings can't be used.

**Fix:** Switched KEDA TriggerAuthentication from connection-string-based auth to Azure Workload Identity.

### 9.3 KEDA operator not getting Workload Identity tokens

**Symptom:** KEDA logs showed `sources must contain at least one TokenCredential`

**Cause:** The KEDA operator pod didn't have the `azure.workload.identity/use: "true"` label, so the AKS mutating webhook didn't inject the identity environment variables.

**Fix:** Patched the KEDA operator deployment with a strategic merge patch to add the label to the pod template. Also created a federated credential for the `keda:keda-operator` service account.

### 9.4 `az servicebus queue message send` doesn't exist

**Symptom:** Load test appeared to send messages (no errors), but queue remained empty.

**Cause:** The installed version of Azure CLI doesn't have the `az servicebus queue message send` subcommand. The send calls were silently failing because errors were piped to `Out-Null`.

**Fix:** Rewrote the load test script to use the `azure-servicebus` Python SDK with `AzureCliCredential` instead of the az CLI.

### 9.5 Unicode encoding error in PowerShell

**Symptom:** `az acr build` output piped through `Select-Object` threw `UnicodeEncodeError: 'charmap' codec can't encode characters`.

**Cause:** ACR build logs contain Unicode characters (progress bars, emoji) that can't be encoded in the Windows cp1252 codepage.

**Fix:** Used `--no-logs` flag with `az acr build` to suppress streaming logs and just return the JSON result.

---

## 10. Resource Summary

### Azure Resources Created

| Resource | Name | Purpose |
|----------|------|---------|
| Resource Group | `rg-a2a-keda-demo` | Container for all resources |
| AKS Cluster | `aks-a2a-demo` | 3-node cluster with OIDC + Workload Identity |
| Container Registry | `acra2ademo584` | Private registry for agent images |
| Service Bus Namespace | `sb-a2a-demo` | Message broker (Standard SKU) |
| Queue | `invoice-requests` | Inbound invoices for validation |
| Queue | `invoice-responses` | Validation results back to orchestrator |
| Queue | `po-requests` | Inbound PO creation requests |
| Queue | `po-responses` | PO creation results back to orchestrator |
| Managed Identity | `id-a2a-agents` | Passwordless auth for Service Bus + OpenAI |
| Federated Credential | `fed-a2a-agents` | Links `a2a-agents:default` SA to identity |
| Federated Credential | `fed-keda-operator` | Links `keda:keda-operator` SA to identity |
| KEDA (Helm) | `keda` namespace | Event-driven pod autoscaler |

### Container Images

| Image | Registry | Source |
|-------|----------|--------|
| `a2a-orchestrator:latest` | `acra2ademo584.azurecr.io` | `docker/Dockerfile.orchestrator` |
| `a2a-invoice-agent:latest` | `acra2ademo584.azurecr.io` | `docker/Dockerfile.invoice` |
| `a2a-po-agent:latest` | `acra2ademo584.azurecr.io` | `docker/Dockerfile.po` |

### Kubernetes Resources (in `a2a-agents` namespace)

| Resource | Name | Notes |
|----------|------|-------|
| Deployment | `orchestrator` | Always running (1 replica), LoadBalancer service |
| Deployment | `invoice-agent` | KEDA-managed (0–10 replicas) |
| Deployment | `po-agent` | KEDA-managed (0–5 replicas) |
| Deployment | `redis` | Caching (1 replica) |
| ConfigMap | `agent-config` | URLs, Service Bus config |
| Secret | `azure-openai-secret` | Azure OpenAI endpoint + credentials |
| ScaledObject | `invoice-agent-scaler` | Scales on `invoice-requests` queue depth > 5 |
| ScaledObject | `po-agent-scaler` | Scales on `po-requests` queue depth > 3 |
| TriggerAuthentication | `azure-servicebus-auth` | Workload Identity for KEDA |

### Files Created/Modified

| File | Status | Purpose |
|------|--------|---------|
| `agents/common/__init__.py` | New | Package init |
| `agents/common/servicebus.py` | New | Shared async Service Bus transport |
| `agents/orchestrator/agent.py` | Modified | Added `USE_SERVICEBUS` toggle |
| `agents/invoice_agent/server.py` | Modified | Added Service Bus consumer loop |
| `agents/po_agent/server.py` | Modified | Added Service Bus consumer loop |
| `k8s/namespace.yaml` | Modified | Added Workload Identity ServiceAccount |
| `k8s/configmap.yaml` | Modified | Added Service Bus config |
| `k8s/secrets.yaml` | Modified | Updated with actual OpenAI endpoint |
| `k8s/orchestrator.yaml` | New | Orchestrator Deployment + LoadBalancer |
| `k8s/invoice-agent.yaml` | Modified | Added Service Bus env vars + WI labels |
| `k8s/po-agent.yaml` | Modified | Added Service Bus env vars + WI labels |
| `k8s/keda/trigger-auth.yaml` | New | KEDA Workload Identity auth |
| `k8s/keda/invoice-scaledobject.yaml` | New | Invoice agent KEDA scaler (0→10) |
| `k8s/keda/po-scaledobject.yaml` | New | PO agent KEDA scaler (0→5) |
| `docker/Dockerfile.orchestrator` | Modified | Added `COPY agents/common/` |
| `docker/Dockerfile.invoice` | Modified | Added `COPY agents/common/` |
| `docker/Dockerfile.po` | Modified | Added `COPY agents/common/` |
| `scripts/setup-azure.sh` | New | Azure infrastructure provisioning |
| `scripts/demo-load.py` | New | Load test to trigger KEDA scaling |
| `requirements.txt` | Modified | Added `aiohttp>=3.9.0` |
| `.env.example` | Modified | Added `USE_SERVICEBUS`, `SERVICEBUS_FQDN` |
| `DEMO.md` | Modified | Full 4-part demo walkthrough |
| `README.md` | Modified | Updated project structure + deployment steps |

### Cleanup

To tear down all Azure resources when the demo is no longer needed:
```powershell
az group delete --name rg-a2a-keda-demo --yes --no-wait
```
