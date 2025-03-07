import asyncio
import os
from typing import Dict, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor

from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import FloodWaitError, RPCError

from hypersave.settings import Settings



class UserClient(Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = None

    async def start(self):
        await super().start()
        self.user_id = (await self.get_me()).id


class UserSessionManager:
    def __init__(self, max_concurrent_downloads: int = 5):
        self.settings = Settings()
        self.user_clients: List[UserClient] = List[UserClient]
        self.download_queues: Dict[str, asyncio.Queue] = {}
        self.download_semaphore = asyncio.Semaphore(max_concurrent_downloads)
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent_downloads)
    
    async def get_or_create_user_client(self, user_id: str, session_string: str) -> UserClient:
        for user in self.user_clients:
            if user.user_id == user_id:
                if user.is_connected:
                    return user
                else:
                    self.user_clients.remove(user)
                    break
        
        client = Client(
            name=f"user_{user_id}",
            session_string=session_string,
            api_id=self.settings.api_id,
            api_hash=self.settings.api_hash,
            device_model=self.settings.bot_name,
            max_concurrent_transmissions=5,
            workdir=f"./sessions/"
        )
        
        try:
            await client.start()
            self.user_clients.append(client)
            return client
        except Exception as e:
            print(f"Error creating user client for {user_id}: {e}")
            raise

    async def enqueue_download(
        self, 
        user_id: str, 
        download_task: callable,
        priority: int = 0
    ) -> asyncio.Future:
        """
        Enqueue a download task for a specific user
        
        Args:
            user_id (str): User identifier
            download_task (callable): Function to execute download
            priority (int): Download priority (lower = higher priority)
        
        Returns:
            asyncio.Future: Future representing the download task
        """
        # Create queue for user if not exists
        if user_id not in self.download_queues:
            self.download_queues[user_id] = asyncio.PriorityQueue()
        
        # Create a future to track the download
        future = asyncio.get_event_loop().create_future()
        
        # Enqueue the task
        await self.download_queues[user_id].put((priority, future, download_task))
        
        return future

    async def process_user_downloads(self, user_id: str):
        """
        Process download queue for a specific user
        
        Args:
            user_id (str): User identifier
        """
        queue = self.download_queues.get(user_id)
        if not queue:
            return
        
        while not queue.empty():
            try:
                # Get next download task
                _, future, download_task = await queue.get()
                
                async with self.download_semaphore:
                    try:
                        # Execute download task
                        result = await download_task()
                        future.set_result(result)
                    except Exception as e:
                        future.set_exception(e)
                    finally:
                        queue.task_done()
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error processing downloads for {user_id}: {e}")

    async def download_media(
        self, 
        user_id: str, 
        session_string: str,
        chat_id: int, 
        message_id: int
    ) -> str:
        """
        Download media for a specific user
        
        Args:
            user_id (str): User identifier
            session_string (str): User's session string
            chat_id (int): Source chat ID
            message_id (int): Source message ID
        
        Returns:
            str: Path to downloaded media
        """
        async def download_task():
            # Get or create user client
            user_client = await self.get_or_create_user_client(user_id, session_string)
            
            try:
                # Fetch message
                message = await user_client.get_messages(chat_id, message_id)
                
                # Validate media
                if not message.media:
                    raise ValueError("No media found in message")
                
                # Download media
                media_path = await message.download()
                return media_path
            
            except FloodWaitError as flood:
                # Handle Telegram flood wait
                await asyncio.sleep(flood.x)
                raise
            except RPCError as rpc_error:
                print(f"RPC Error during download: {rpc_error}")
                raise
        
        # Enqueue and wait for download
        future = await self.enqueue_download(user_id, download_task)
        return await future

class DownloadManager:
    def __init__(self):
        # Initialize user session manager
        self.user_session_manager = UserSessionManager()
    
    async def download_from_url(
        self, 
        user_id: str, 
        session_string: str,
        url: str
    ) -> str:
        """
        Download media from a Telegram URL
        
        Args:
            user_id (str): User identifier
            session_string (str): User's session string
            url (str): Telegram message URL
        
        Returns:
            str: Path to downloaded media
        """
        try:
            # Parse URL to get chat and message IDs
            chat_id, message_id = self.parse_telegram_url(url)
            
            # Download media
            media_path = await self.user_session_manager.download_media(
                user_id, 
                session_string, 
                chat_id, 
                message_id
            )
            
            return media_path
        
        except Exception as e:
            print(f"Download failed: {e}")
            raise
    
    def parse_telegram_url(self, url: str) -> Tuple[int, int]:
        """
        Parse Telegram URL to extract chat and message IDs
        
        Args:
            url (str): Telegram message URL
        
        Returns:
            Tuple[int, int]: Chat ID and Message ID
        """
        # Implement URL parsing logic similar to previous implementations
        # This is a placeholder - you'll need to adapt it to your specific URL format
        parts = url.split('/')
        if len(parts) < 5:
            raise ValueError("Invalid Telegram URL")
        
        # Handle different URL formats (public/private channels, groups)
        if parts[3] == 'c':
            # Private channel/group
            chat_id = int(f'-100{parts[4]}')
            message_id = int(parts[5])
        else:
            # Public channel/group
            chat_id = parts[3]
            message_id = int(parts[4])
        
        return chat_id, message_id

# Example usage
async def main():
    download_manager = DownloadManager()
    
    # Example download
    user_id = 'user123'
    session_string = 'your_session_string'
    url = 'https://t.me/channel/123'
    
    try:
        media_path = await download_manager.download_from_url(
            user_id, 
            session_string, 
            url
        )
        print(f"Media downloaded to: {media_path}")
    except Exception as e:
        print(f"Download failed: {e}")

if __name__ == '__main__':
    asyncio.run(main())