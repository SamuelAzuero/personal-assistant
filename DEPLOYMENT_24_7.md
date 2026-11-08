# Guía de Despliegue 24/7 en la Nube (Costo bash / Free Tier)

Tu Asistente Personal Autónomo está listo para desplegarse y operar 24 horas al día, 7 días a la semana, respondiendo de inmediato a tus mensajes y notas de voz en Telegram [@Minekeinf_bot](https://t.me/Minekeinf_bot) y sirviendo tu panel web.

A continuación tienes las 3 mejores opciones gratuitas:

---

## 🚀 Opción 1: Google Cloud Run (Recomendada - Serverless Webhook)

Google Cloud Run ofrece **2 millones de peticiones gratuitas al mes** de forma permanente. El bot escala a cero cuando no hay actividad y se despierta en menos de 1 segundo al recibir un mensaje o audio.

### Pasos:
1. Instala y autentica Google Cloud SDK:
   ```bash
   gcloud auth login
   gcloud config set project TU_PROJECT_ID
   ```
2. Ejecuta el script automatizado:
   ```bash
   ./deploy/deploy_cloud_run.sh
   ```
3. Configura el Webhook en Telegram automáticamente con la URL obtenida:
   ```bash
   ./.venv/bin/python scripts/setup_cloud_webhook.py --set https://TU_URL_DE_CLOUDRUN.run.app/api/webhook/telegram
   ```
¡Listo! Telegram enviará cada mensaje directamente a Cloud Run.

---

## 🟣 Opción 2: Render.com (1-Click / GitHub)

Render ofrece 750 horas mensuales gratuitas (suficiente para correr 24/7 un servicio):

1. Sube este repositorio a tu GitHub (público o privado).
2. Entra a [render.com](https://render.com) y crea un **New Web Service** vinculado a tu repo.
3. Render detectará automáticamente el archivo `Dockerfile` o `Procfile`.
4. En **Environment Variables**, agrega las variables de tu archivo `.env`:
   - `TELEGRAM_BOT_TOKEN`
   - `GEMINI_API_KEY`
   - `GMAIL_USER_EMAIL`
   - `GMAIL_APP_PASSWORD`
   - `SECONDARY_GMAIL_USER_EMAIL`
   - `SECONDARY_GMAIL_APP_PASSWORD`
   - `MOCK_SERVICES=false`
   - `CURRENCY_CODE=COP`
5. Haz clic en **Create Web Service**.
6. Copia tu URL pública de Render (ej: `https://mi-asistente.onrender.com`) y activa el webhook:
   ```bash
   ./.venv/bin/python scripts/setup_cloud_webhook.py --set https://mi-asistente.onrender.com/api/webhook/telegram
   ```

---

## 🐳 Opción 3: Cualquier Servidor / VPS (Docker Compose 24/7)

Si tienes un VPS (Oracle Cloud Always Free, DigitalOcean, Linode, o una Raspberry Pi / servidor local):

1. Clona el proyecto y crea tu `.env` con tus claves.
2. Inicia el contenedor en segundo plano con reinicio automático permanente:
   ```bash
   docker compose up -d
   ```
3. Para ver los logs en vivo:
   ```bash
   docker compose logs -f
   ```
El contenedor se reiniciará automáticamente si el servidor se apaga o reinicia (`restart: always`).

---

## 🛠️ Comandos de Utilidad

### Ver el estado del Webhook:
```bash
./.venv/bin/python scripts/setup_cloud_webhook.py --status
```

### Regresar al modo Polling local:
```bash
./.venv/bin/python scripts/setup_cloud_webhook.py --delete
./.venv/bin/python scripts/run_telegram_polling.py
```
