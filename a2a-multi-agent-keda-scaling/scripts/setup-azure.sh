#!/bin/bash
# Setup Azure resources for the A2A Multi-Agent KEDA Scaling Demo
# Prerequisites: az login, az account set -s <subscription>
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-a2a-keda-demo}"
LOCATION="${LOCATION:-eastus2}"
AKS_NAME="${AKS_NAME:-aks-a2a-demo}"
ACR_NAME="${ACR_NAME:-acra2ademo}"
SERVICEBUS_NS="${SERVICEBUS_NS:-sb-a2a-demo}"
QUEUES=("invoice-requests" "invoice-responses" "po-requests" "po-responses")

echo "═══════════════════════════════════════════════════════"
echo "  A2A Multi-Agent KEDA Demo — Azure Setup"
echo "═══════════════════════════════════════════════════════"
echo "  Resource Group : $RESOURCE_GROUP"
echo "  Location       : $LOCATION"
echo "  AKS Cluster    : $AKS_NAME"
echo "  ACR            : $ACR_NAME"
echo "  Service Bus NS : $SERVICEBUS_NS"
echo "═══════════════════════════════════════════════════════"

# ── 1. Resource Group ─────────────────────────────────────────
echo -e "\n[1/7] Creating resource group..."
az group create --name $RESOURCE_GROUP --location $LOCATION -o none

# ── 2. Azure Container Registry ──────────────────────────────
echo "[2/7] Creating Azure Container Registry..."
az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic -o none

# ── 3. AKS Cluster with OIDC + Workload Identity ─────────────
echo "[3/7] Creating AKS cluster (with OIDC issuer & workload identity)..."
az aks create \
  --resource-group $RESOURCE_GROUP \
  --name $AKS_NAME \
  --node-count 3 \
  --enable-oidc-issuer \
  --enable-workload-identity \
  --attach-acr $ACR_NAME \
  --generate-ssh-keys \
  -o none

# Get credentials
az aks get-credentials --resource-group $RESOURCE_GROUP --name $AKS_NAME --overwrite-existing

# ── 4. Install KEDA on AKS ───────────────────────────────────
echo "[4/7] Installing KEDA via Helm..."
helm repo add kedacore https://kedacore.github.io/charts 2>/dev/null || true
helm repo update
helm upgrade --install keda kedacore/keda --namespace keda --create-namespace --wait

# ── 5. Azure Service Bus Namespace + Queues ───────────────────
echo "[5/7] Creating Service Bus namespace and queues..."
az servicebus namespace create \
  --resource-group $RESOURCE_GROUP \
  --name $SERVICEBUS_NS \
  --sku Standard \
  --location $LOCATION \
  -o none

for QUEUE in "${QUEUES[@]}"; do
  echo "  Creating queue: $QUEUE"
  az servicebus queue create \
    --resource-group $RESOURCE_GROUP \
    --namespace-name $SERVICEBUS_NS \
    --name $QUEUE \
    -o none
done

# ── 6. Managed Identity + Federated Credential ───────────────
echo "[6/7] Setting up Managed Identity for workload identity..."
IDENTITY_NAME="id-a2a-agents"
az identity create --resource-group $RESOURCE_GROUP --name $IDENTITY_NAME -o none

IDENTITY_CLIENT_ID=$(az identity show --resource-group $RESOURCE_GROUP --name $IDENTITY_NAME --query clientId -o tsv)
IDENTITY_OBJECT_ID=$(az identity show --resource-group $RESOURCE_GROUP --name $IDENTITY_NAME --query principalId -o tsv)
AKS_OIDC_ISSUER=$(az aks show --resource-group $RESOURCE_GROUP --name $AKS_NAME --query oidcIssuerProfile.issuerUrl -o tsv)
SB_RESOURCE_ID=$(az servicebus namespace show --resource-group $RESOURCE_GROUP --name $SERVICEBUS_NS --query id -o tsv)

# Grant Service Bus Data Owner role to the managed identity
az role assignment create \
  --role "Azure Service Bus Data Owner" \
  --assignee-object-id $IDENTITY_OBJECT_ID \
  --assignee-principal-type ServicePrincipal \
  --scope $SB_RESOURCE_ID \
  -o none

# Create federated credential for the a2a-agents namespace default SA
az identity federated-credential create \
  --name "fed-a2a-agents" \
  --identity-name $IDENTITY_NAME \
  --resource-group $RESOURCE_GROUP \
  --issuer $AKS_OIDC_ISSUER \
  --subject "system:serviceaccount:a2a-agents:default" \
  --audiences "api://AzureADTokenExchange" \
  -o none

# ── 7. Print summary ─────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ Setup Complete!"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "  Service Bus FQDN : ${SERVICEBUS_NS}.servicebus.windows.net"
echo "  Identity Client ID: $IDENTITY_CLIENT_ID"
echo ""
echo "  Next steps:"
echo "  1. Update k8s/configmap.yaml:"
echo "     SERVICEBUS_FQDN: \"${SERVICEBUS_NS}.servicebus.windows.net\""
echo ""
echo "  2. Annotate the service account in k8s/namespace.yaml:"
echo "     azure.workload.identity/client-id: \"$IDENTITY_CLIENT_ID\""
echo ""
echo "  3. Build and push images:"
echo "     az acr build --registry $ACR_NAME --image a2a-invoice-agent:latest -f docker/Dockerfile.invoice ."
echo "     az acr build --registry $ACR_NAME --image a2a-po-agent:latest -f docker/Dockerfile.po ."
echo "     az acr build --registry $ACR_NAME --image a2a-orchestrator:latest -f docker/Dockerfile.orchestrator ."
echo ""
echo "  4. Deploy to AKS:"
echo "     kubectl apply -f k8s/namespace.yaml"
echo "     kubectl apply -f k8s/"
echo "     kubectl apply -f k8s/keda/"
echo ""
echo "  5. Run the load test:"
echo "     python scripts/demo-load.py --count 50 --queue invoice-requests"
echo "     kubectl get pods -n a2a-agents -w"
echo ""
