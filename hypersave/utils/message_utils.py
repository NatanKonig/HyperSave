from collections import defaultdict
from typing import List

from pyrogram import Client, enums
from pyrogram.types import Message

from hypersave.database.models import User
from hypersave.database.user_repository import UserRepository

user_repository = UserRepository()


async def save_message_info(message: Message):
    if str(message.chat.type) == "ChatType.PRIVATE":
        await process_private_message(message)


async def process_private_message(message):
    user_id = message.from_user.id
    name = f'{message.from_user.first_name} {message.from_user.last_name if message.from_user.last_name else ""}'
    username = message.from_user.username
    user = User(t_id=user_id, t_name=name, t_username=username)
    user_repository.add(user)


async def format_message_entities(message_text: str, entities: List = None) -> str:
    """
    Format message text with entities (bold, italic, etc)

    Args:
        message_text: Raw message text
        entities: Message entities

    Returns:
        Formatted message text
    """
    if not message_text or not entities:
        return message_text

    # Define priority for entities (some should override others)
    priority = {
        enums.MessageEntityType.BOLD: 1,
        enums.MessageEntityType.ITALIC: 2,
        enums.MessageEntityType.UNDERLINE: 3,
        enums.MessageEntityType.STRIKETHROUGH: 4,
        enums.MessageEntityType.SPOILER: 5,
        enums.MessageEntityType.CODE: 6,
        enums.MessageEntityType.PRE: 7,
        enums.MessageEntityType.TEXT_LINK: 8,
        enums.MessageEntityType.HASHTAG: 9,
    }
    default_priority = 100

    # Group entities by position
    entity_dict = defaultdict(list)
    for entity in entities:
        start = entity.offset
        end = entity.offset + entity.length
        entity_dict[(start, end)].append(entity)

    # Build formatted text
    last_end = 0
    result = []

    for (start, end), entities_at_pos in sorted(entity_dict.items()):
        # Add any text before this entity
        if start > last_end:
            result.append(message_text[last_end:start])

        # Get text for this entity
        formatted_text = message_text[start:end]

        # Sort entities by priority
        entities_at_pos.sort(
            key=lambda x: priority.get(x.type, default_priority), reverse=True
        )

        # Apply formatting for each entity
        for entity in entities_at_pos:
            if entity.type == enums.MessageEntityType.BOLD:
                formatted_text = f"**{formatted_text}**"
            elif entity.type == enums.MessageEntityType.ITALIC:
                formatted_text = f"__{formatted_text}__"
            elif entity.type == enums.MessageEntityType.UNDERLINE:
                formatted_text = f"--{formatted_text}--"
            elif entity.type == enums.MessageEntityType.STRIKETHROUGH:
                formatted_text = f"~~{formatted_text}~~"
            elif entity.type == enums.MessageEntityType.SPOILER:
                formatted_text = f"||{formatted_text}||"
            elif entity.type == enums.MessageEntityType.CODE:
                formatted_text = f"`{formatted_text}`"
            elif entity.type == enums.MessageEntityType.PRE:
                formatted_text = f"```{formatted_text}```"
            elif entity.type == enums.MessageEntityType.TEXT_LINK:
                formatted_text = f"[{formatted_text}]({entity.url})"
            elif entity.type == enums.MessageEntityType.HASHTAG:
                formatted_text = f"{formatted_text}"

        # Add formatted text to result
        result.append(formatted_text)
        last_end = end

    # Add any remaining text
    if last_end < len(message_text):
        result.append(message_text[last_end:])

    return "".join(result)
