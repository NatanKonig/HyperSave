import os
from shutil import rmtree

from hypersave.logger import logger
from hypersave.settings import Settings

settings = Settings()


def clear_and_create_folders() -> None:
    paths = [str(settings.DOWNLOADS_DIR), str(settings.THUMBS_DIR)]

    for folder in paths:
        if not os.path.exists(folder):
            continue

        root_folder = os.path.abspath(folder)

        for root, dirs, files in os.walk(root_folder, topdown=False):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    os.remove(file_path)
                    logger.info(f"Arquivo removido: {file_path}")
                except Exception as e:
                    logger.error(f"Error removing file {file_path}: {e}")

            for dir in dirs:
                dir_path = os.path.join(root, dir)
                try:
                    rmtree(dir_path)
                    logger.info(f"Pasta removida: {dir_path}")
                except Exception as e:
                    logger.error(f"Error removing directory {dir_path}: {e}")

    settings._create_directories()
