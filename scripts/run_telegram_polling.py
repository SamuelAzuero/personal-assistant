#!/usr/bin/env python3
"""
Telegram Long-Polling Runner for Local & Server Interactive Assistant.
Allows chatting with @Minekeinf_bot directly without requiring a public HTTPS webhook URL.
"""

import logging
import os
import signal
import sys
import time
from typing import Any, Dict

import httpx

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings
from app.core.intent_parser import IntentParser
from app.core.session_manager import SessionManager
from app.api.webhook import create_default_tool_router
from app.integrations.telegram_client import TelegramClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("telegram_polling")

running = True


def handle_signal(sig, frame):
    global running
    logger.info("Interrupción recibida (SIGINT/SIGTERM). Deteniendo bot...")
    running = False


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def main():
    global running
    settings = get_settings()
    bot_token = settings.telegram_bot_token

    if not bot_token:
        logger.error("No se encontró TELEGRAM_BOT_TOKEN en .env")
        sys.exit(1)

    logger.info("Iniciando Asistente Personal Autónomo en modo Long-Polling...")
    logger.info("Usuario: %s | Monedas: %s (%s)", settings.user_name, settings.currency_code, settings.currency_symbol)
    logger.info("Correos configurados: %s, %s", settings.gmail_user_email, settings.secondary_gmail_user_email)

    # Initialize Core Engine
    telegram_client = TelegramClient(bot_token=bot_token, mock_mode=False)
    intent_parser = IntentParser()
    session_manager = SessionManager()
    tool_router = create_default_tool_router()

    base_url = f"https://api.telegram.org/bot{bot_token}"

    # 1. Verificar identidad del bot y eliminar cualquier webhook previo
    try:
        with httpx.Client(timeout=10.0) as client:
            me_resp = client.get(f"{base_url}/getMe")
            if me_resp.status_code == 200 and me_resp.json().get("ok"):
                bot_info = me_resp.json()["result"]
                logger.info("Conectado con éxito a Telegram Bot: @%s (%s)", bot_info.get("username"), bot_info.get("first_name"))
            else:
                logger.error("Token de Telegram inválido o error de conexión: %s", me_resp.text)
                sys.exit(1)

            # Eliminar webhook para permitir getUpdates
            del_resp = client.post(f"{base_url}/deleteWebhook", json={"drop_pending_updates": False})
            logger.info("Estado de deleteWebhook: %s", del_resp.json().get("description", "OK"))
    except Exception as e:
        logger.error("Error al conectar con la API de Telegram: %s", e)
        sys.exit(1)

    print("\n" + "=" * 65)
    print("🤖 BOT ACTIVO: @Minekeinf_bot")
    print("💬 Abre Telegram en tu teléfono y envía /start o cualquier mensaje")
    print("=" * 65 + "\n")

    offset = 0
    poll_client = httpx.Client(timeout=35.0)

    welcome_msg = (
        f"👋 ¡Hola {settings.user_name}! Soy tu **Asistente Personal Autónomo**.\n\n"
        "Estoy conectado y listo para ayudarte con:\n"
        "• 💰 **Finanzas (COP)**: *'gasté 50 mil en almuerzo'*, *'¿cuál es mi saldo?'*\n"
        "• 📋 **Tareas**: *'recuérdame entregar proyecto mañana a las 3pm'*\n"
        "• 📅 **Agenda**: *'agendar reunión con profesor mañana a las 10am'*\n"
        "• 📬 **Correos**: *'¿qué correos importantes me llegaron?'*\n"
        "• 🎉 **Planes**: *'recomiéndame planes para salir este fin de semana en Bogotá'*\n\n"
        f"📧 Monitoreando tus cuentas: `{settings.gmail_user_email}` y `{settings.secondary_gmail_user_email}`"
    )

    quick_kb = telegram_client.build_default_quick_keyboard()

    while running:
        try:
            resp = poll_client.get(
                f"{base_url}/getUpdates",
                params={"offset": offset, "timeout": 25, "allowed_updates": ["message"]},
            )
            if resp.status_code != 200:
                logger.warning("Respuesta no OK de getUpdates: %s %s", resp.status_code, resp.text)
                time.sleep(2)
                continue

            data = resp.json()
            if not data.get("ok"):
                logger.warning("Error en getUpdates: %s", data)
                time.sleep(2)
                continue

            updates = data.get("result", [])
            for upd in updates:
                offset = max(offset, upd["update_id"] + 1)
                msg = upd.get("message")
                if not msg:
                    continue

                chat_id = str(msg.get("chat", {}).get("id", ""))
                user_id = str(msg.get("from", {}).get("id") or chat_id)
                user_text = (msg.get("text") or "").strip()

                if not chat_id:
                    continue

                # Soporte para notas de voz y mensajes de audio
                voice_data = msg.get("voice") or msg.get("audio")
                if voice_data and not user_text:
                    file_id = voice_data.get("file_id")
                    mime_type = voice_data.get("mime_type", "audio/ogg")
                    logger.info("Nota de voz recibida de [%s], file_id: %s", user_id, file_id)
                    try:
                        # 1. Obtener ruta del archivo desde Telegram
                        f_resp = poll_client.get(f"{base_url}/getFile", params={"file_id": file_id})
                        if f_resp.status_code == 200 and f_resp.json().get("ok"):
                            file_path = f_resp.json()["result"]["file_path"]
                            # 2. Descargar el archivo de audio
                            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
                            audio_resp = poll_client.get(download_url)
                            if audio_resp.status_code == 200:
                                audio_bytes = audio_resp.content
                                # 3. Transcribir con Gemini
                                gemini_svc = tool_router.effective_gemini_service
                                if gemini_svc and gemini_svc.is_available():
                                    transcription = gemini_svc.transcribe_audio(audio_bytes, mime_type=mime_type)
                                    if transcription:
                                        user_text = transcription.strip()
                                        logger.info("Nota de voz transcrita con éxito de [%s]: '%s'", user_id, user_text)
                                        telegram_client.send_message(chat_id, f"🎙️ *Escuché:* \"{user_text}\"")
                    except Exception as ve:
                        logger.error("Error al procesar nota de voz de [%s]: %s", user_id, ve)

                if not user_text:
                    continue

                logger.info("Mensaje procesando para [%s]: %s", user_id, user_text[:60])

                # Comandos de bienvenida / ayuda
                if user_text.lower() in ("/start", "/help", "inicio", "ayuda"):
                    telegram_client.send_message(chat_id, welcome_msg, reply_markup=quick_kb)
                    continue

                # Procesamiento conversacional del mensaje
                if user_text:
                    try:
                        session = session_manager.get_session(user_id)
                        session_manager.add_message(user_id, "user", user_text)

                        intent_res = intent_parser.parse(
                            user_text,
                            session_context=session.to_context_dict(),
                        )

                        clarification = session_manager.update_with_intent(user_id, intent_res)
                        if clarification:
                            response_text = clarification
                        else:
                            response_text = tool_router.dispatch(user_id, intent_res)

                        session_manager.add_message(user_id, "assistant", response_text)
                        telegram_client.send_message(chat_id, response_text, reply_markup=quick_kb)
                    except Exception as err:
                        logger.error("Error procesando mensaje de [%s]: %s", user_id, err, exc_info=True)
                        telegram_client.send_message(
                            chat_id,
                            f"⚠️ Ocurrió un error al procesar tu solicitud: {err}",
                            reply_markup=quick_kb,
                        )

        except httpx.ReadTimeout:
            # Normal en long-polling cuando no hay nuevos mensajes en la ventana de tiempo
            continue
        except Exception as e:
            logger.error("Error durante el sondeo de Telegram: %s", e)
            time.sleep(3)

    poll_client.close()
    logger.info("Servicio de Telegram finalizado correctamente.")


if __name__ == "__main__":
    main()
