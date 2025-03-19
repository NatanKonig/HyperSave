import os
from pathlib import Path

from hypersave.logger import logger
from hypersave.settings import Settings

settings = Settings()


def ensure_directories_exist():
    """Ensure all required directories exist"""
    try:
        directories = [settings.DOWNLOADS_DIR, settings.THUMBS_DIR, Path("sessions")]

        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            logger.info(f"Ensured directory exists: {directory}")

            # Verify directory is writable
            test_file = directory / ".write_test"
            try:
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
            except Exception as e:
                logger.error(f"Directory is not writable: {directory} - {e}")
    except Exception as e:
        logger.error(f"Error ensuring directories exist: {e}")
