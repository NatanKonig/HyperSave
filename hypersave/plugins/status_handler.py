from pyrogram import Client, filters
from pyrogram.types import Message

from hypersave.bot import ClientBot
from hypersave.plugins.custom_filters import CustomFilters
from hypersave.plugins.download_handler import (
    download_manager,
    upload_manager,
    user_manager,
)

custom_filters = CustomFilters()


@ClientBot.on_message(
    filters.command("status") & filters.private & custom_filters.is_admin
)
async def handle_status_request(bot: Client, message: Message):
    """Handle status command to show current download/upload status"""
    try:
        user_id = str(message.from_user.id)

        # Get queue status
        download_status = download_manager.get_queue_status()
        upload_status = upload_manager.get_queue_status()

        # Prepare status message
        status_text = "📊 **Status do Sistema**\n\n"

        # Download status
        status_text += "📥 **Downloads**\n"
        status_text += f"- Na fila: {download_status['queue_size']}\n"
        status_text += f"- Ativos: {download_status['active_downloads']}\n"
        status_text += f"- Concluídos: {download_status['completed_tasks']}\n\n"

        # Upload status
        status_text += "📤 **Uploads**\n"
        status_text += f"- Na fila: {upload_status['queue_size']}\n"
        status_text += f"- Ativos: {upload_status['active_uploads']}\n"
        status_text += f"- Concluídos: {upload_status['completed_tasks']}\n\n"

        # Active downloads details
        if download_status["active_tasks"]:
            status_text += "🔄 **Downloads Ativos**\n"
            for task in download_status["active_tasks"]:
                status_text += f"- ID: {task['task_id'][:10]}...\n"
                status_text += f"  Progresso: {task['progress']}\n"
                status_text += f"  Velocidade: {task['speed']}\n"
                status_text += f"  ETA: {task['eta']}\n\n"

        # Active uploads details
        if upload_status["active_tasks"]:
            status_text += "🔄 **Uploads Ativos**\n"
            for task in upload_status["active_tasks"]:
                status_text += f"- Arquivo: {task['file']}\n"
                status_text += f"  Progresso: {task['progress']}\n"
                status_text += f"  Velocidade: {task['speed']}\n"
                status_text += f"  ETA: {task['eta']}\n\n"

        # Send status message
        await message.reply(status_text)

    except Exception as e:
        await message.reply(f"Erro ao obter status: {str(e)}")


@ClientBot.on_message(
    filters.command("users") & filters.private & custom_filters.is_admin
)
async def handle_users_status(bot: Client, message: Message):
    """Handle users command to show active users (admin only)"""
    try:
        # Get active users
        active_users = user_manager.get_active_users()
        active_count = user_manager.get_active_users_count()

        # Prepare message
        users_text = f"👥 **Usuários Ativos: {active_count}**\n\n"

        # Add details for each user
        for user_id, info in active_users.items():
            users_text += f"- User ID: {user_id}\n"
            users_text += f"  Client ID: {info['user_id']}\n"
            users_text += f"  Tempo inativo: {info['idle_time']}\n\n"

        # Send status message
        await message.reply(users_text)

    except Exception as e:
        await message.reply(f"Erro ao obter status dos usuários: {str(e)}")


@ClientBot.on_message(
    filters.command("clear") & filters.private & custom_filters.is_admin
)
async def handle_clear_completed(bot: Client, message: Message):
    """Handle clear command to remove completed tasks from history"""
    try:
        # Clear completed tasks
        download_manager.completed_downloads.clear()
        upload_manager.completed_uploads.clear()

        await message.reply("✅ Histórico de tarefas concluídas foi limpo!")

    except Exception as e:
        await message.reply(f"Erro ao limpar histórico: {str(e)}")
