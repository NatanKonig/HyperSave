from time import time

from pyrogram import Client


class UserClient(Client):
    """Extended Pyrogram Client with additional tracking information"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = None
        self.last_used = time()

    async def start(self):
        """Start client and set user_id"""
        await super().start()
        self.user_id = (await self.get_me()).id
        self.last_used = time()
        return self
