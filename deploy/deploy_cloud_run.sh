#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Google Cloud Run Automated Deployment Script (Scale-to-Zero Free Tier)
# ==============================================================================

export PATH="/home/samuel-azuero/google-cloud-sdk/bin:$PATH"

SERVICE_NAME="${SERVICE_NAME:-personal-assistant}"
REGION="${GCP_REGION:-us-central1}"
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo '')}"

echo "=================================================================="
echo " 🚀 Desplegando ${SERVICE_NAME} a Google Cloud Run (Nivel Gratuito)"
echo "=================================================================="

# Verificar autenticación
ACTIVE_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || echo "")
if [[ -z "${ACTIVE_ACCOUNT}" ]]; then
  echo "❌ Error: No hay ninguna cuenta de Google autenticada en gcloud."
  echo "Por favor ejecuta primero en tu terminal:"
  echo "   gcloud auth login"
  echo "e inicia sesión con tu cuenta de Google."
  exit 1
fi

echo "✅ Cuenta activa: ${ACTIVE_ACCOUNT}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "❌ Error: No tienes ningún proyecto de Google Cloud seleccionado."
  echo "Ejecuta:"
  echo "   gcloud projects list"
  echo "   gcloud config set project <TU_PROJECT_ID>"
  exit 1
fi

# 2. Auto-detectar número de proyecto y configurar bucket de almacenamiento persistente
echo "--> Obteniendo número de proyecto para ${PROJECT_ID}..."
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)" 2>/dev/null || echo "")
if [[ -z "${PROJECT_NUMBER}" ]]; then
  echo "❌ Error: No se pudo obtener el número de proyecto de ${PROJECT_ID}."
  exit 1
fi

BUCKET_NAME="${GCS_BUCKET_NAME:-personal-assistant-data-${PROJECT_NUMBER}}"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "✅ Proyecto ID:        ${PROJECT_ID}"
echo "✅ Número Proyecto:    ${PROJECT_NUMBER}"
echo "✅ Región:             ${REGION}"
echo "✅ Servicio:           ${SERVICE_NAME}"
echo "✅ Bucket Persistente: gs://${BUCKET_NAME}"
echo "✅ Cuenta de Servicio: ${COMPUTE_SA}"

# 3. Habilitar APIs necesarias si no están activas
echo ""
echo "--> Verificando APIs requeridas (Cloud Run, Cloud Build, Artifact Registry, Storage)..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  --project="${PROJECT_ID}"

# 4. Provisionamiento y verificación del Bucket de Almacenamiento Persistente
echo ""
echo "--> Verificando bucket de almacenamiento persistente gs://${BUCKET_NAME}..."
if gcloud storage buckets describe "gs://${BUCKET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "✅ Bucket gs://${BUCKET_NAME} ya existe."
else
  echo "--> Creando bucket gs://${BUCKET_NAME} en región ${REGION} con uniform-bucket-level-access..."
  gcloud storage buckets create "gs://${BUCKET_NAME}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --uniform-bucket-level-access
  echo "✅ Bucket gs://${BUCKET_NAME} creado exitosamente."
fi

# 5. Asignar rol roles/storage.objectAdmin a la cuenta de servicio de Cloud Run
echo "--> Asignando permisos roles/storage.objectAdmin a ${COMPUTE_SA} en gs://${BUCKET_NAME}..."
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/storage.objectAdmin" \
  --quiet >/dev/null
echo "✅ Permisos IAM configurados correctamente."

# 6. Generar variables de entorno de producción
echo ""
echo "--> Generando configuración de variables de entorno de producción..."
python3 scripts/generate_env_yaml.py

# 7. Construcción de imagen de contenedor con Cloud Build
IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"
echo ""
echo "--> Construyendo imagen Docker con Cloud Build: ${IMAGE_TAG}..."
gcloud builds submit --tag "${IMAGE_TAG}" .

# 8. Desplegar a Cloud Run con volumen persistente GCS FUSE y Scale-to-Zero
echo ""
echo "--> Desplegando en Cloud Run con volumen persistente GCS FUSE y Scale-to-Zero..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_TAG}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 80 \
  --timeout 60s \
  --port 8080 \
  --execution-environment gen2 \
  --env-vars-file deploy/cloud_run_env.yaml \
  --add-volume=name=data-volume,type=cloud-storage,bucket="${BUCKET_NAME}",mount-options="uid=1001;gid=1001;file-mode=0700;dir-mode=0700" \
  --add-volume-mount=volume=data-volume,mount-path=/app/data

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --platform managed \
  --region "${REGION}" \
  --format 'value(status.url)' 2>/dev/null || echo "https://${SERVICE_NAME}-${PROJECT_ID}.${REGION}.run.app")

echo ""
echo "=================================================================="
echo " 🎉 ¡Despliegue a Google Cloud Run Completado con Éxito!"
echo " 🌐 URL del Panel Web:   ${SERVICE_URL}/"
echo " 🩺 Verificación Salud:  ${SERVICE_URL}/health"
echo " 🤖 Webhook Telegram:    ${SERVICE_URL}/api/webhook/telegram"
echo " 💾 Almacenamiento:      gs://${BUCKET_NAME} -> /app/data"
echo "=================================================================="

# 9. Configuración automática del Webhook en Telegram
echo ""
echo "--> Conectando Webhook de Telegram hacia la URL de Cloud Run..."
if [[ -f "./.venv/bin/python" ]]; then
  ./.venv/bin/python scripts/setup_cloud_webhook.py --set "${SERVICE_URL}/api/webhook/telegram"
else
  python3 scripts/setup_cloud_webhook.py --set "${SERVICE_URL}/api/webhook/telegram"
fi

echo ""
echo "✅ ¡El bot ya está corriendo 24/7 en Google Cloud Run y escuchando en Telegram con almacenamiento persistente!"
