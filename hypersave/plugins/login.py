import asyncio
import traceback

from convopyro import listen_message
from pyrogram import Client, filters
from pyrogram.errors import (
    ApiIdInvalid,
    FloodWait,
    PasswordHashInvalid,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberInvalid,
    SessionPasswordNeeded,
)
from pyrogram.types import Message

from hypersave.bot import ClientBot
from hypersave.logger import logger
from hypersave.settings import Settings

settings = Settings()


@ClientBot.on_message(filters.command("login") & filters.private)
async def generate_session(client: Client, message: Message):
    user_id = message.chat.id

    try:
        await message.reply(
            "📲 Envie seu número de telefone no formato internacional.\nExemplo: +5511999887654"
        )
        number_response = await wait_for_response(
            client,
            message,
            timeout=180,
            error_message="❌ Tempo limite excedido para o envio do número de telefone. Reinicie o processo de login."
        )

        phone_number = number_response.text.strip().replace(" ", "")

        client_user = Client(f"session_{user_id}", settings.api_id, settings.api_hash)
        await client_user.connect()
        
        try:
            code_info = await client_user.send_code(phone_number)
            await message.reply("📲 Enviando código de verificação...")
        except ApiIdInvalid:
            await message.reply("❌ API ID ou API HASH inválidos. Reinicie a sessão.")
            return
        except PhoneNumberInvalid:
            await message.reply("❌ Número de telefone inválido. Reinicie a sessão.")
            return

        phone_code_hash = code_info.phone_code_hash

        await message.reply(
            "📩 Verifique seu Telegram e insira o código recebido. \n\n**INSIRA NESTE MODELO A SEGUIR**: \nEx: Seu codigo é **12345** então vc deve enviar: **AB1 CD2 EF3 GH4 IJ5**\n\nEx 2: Seu codigo é **36139** então vc deve enviar: **AB3 CD6 EF1 GH3 IJ9**"
        )
        otp_response = await wait_for_response(
            client,
            message,
            timeout=180,
            error_message="❌ Tempo limite excedido para o envio do código de verificação. Reinicie o processo de login."
        )

        phone_code = otp_response.text.strip()

        try:
            await client_user.sign_in(
                phone_number=phone_number,
                phone_code_hash=phone_code_hash,
                phone_code=phone_code,
            )
        except PhoneCodeInvalid:
            await message.reply("❌ Código inválido. Reinicie a sessão.")
            return
        except PhoneCodeExpired:
            await message.reply("❌ Código expirado. Reinicie a sessão.")
            return
        except SessionPasswordNeeded:
            await message.reply(
                "🔒 Sua conta tem verificação em duas etapas. Insira sua senha."
            )

            password_response = await wait_for_response(
                client,
                message,
                timeout=180,
                error_message="❌ Tempo limite excedido para o envio da senha de verificação de duas etapas. Reinicie o processo de login."
            )

            try:
                await client_user.check_password(
                    password=password_response.text.strip()
                )
            except PasswordHashInvalid:
                await message.reply("❌ Senha incorreta. Reinicie a sessão.")
                return

        string_session = await client_user.export_session_string()
        logger.info(f"Sessão gerada para {phone_number}: {string_session}")

        await client_user.terminate()
        await message.reply("✅ Login bem-sucedido!")
    except asyncio.TimeoutError:
        return # Error message already sent
    except Exception as e:
        await message.reply(
            f"❌ Erro inesperado, tente novamente mais tarde, ou entre em contato com o criador do bot."
        )
        logger.error(f"Erro ao gerar sessão: {e}")
        traceback.print_exc()


async def wait_for_response(client, message, timeout, error_message):
    try:
        response = await listen_message(client, message.from_user.id, timeout=timeout)
        if response is None:
            await message.reply(error_message)
            raise asyncio.TimeoutError
        return response
    except asyncio.TimeoutError:
        raise