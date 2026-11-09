#!/usr/bin/env python3
"""CLI Utility to manage Telegram Webhook registration for Cloud deployments."""

import argparse
import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SECRET = os.getenv('TELEGRAM_SECRET_TOKEN') or os.getenv('TELEGRAM_WEBHOOK_SECRET', '')

if not SECRET:
    yaml_path = os.path.join(os.path.dirname(__file__), "..", "deploy", "cloud_run_env.yaml")
    if os.path.exists(yaml_path):
        try:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as f:
                y = yaml.safe_load(f) or {}
                SECRET = y.get("TELEGRAM_SECRET_TOKEN") or y.get("TELEGRAM_WEBHOOK_SECRET") or ""
        except Exception:
            pass

if not TOKEN:
    print('❌ Error: TELEGRAM_BOT_TOKEN is not configured in .env')
    sys.exit(1)

BASE_URL = f'https://api.telegram.org/bot{TOKEN}'


def get_webhook_info():
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f'{BASE_URL}/getWebhookInfo')
        if resp.status_code == 200:
            info = resp.json().get('result', {})
            print('📡 Estado actual del Webhook:')
            print(f'   URL: {info.get("url") or "Ninguno (Modo Polling activo)"}')
            print(f'   Pendientes de entrega: {info.get("pending_update_count", 0)}')
            if info.get('last_error_message'):
                print(f'   Último error: {info.get("last_error_message")}')
        else:
            print(f'❌ Error al consultar webhook: {resp.text}')


def set_webhook(url: str):
    payload = {
        'url': url,
        'drop_pending_updates': False,
    }
    if SECRET:
        payload['secret_token'] = SECRET

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(f'{BASE_URL}/setWebhook', json=payload)
        if resp.status_code == 200 and resp.json().get('ok'):
            print(f'✅ ¡Webhook configurado con éxito hacia {url}!')
            if SECRET:
                print('   🔐 Secret token de validación activado.')
        else:
            print(f'❌ Error al configurar webhook: {resp.text}')


def delete_webhook():
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(f'{BASE_URL}/deleteWebhook', json={'drop_pending_updates': False})
        if resp.status_code == 200 and resp.json().get('ok'):
            print('✅ Webhook eliminado con éxito. Ahora puedes usar scripts/run_telegram_polling.py localmente.')
        else:
            print(f'❌ Error al eliminar webhook: {resp.text}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Gestor de Webhook de Telegram para despliegue en la nube')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--status', action='store_true', help='Ver estado actual del webhook')
    group.add_argument('--set', metavar='URL', help='Establecer URL pública HTTPS del Webhook (ej. https://mi-app.run.app/webhook/telegram)')
    group.add_argument('--delete', action='store_true', help='Eliminar webhook para regresar a modo polling local')

    args = parser.parse_args()

    if args.status:
        get_webhook_info()
    elif args.set:
        set_webhook(args.set)
    elif args.delete:
        delete_webhook()
