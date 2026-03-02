# A2A Multi-Agent Procurement Demo

## Overview

This demo showcases a **multi-agent procurement system** using Google's [A2A (Agent-to-Agent) protocol](https://github.com/a2aproject/a2a-python) for inter-agent communication. Three independent agents collaborate to process invoices, create purchase orders, and schedule payments — all coordinated through a central orchestrator.

The system supports two communication modes:
- **HTTP/A2A** — synchronous, ideal for local development
- **Azure Service Bus** — asynchronous queue-based messaging with **KEDA event-driven autoscaling** on AKS

### Key Technologies

| Component | Technology |
|-----------|-----------|
| Agent Protocol | [A2A SDK v0.3.x](https://github.com/a2aproject/a2a-python) (JSON-RPC 2.0) |
| Agent Framework | [LangGraph](https://langchain-ai.github.io/langgraph/) with conditional edges |
| LLM | Azure OpenAI (GPT-4.1) |
| Authentication | `DefaultAzureCredential` — token-based, no API keys |
| Transport | HTTP (local dev) / Azure Service Bus (AKS production) |
| Scaling | KEDA on AKS — scale-to-zero based on Service Bus queue depth |
| Infrastructure | Azure Kubernetes Service + Azure Container Registry |

---

## Architecture

### Mode 1 — HTTP/A2A (Local Development)

```
                          ┌──────────────────────────┐
                          │   Orchestrator Agent     │
       HTTP Request ──────►     (Port 8000)          │
                          │  LangGraph Workflow      │
                          │  - Analyze Request       │
                          │  - Route to Sub-Agents   │
                          │  - Generate LLM Summary  │
                          └────┬───────────┬─────────┘
                               │           │
                    A2A/HTTP   │           │   A2A/HTTP
                               │           │
              ┌────────────────▼──┐   ┌────▼─────────────────┐
              │  Invoice Agent    │   │  Purchase Order Agent │
              │   (Port 8001)     │   │    (Port 8002)        │
              │                   │   │                       │
              │ - Format checks   │   │ - Budget validation   │
              │ - Amount matching │   │ - Vendor lookup       │
              │ - LLM compliance  │   │ - PO creation         │
              └───────────────────┘   └───────────────────────┘
```

### Mode 2 — Azure Service Bus + KEDA (AKS Production)

```
                          ┌──────────────────────────┐
                          │   Orchestrator Agent     │
       HTTP Request ──────►     (Port 8000)          │
                          │  LangGraph Workflow      │
                          └────┬───────────┬─────────┘
                               │           │
                    ┌──────────▼──┐   ┌────▼──────────┐
                    │  SB Queue:  │   │  SB Queue:    │
                    │  invoice-   │   │  po-          │
                    │  requests   │   │  requests     │
                    └──────┬──────┘   └────┬──────────┘
                           │               │
              ┌────────────▼──┐   ┌────────▼─────────┐
              │  Invoice Agent │   │  PO Agent        │
              │  (KEDA: 0→10) │   │  (KEDA: 0→5)    │
              └────────┬───────┘   └────────┬─────────┘
                       │                    │
                    ┌──▼──────────┐   ┌─────▼─────────┐
                    │  SB Queue:  │   │  SB Queue:    │
                    │  invoice-   │   │  po-           │
                    │  responses  │   │  responses     │
                    └──────┬──────┘   └────┬──────────┘
                           │               │
                          ┌▼───────────────▼─┐
                          │   Orchestrator    │
                          │  (await reply)    │
                          └──────────────────┘
```

When `USE_SERVICEBUS=true`, the orchestrator sends work items to Service Bus queues instead of making direct HTTP calls. Each agent runs a background consumer loop that picks up messages, processes them through its LangGraph workflow, and publishes results to a response queue. KEDA monitors the request queues and scales agent pods from **0 to N** based on queue depth.

---

## Project Structure

```
a2a-multi-agent-keda-scaling/
├── agents/
│   ├── common/
│   │   └── servicebus.py           # Shared Azure Service Bus transport
│   ├── orchestrator/
│   │   ├── agent.py                 # LangGraph workflow + Service Bus toggle
│   │   └── server.py               # A2A Starlette server
│   ├── invoice_agent/
│   │   ├── agent.py                 # LangGraph invoice validation workflow
│   │   └── server.py               # A2A server + Service Bus consumer
│   └── po_agent/
│       ├── agent.py                 # LangGraph PO management workflow
│       └── server.py               # A2A server + Service Bus consumer
├── k8s/
│   ├── namespace.yaml               # a2a-agents namespace
│   ├── configmap.yaml               # Agent config + Service Bus settings
│   ├── secrets.yaml                 # Azure OpenAI credentials
│   ├── orchestrator.yaml            # Orchestrator Deployment + LoadBalancer
│   ├── invoice-agent.yaml           # Invoice Agent Deployment + ClusterIP
│   ├── po-agent.yaml                # PO Agent Deployment + ClusterIP
│   ├── redis.yaml                   # Redis for caching
│   └── keda/
│       ├── trigger-auth.yaml        # Workload Identity auth for KEDA
│       ├── invoice-scaledobject.yaml # Scale invoice-agent 0→10 on queue depth
│       └── po-scaledobject.yaml     # Scale po-agent 0→5 on queue depth
├── docker/
│   ├── docker-compose.yml           # Local multi-container setup
│   ├── Dockerfile.base
│   ├── Dockerfile.orchestrator
│   ├── Dockerfile.invoice
│   └── Dockerfile.po
├── scripts/
│   ├── setup-azure.sh               # One-command: AKS + ACR + Service Bus + KEDA + Identity
│   └── demo-load.py                 # Flood queues to trigger KEDA scaling
├── pyproject.toml
├── requirements.txt
├── .env.example
├── DEMO.md                          # ← You are here
└── README.md
```

---

## Part 1: Running the Demo (Local — HTTP Mode)

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Azure CLI logged in (`az login`)
- Access to an Azure OpenAI deployment

### 1. Install Dependencies

```powershell
uv sync
```

### 2. Configure Environment

Create a `.env` file in the project root:

```env
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

> **Note:** No API key needed — the agents use `DefaultAzureCredential` which picks up your `az login` session automatically.

### 3. Start All Three Agents

Open **three separate terminals** and run one agent in each:

**Terminal 1 — Invoice Validation Agent (port 8001):**
```powershell
cd agents/invoice_agent
..\..\..\..\vscoderepos\a2a-multi-agent-keda-scaling\.venv\Scripts\python server.py
```

**Terminal 2 — Purchase Order Agent (port 8002):**
```powershell
cd agents/po_agent
..\..\..\..\vscoderepos\a2a-multi-agent-keda-scaling\.venv\Scripts\python server.py
```

**Terminal 3 — Orchestrator Agent (port 8000):**
```powershell
cd agents/orchestrator
..\..\..\..\vscoderepos\a2a-multi-agent-keda-scaling\.venv\Scripts\python server.py
```

You should see `Uvicorn running on http://0.0.0.0:800x` for each agent.

### 4. Verify Agent Discovery

Each agent exposes an A2A agent card at `/.well-known/agent-card.json`:

```powershell
# Orchestrator
Invoke-RestMethod http://localhost:8000/.well-known/agent-card.json | ConvertTo-Json -Depth 5

# Invoice Agent
Invoke-RestMethod http://localhost:8001/.well-known/agent-card.json | ConvertTo-Json -Depth 5

# PO Agent
Invoke-RestMethod http://localhost:8002/.well-known/agent-card.json | ConvertTo-Json -Depth 5
```

### 5. Demo Requests

#### Full Procurement Flow (Invoice → PO → Payment → Summary)

```powershell
$body = @{
    jsonrpc = "2.0"
    id = "1"
    method = "message/send"
    params = @{
        message = @{
            role = "user"
            messageId = "msg-demo-001"
            parts = @(@{
                kind = "text"
                text = '{"type":"full_flow","invoice_data":{"invoice_number":"INV-2026-001","vendor":"Acme Corp","vendor_id":"V001","amount":5000,"date":"2026-02-19","line_items":[{"description":"Consulting Services","amount":3000},{"description":"Software Licenses","amount":2000}]},"requester":"demo-user"}'
            })
        }
    }
} | ConvertTo-Json -Depth 10

$resp = Invoke-RestMethod -Uri "http://localhost:8000/" -Method POST `
    -ContentType "application/json" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
$resp | ConvertTo-Json -Depth 10
```

**What happens behind the scenes:**
1. Orchestrator analyzes the request → routes to `full_flow` workflow
2. Orchestrator calls **Invoice Agent** via A2A → validates format, amounts, LLM compliance check
3. Invoice approved → Orchestrator calls **PO Agent** via A2A → budget check, vendor lookup, PO created
4. Payment is scheduled for the PO
5. **GPT-4.1** generates a professional summary of the entire workflow
6. Full result returned as a JSON-RPC task with status history

#### Invoice-Only Validation

```powershell
$body = @{
    jsonrpc = "2.0"
    id = "2"
    method = "message/send"
    params = @{
        message = @{
            role = "user"
            messageId = "msg-demo-002"
            parts = @(@{
                kind = "text"
                text = '{"type":"invoice_only","invoice_data":{"invoice_number":"INV-2026-005","vendor":"Contoso Ltd","vendor_id":"V002","amount":7500,"date":"2026-02-20","line_items":[{"description":"Cloud Services","amount":5000},{"description":"Premium Support","amount":2500}]},"requester":"demo-user"}'
            })
        }
    }
} | ConvertTo-Json -Depth 10

$resp = Invoke-RestMethod -Uri "http://localhost:8000/" -Method POST `
    -ContentType "application/json" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
$resp | ConvertTo-Json -Depth 10
```

#### Direct Agent Call (Invoice Agent)

```powershell
$body = @{
    jsonrpc = "2.0"
    id = "3"
    method = "message/send"
    params = @{
        message = @{
            role = "user"
            messageId = "msg-demo-003"
            parts = @(@{
                kind = "text"
                text = '{"invoice_number":"INV-2026-010","vendor":"Test Vendor","amount":1000,"date":"2026-02-19","line_items":[{"description":"Office Supplies","amount":1000}]}'
            })
        }
    }
} | ConvertTo-Json -Depth 10

$resp = Invoke-RestMethod -Uri "http://localhost:8001/" -Method POST `
    -ContentType "application/json" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
$resp | ConvertTo-Json -Depth 10
```

---

## Part 2: AKS Deployment with KEDA Scaling

This is the main customer demo — showing A2A agents scaling from **0 to N pods** driven by Azure Service Bus queue depth.

### Prerequisites

- Azure CLI (`az login`)
- `kubectl`
- `helm`
- Azure subscription with permissions to create AKS, ACR, Service Bus, and Managed Identity

### Step 1 — Provision Azure Infrastructure

The setup script creates everything in one command:

```bash
./scripts/setup-azure.sh
```

This provisions:

| Resource | Purpose |
|----------|---------|
| **Resource Group** (`rg-a2a-keda-demo`) | Container for all resources |
| **AKS Cluster** | Kubernetes with OIDC issuer + workload identity enabled |
| **Azure Container Registry** | Private registry for agent images |
| **Azure Service Bus Namespace** | Message broker for agent communication |
| **4 Queues** | `invoice-requests`, `invoice-responses`, `po-requests`, `po-responses` |
| **KEDA** (via Helm) | Event-driven pod autoscaler |
| **Managed Identity** | Passwordless auth for Service Bus + OpenAI, federated to AKS |

### Step 2 — Update Configuration

After the setup script runs, update `k8s/configmap.yaml` with your actual Service Bus namespace:

```yaml
SERVICEBUS_FQDN: "sb-a2a-demo.servicebus.windows.net"
USE_SERVICEBUS: "true"
```

Update `k8s/secrets.yaml` with your Azure OpenAI credentials.

Update `k8s/keda/invoice-scaledobject.yaml` and `k8s/keda/po-scaledobject.yaml` — replace `${SERVICEBUS_NAMESPACE}` with your Service Bus namespace name (e.g. `sb-a2a-demo`).

### Step 3 — Build and Push Container Images

```bash
ACR_NAME=acra2ademo

az acr build --registry $ACR_NAME --image a2a-orchestrator:latest -f docker/Dockerfile.orchestrator .
az acr build --registry $ACR_NAME --image a2a-invoice-agent:latest -f docker/Dockerfile.invoice .
az acr build --registry $ACR_NAME --image a2a-po-agent:latest -f docker/Dockerfile.po .
```

### Step 4 — Deploy to AKS

```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Deploy core resources (agents, services, config, secrets, redis)
kubectl apply -f k8s/

# Deploy KEDA ScaledObjects
kubectl apply -f k8s/keda/
```

### Step 5 — Verify Deployment

```powershell
# Check all resources are running
kubectl get all -n a2a-agents

# Verify KEDA ScaledObjects are active
kubectl get scaledobjects -n a2a-agents

# Expected output:
# NAME                    SCALETARGETNAME   MIN   MAX   TRIGGERS            READY
# invoice-agent-scaler    invoice-agent     0     10    azure-servicebus    True
# po-agent-scaler         po-agent          0     5     azure-servicebus    True

# Initially, agent pods should be at 0 (scale-to-zero)
kubectl get pods -n a2a-agents
# Expected: only orchestrator and redis running; no invoice-agent or po-agent pods
```

---

## Part 3: KEDA Scaling Demo (The Money Shot 🎬)

This is the demo you show the customer. It demonstrates pods scaling from **0 to N in real-time** based on Azure Service Bus queue depth.

### Setup: Open Three Terminals

**Terminal 1 — Watch pods (leave this visible):**
```powershell
kubectl get pods -n a2a-agents -w
```

**Terminal 2 — Watch KEDA ScaledObjects:**
```powershell
kubectl get scaledobjects -n a2a-agents -w
```

**Terminal 3 — Run the load test:**
```powershell
# Set your Service Bus FQDN
$env:SERVICEBUS_FQDN = "sb-a2a-demo.servicebus.windows.net"

# Flood invoice-requests queue with 50 messages
python scripts/demo-load.py --count 50 --queue invoice-requests
```

### What the Customer Sees

```
Timeline:

  T+0s    kubectl shows: 0 invoice-agent pods (scale-to-zero ✨)
          Queue is empty, no work = no compute cost

  T+5s    Load test starts sending invoices to Service Bus queue
          ══════════════════════════════════════════════════
            KEDA Scaling Demo — Load Test
          ══════════════════════════════════════════════════
            Target queue : invoice-requests
            Messages     : 50
          ══════════════════════════════════════════════════
          [   1/50] Sent INV-20260223-0001 (0.1s elapsed)
          [   2/50] Sent INV-20260223-0002 (0.2s elapsed)
          ...

  T+15s   KEDA detects queue depth > 5 messages
          → Scales invoice-agent from 0 → 1 pod
          kubectl output:
            invoice-agent-7d8f9c-abc12   0/1   ContainerCreating   0   0s

  T+30s   Queue continues growing, KEDA scales further
          → invoice-agent: 1 → 3 pods
          kubectl output:
            invoice-agent-7d8f9c-abc12   1/1   Running   0   15s
            invoice-agent-7d8f9c-def34   0/1   ContainerCreating   0   0s
            invoice-agent-7d8f9c-ghi56   0/1   ContainerCreating   0   0s

  T+60s   All 50 messages sent. Agents are processing concurrently.
          → invoice-agent: scaled to 5-10 pods depending on processing speed

  T+90s   Queue is draining as agents complete work.
          Messages processed → results published to invoice-responses queue

  T+5min  Queue is empty. KEDA cooldown period begins.

  T+10min KEDA scales invoice-agent back to 0 pods.
          → Zero compute cost when idle ✨
```

### Also Try: PO Agent Scaling

```powershell
# Flood po-requests queue
python scripts/demo-load.py --count 20 --queue po-requests
```

### Also Try: Both Queues Simultaneously

```powershell
# Terminal A
python scripts/demo-load.py --count 50 --queue invoice-requests

# Terminal B (at the same time)
python scripts/demo-load.py --count 20 --queue po-requests
```

This shows both agent types scaling independently — invoice-agent scales up to handle invoices while po-agent scales up to handle purchase orders.

---

## Part 4: What to Show the Customer

### Demo Talking Points

| Demo Point | What to Highlight |
|------------|-------------------|
| **Scale-to-Zero** | Agent pods start at 0 replicas — no compute cost when idle |
| **Event-Driven Scaling** | KEDA monitors Service Bus queue depth and scales pods automatically |
| **Independent Scaling** | Invoice agent and PO agent scale independently based on their own workloads |
| **A2A Protocol** | Standard JSON-RPC 2.0 — any A2A-compliant agent can participate in the system |
| **Agent Discovery** | Each agent self-describes via `/.well-known/agent-card.json` |
| **Multi-Agent Orchestration** | Orchestrator coordinates agents via conditional LangGraph workflows |
| **LLM Integration** | Azure OpenAI GPT-4.1 for compliance analysis and summary generation |
| **Passwordless Auth** | `DefaultAzureCredential` + Workload Identity — no secrets in code or config |
| **Dual Transport** | Same agents work over HTTP (dev) or Service Bus (prod) with one env var toggle |
| **Resilient Messaging** | Service Bus provides durable, at-least-once delivery — messages survive pod restarts |
| **Fast Recovery** | Dead-lettering on processing errors; no message loss |

### Key Customer Questions & Answers

**Q: How fast does scaling happen?**
A: KEDA polls every 15 seconds. Pods typically start within 15-30s of queue depth exceeding the threshold.

**Q: What if a pod crashes mid-processing?**
A: The message remains in the Service Bus queue (it's not completed until processing succeeds). Another pod picks it up.

**Q: Can we use this with different agent frameworks?**
A: Yes — the A2A protocol is framework-agnostic. The Service Bus transport layer works with any agent that can produce/consume JSON.

**Q: What about cost when there's no traffic?**
A: KEDA scales to zero. You only pay for the orchestrator pod + Service Bus (minimal) when idle.

**Q: How do we add a new agent type?**
A: Create the agent, add a new queue pair (`<name>-requests` / `<name>-responses`), add a KEDA ScaledObject, and update the orchestrator to route to it.

---

## Architecture Details

### Service Bus Transport (`agents/common/servicebus.py`)

The shared transport helper provides three key methods:

| Method | Purpose |
|--------|---------|
| `send_message(queue, payload, correlation_id)` | Send a JSON message to a queue with a correlation ID |
| `receive_response(queue, correlation_id, timeout)` | Wait for a response message matching a correlation ID |
| `consume_queue(queue, handler, response_queue)` | Continuously consume and process messages (used by agents) |

All communication uses `DefaultAzureCredential` for passwordless authentication.

### How the Toggle Works

The `USE_SERVICEBUS` environment variable controls the transport mode:

```
USE_SERVICEBUS=false (default)
  Orchestrator → HTTP/A2A → Invoice Agent
  Orchestrator → HTTP/A2A → PO Agent

USE_SERVICEBUS=true
  Orchestrator → Service Bus (invoice-requests) → Invoice Agent
  Invoice Agent → Service Bus (invoice-responses) → Orchestrator
  (same pattern for PO Agent)
```

When `USE_SERVICEBUS=true`:
- The **orchestrator** sends to request queues and awaits correlated responses
- Each **agent server** starts a background consumer loop alongside its HTTP server
- Messages are correlated using a UUID — the response carries the same `correlation_id`

### KEDA ScaledObject Configuration

```yaml
# invoice-agent: scale 0→10 when queue has > 5 messages
spec:
  scaleTargetRef:
    name: invoice-agent
  minReplicaCount: 0
  maxReplicaCount: 10
  cooldownPeriod: 300        # 5 min before scaling down
  pollingInterval: 15        # check every 15s
  triggers:
  - type: azure-servicebus
    metadata:
      queueName: invoice-requests
      messageCount: "5"      # threshold to trigger scale-up
```

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Auth | `DefaultAzureCredential` | Consistent with existing OpenAI auth; works with Managed Identity |
| Correlation | UUID per request | Match response to the correct sender in async flow |
| Toggle | `USE_SERVICEBUS` env var | Keep HTTP/A2A as default for local dev, Service Bus for production |
| Queues | 4 (request + response per agent) | Clean separation, independent scaling per agent |
| Message format | Same JSON as HTTP payloads | No code changes needed in agent business logic |
| Fallback | HTTP if Service Bus unavailable | Graceful degradation for local development |
| Dead-lettering | On processing errors | Prevents poison messages from blocking the queue |

---

## Files Changed (from HTTP-only baseline)

| File | Change |
|------|--------|
| `agents/common/servicebus.py` | **New** — shared async Service Bus transport (send/receive/consume) |
| `agents/common/__init__.py` | **New** — package init |
| `agents/orchestrator/agent.py` | **Modified** — added `USE_SERVICEBUS` toggle and `_send_via_servicebus()` method |
| `agents/invoice_agent/server.py` | **Modified** — added background Service Bus consumer loop |
| `agents/po_agent/server.py` | **Modified** — added background Service Bus consumer loop |
| `k8s/configmap.yaml` | **Modified** — added `USE_SERVICEBUS` and `SERVICEBUS_FQDN` |
| `k8s/invoice-agent.yaml` | **Modified** — added Service Bus env vars to pod spec |
| `k8s/po-agent.yaml` | **Modified** — added Service Bus env vars to pod spec |
| `k8s/orchestrator.yaml` | **New** — Orchestrator Deployment + LoadBalancer Service |
| `k8s/keda/trigger-auth.yaml` | **New** — KEDA TriggerAuthentication (Azure Workload Identity) |
| `k8s/keda/invoice-scaledobject.yaml` | **New** — Scale invoice-agent 0→10 on queue depth |
| `k8s/keda/po-scaledobject.yaml` | **New** — Scale po-agent 0→5 on queue depth |
| `scripts/setup-azure.sh` | **New** — One-command Azure provisioning |
| `scripts/demo-load.py` | **New** — Load test to flood queues and trigger scaling |
| `.env.example` | **Modified** — added `USE_SERVICEBUS` and `SERVICEBUS_FQDN` |

---

## Azure Resources Required

| Resource | Purpose | Cost Impact |
|----------|---------|-------------|
| Azure Kubernetes Service | Container orchestration | Node pool (3 nodes) |
| Azure Container Registry (Basic) | Private image registry | ~$5/month |
| Azure Service Bus (Standard) | Message broker for agent queues | ~$10/month + per-message |
| KEDA (Helm on AKS) | Event-driven pod autoscaler | Free (OSS) |
| Managed Identity | Passwordless auth for Service Bus + OpenAI | Free |
| Azure OpenAI | LLM for compliance checks and summaries | Per-token |
