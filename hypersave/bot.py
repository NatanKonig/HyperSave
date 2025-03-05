import asyncio
import traceback

import uvloop
from convopyro import Conversation
from pyrogram import Client, idle

from hypersave.database.database import Database
from hypersave.logger import logger
from hypersave.settings import Settings

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
        logger.success("Bot iniciado!")
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Erro ao iniciar o bot: {e}")
        traceback.print_exc()
        exit(1)
    except KeyboardInterrupt:
        logger.warning("Bot finalizado!")
        exit(0)
