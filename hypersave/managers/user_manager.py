import asyncio
from time import time
from typing import Dict, Optional

from pyrogram import Client
from pyrogram.errors import RPCError

from hypersave.database.user_repository import UserRepository
from hypersave.models.user_client import UserClient
from hypersave.settings import Settings


class UserManager:
    def __init__(self):
        self.settings = Settings()
        self.user_repository = UserRepository()

        # Cache for active user clients
        self.user_clients: Dict[str, UserClient] = {}

        # Client inactivity timeout (2 hours)
        self.client_timeout = 7200  # seconds

        # Background task for cleaning inactive clients
        self.cleanup_task = None
        self.running = False

    def start(self):
        """Start the user manager"""
        if not self.running:
            self.running = True
            self.cleanup_task = asyncio.create_task(self.cleanup_inactive_clients())

    async def stop(self):
        """Stop the user manager and disconnect all clients"""
        self.running = False

        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

        # Disconnect all active clients
        for user_id, client in self.user_clients.items():
            if client.is_connected:
                await client.stop()

        self.user_clients.clear()

    async def get_user_client(self, user_id: str) -> Optional[UserClient]:
        """
        Get an active client for a user

        Args:
            user_id: User ID

        Returns:
            UserClient object if successful, None otherwise
        """
        # Check if client already exists and is connected
        if user_id in self.user_clients and self.user_clients[user_id].is_connected:
            client = self.user_clients[user_id]
            client.last_used = time()
            return client

        # Not found or not connected, try to create a new one
        return await self.create_user_client(user_id)

    async def create_user_client(self, user_id: str) -> Optional[UserClient]:
        """
        Create a new user client

        Args:
            user_id: User ID

        Returns:
            UserClient object if successful, None otherwise
        """
        try:
            # Get session string from database
            session_string = self.user_repository.get_string_session(user_id)

            if not session_string:
                return None

            # Create new client
            client = UserClient(
                name=f"user_{user_id}",
                session_string=session_string,
                api_id=self.settings.api_id,
                api_hash=self.settings.api_hash,
                device_model=self.settings.bot_name,
                max_concurrent_transmissions=5,
                workdir="sessions",
            )

            # Start client
            await client.start()

            # Cache the client
            self.user_clients[user_id] = client

            return client

        except RPCError as e:
            print(f"Telegram API error creating client for user {user_id}: {e}")
            return None
        except Exception as e:
            print(f"Error creating client for user {user_id}: {e}")
            return None

    async def save_session_string(self, user_id: str, session_string: str) -> bool:
        """
        Save a user's session string to the database

        Args:
            user_id: User ID
            session_string: Pyrogram session string

        Returns:
            True if successful, False otherwise
        """
        return self.user_repository.add_string_session(user_id, session_string)

    async def cleanup_inactive_clients(self):
        """Periodically clean up inactive clients"""
        while self.running:
            try:
                current_time = time()
                to_remove = []

                # Find inactive clients
                for user_id, client in self.user_clients.items():
                    if current_time - client.last_used > self.client_timeout:
                        to_remove.append(user_id)

                # Stop and remove inactive clients
                for user_id in to_remove:
                    client = self.user_clients[user_id]
                    if client.is_connected:
                        await client.stop()
                    del self.user_clients[user_id]

                # Log cleanup if any clients were removed
                if to_remove:
                    print(f"Cleaned up {len(to_remove)} inactive user clients")

                # Sleep for a while before next check (10 minutes)
                await asyncio.sleep(600)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in client cleanup task: {e}")
                await asyncio.sleep(60)  # Short sleep on error

    def get_active_users_count(self) -> int:
        """Get count of active user clients"""
        return len(self.user_clients)

    def get_active_users(self) -> Dict[str, Dict]:
        """Get information about active users"""
        return {
            user_id: {
                "last_used": client.last_used,
                "idle_time": f"{int(time() - client.last_used)}s",
                "user_id": client.user_id,
            }
            for user_id, client in self.user_clients.items()
        }
