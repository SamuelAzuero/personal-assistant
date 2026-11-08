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

echo "✅ Proyecto ID:    ${PROJECT_ID}"
echo "✅ Región:         ${REGION}"
echo "✅ Servicio:       ${SERVICE_NAME}"

# Habilitar APIs necesarias si no están activas
echo ""
echo "--> Verificando APIs requeridas (Cloud Run, Cloud Build, Artifact Registry)..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project="${PROJECT_ID}"

# Generar variables de entorno de producción
echo "--> Generando configuración de variables de entorno de producción..."
python3 scripts/generate_env_yaml.py

IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"
echo ""
echo "--> Construyendo imagen Docker con Cloud Build: ${IMAGE_TAG}..."
gcloud builds submit --tag "${IMAGE_TAG}" .

# Desplegar a Cloud Run con parámetros estrictos de nivel gratuito
echo ""
echo "--> Desplegando en Cloud Run con configuración Scale-to-Zero (Costo $0)..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_TAG}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 2 \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 80 \
  --timeout 60s \
  --port 8080 \
  --execution-environment gen2 \
  --env-vars-file deploy/cloud_run_env.yaml

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}"   --platform managed   --region "${REGION}"   --format 'value(status.url)' 2>/dev/null || echo "https://${SERVICE_NAME}-${PROJECT_ID}.${REGION}.run.app")

echo ""
echo "=================================================================="
echo " 🎉 ¡Despliegue a Google Cloud Run Completado con Éxito!"
echo " 🌐 URL del Panel Web:   ${SERVICE_URL}/"
echo " 🩺 Verificación Salud:  ${SERVICE_URL}/health"
echo " 🤖 Webhook Telegram:    ${SERVICE_URL}/api/webhook/telegram"
echo "=================================================================="

# Configuración automática del Webhook en Telegram
echo ""
echo "--> Conectando Webhook de Telegram hacia la URL de Cloud Run..."
./.venv/bin/python scripts/setup_cloud_webhook.py --set "${SERVICE_URL}/api/webhook/telegram"

echo ""
echo "✅ ¡El bot ya está corriendo 24/7 en Google Cloud Run y escuchando en Telegram!"
