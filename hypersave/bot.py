import asyncio
import traceback

import uvloop
from convopyro import Conversation
from pyrogram import Client, idle

from hypersave.database.database import Database
from hypersave.logger import logger
from hypersave.settings import Settings
from hypersave.utils.clear_folders import clear_and_create_folders
from hypersave.utils.directory_helper import ensure_directories_exist

uvloop.install()


class ClientBot(Client):

    def __init__(self):
        settings = Settings()
        super().__init__(
            name=settings.bot_name,
            api_id=settings.api_id,
            api_hash=settings.api_hash,
            bot_token=settings.bot_token,
            plugins=dict(root="hypersave/plugins/"),
            workdir="./sessions/",
            max_concurrent_transmissions=10,
        )


async def main():
    db = Database()
    db.create_tables()
    client = ClientBot()
    Conversation(client)
    await client.start()
    await idle()


if __name__ == "__main__":
    try:
        clear_and_create_folders()
        ensure_directories_exist()
        logger.success("Bot iniciado!")
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Erro ao iniciar o bot: {e}")
        traceback.print_exc()
        exit(1)
    except KeyboardInterrupt:
        logger.warning("Bot finalizado!")
        exit(0)
