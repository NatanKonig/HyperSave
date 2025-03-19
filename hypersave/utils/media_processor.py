import asyncio
import os
import shutil
from asyncio.subprocess import PIPE
from pathlib import Path
from shutil import rmtree

import cv2
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from hypersave.logger import logger
from hypersave.settings import Settings

settings = Settings()


async def compress_image(
    input_path: Path, output_path: Path, quality: int = 85
) -> Path:
    """
    Compress an image to reduce file size

    Args:
        input_path: Path to input image
        output_path: Path to save compressed image
        quality: JPEG quality (0-100)

    Returns:
        Path to the compressed image
    """
    try:
        with Image.open(input_path) as img:
            # Convert to RGB if needed (for PNG with transparency)
            if img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            ):
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(
                    img, mask=img.split()[3] if img.mode == "RGBA" else None
                )
                img = background

            # Save with compression
            img.save(output_path, format="JPEG", quality=quality, optimize=True)

            # If still too large, try more compression
            if os.path.getsize(output_path) > 10 * 1024 * 1024 and quality > 30:
                return await compress_image(input_path, output_path, quality - 20)

            return output_path
    except Exception as e:
        logger.error(f"Error compressing image: {e}")
        # Try using ffmpeg as a fallback
        try:
            cmd = [
                "ffmpeg",
                "-i",
                str(input_path),
                "-q:v",
                "5",  # Quality level (lower means better quality but larger file)
                "-y",
                str(output_path),
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd, stderr=PIPE, stdout=PIPE
            )
            await process.communicate()

            if process.returncode == 0 and os.path.exists(output_path):
                return output_path
        except Exception as ffmpeg_err:
            logger.error(f"Error compressing image with ffmpeg: {ffmpeg_err}")

        # Last resort: make a copy
        shutil.copy(input_path, output_path)
        return output_path


async def resize_image(
    input_path: Path, output_path: Path, max_width: int = 4000, max_height: int = 4000
) -> Path:
    """
    Resize an image to fit within max dimensions while preserving aspect ratio

    Args:
        input_path: Path to input image
        output_path: Path to save resized image
        max_width: Maximum width
        max_height: Maximum height

    Returns:
        Path to the resized image
    """
    try:
        with Image.open(input_path) as img:
            width, height = img.size

            # Calculate new dimensions
            if width > max_width or height > max_height:
                if width / max_width > height / max_height:
                    # Width is the limiting factor
                    new_width = max_width
                    new_height = int(height * (max_width / width))
                else:
                    # Height is the limiting factor
                    new_height = max_height
                    new_width = int(width * (max_height / height))

                # Resize image
                resized_img = img.resize((new_width, new_height), Image.LANCZOS)
                resized_img.save(output_path)
            else:
                # Just copy if no resize needed
                shutil.copy(input_path, output_path)

            return output_path
    except Exception as e:
        logger.error(f"Error resizing image: {e}")
        # Try using ffmpeg as a fallback
        try:
            cmd = [
                "ffmpeg",
                "-i",
                str(input_path),
                "-vf",
                f"scale='min({max_width},iw)':'min({max_height},ih)'",
                "-y",
                str(output_path),
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd, stderr=PIPE, stdout=PIPE
            )
            await process.communicate()

            if process.returncode == 0 and os.path.exists(output_path):
                return output_path
        except Exception as ffmpeg_err:
            logger.error(f"Error resizing image with ffmpeg: {ffmpeg_err}")

        # Last resort: make a copy
        shutil.copy(input_path, output_path)
        return output_path


async def fix_aspect_ratio(input_path: Path, output_path: Path) -> Path:
    """
    Fix extreme aspect ratios by adding padding or cropping

    Args:
        input_path: Path to input image
        output_path: Path to save fixed image

    Returns:
        Path to the fixed image
    """
    try:
        with Image.open(input_path) as img:
            width, height = img.size
            aspect_ratio = width / height

            if aspect_ratio > 20:  # Very wide image
                # Add padding to increase height
                new_height = int(width / 10)  # Make aspect ratio 10:1
                new_img = Image.new(img.mode, (width, new_height), (255, 255, 255))
                paste_y = (new_height - height) // 2
                new_img.paste(img, (0, paste_y))
                new_img.save(output_path)
            elif aspect_ratio < 0.05:  # Very tall image
                # Add padding to increase width
                new_width = int(height / 10)  # Make aspect ratio 1:10
                new_img = Image.new(img.mode, (new_width, height), (255, 255, 255))
                paste_x = (new_width - width) // 2
                new_img.paste(img, (paste_x, 0))
                new_img.save(output_path)
            else:
                # Just copy if no fix needed
                shutil.copy(input_path, output_path)

            return output_path
    except Exception as e:
        logger.error(f"Error fixing aspect ratio: {e}")
        # Last resort: make a copy
        shutil.copy(input_path, output_path)
        return output_path


async def get_video_info(video_path: Path) -> tuple:
    """
    Get video information (duration, width, height)

    Args:
        video_path: Path to the video file

    Returns:
        tuple: (duration, width, height)
    """
    try:
        video = cv2.VideoCapture(str(video_path))
        if not video.isOpened():
            logger.error(f"Failed to open video {video_path}")
            raise RuntimeError(f"Failed to open video {video_path}")

        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = int(frame_count / fps) if fps > 0 else 0
        width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))

        video.release()

        logger.info(
            f"Video info: duration={duration}s, dimensions={width}x{height}, fps={fps}"
        )
        return duration, width, height
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        # Try with ffmpeg as fallback
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,duration",
                "-of",
                "csv=p=0",
                str(video_path),
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                output = stdout.decode().strip().split(",")
                if len(output) >= 3:
                    width = int(float(output[0]))
                    height = int(float(output[1]))
                    duration = int(float(output[2]))
                    logger.info(
                        f"Video info from ffprobe: duration={duration}s, dimensions={width}x{height}"
                    )
                    return duration, width, height

            logger.warning(f"Failed to get video info with ffprobe: {stderr.decode()}")
            # If ffprobe fails or returns invalid data
            return 0, 640, 480  # Default values
        except Exception as ffprobe_err:
            logger.error(f"Error getting video info with ffprobe: {ffprobe_err}")
            return 0, 640, 480  # Default values


async def get_video_thumbnail(video_path: Path, output_path: Path) -> Path:
    """
    Extract thumbnail from a video while preserving aspect ratio

    Args:
        video_path: Path to video file
        output_path: Path to save thumbnail

    Returns:
        Path to the thumbnail
    """
    if not os.path.exists(video_path):
        logger.error(f"Video file not found for thumbnail: {video_path}")
        return None

    try:
        # Ensure output directory exists
        os.makedirs(output_path.parent, exist_ok=True)

        # First try using ffmpeg (simple method without resizing)
        cmd = [
            "ffmpeg",
            "-i",
            str(video_path),
            "-ss",
            "00:00:02",  # Take frame from 1 second in
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(*cmd, stderr=PIPE, stdout=PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode == 0 and os.path.exists(output_path):
            logger.info(f"Successfully created thumbnail with ffmpeg: {output_path}")
            return output_path

        # If ffmpeg fails, try with OpenCV
        logger.info("Trying to extract thumbnail with OpenCV")
        cap = cv2.VideoCapture(str(video_path))

        # Check if video opened successfully
        if not cap.isOpened():
            logger.error(f"Failed to open video {video_path}")
            return None

        # Move to 1 second in if possible
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps > 0:
            target_frame = int(1 * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

        # Read frame
        success, frame = cap.read()
        if success:
            cv2.imwrite(str(output_path), frame)
            cap.release()
            logger.info(f"Successfully created thumbnail with OpenCV: {output_path}")
            return output_path
        else:
            logger.error("Failed to read frame with OpenCV")
            cap.release()
            return None

    except Exception as e:
        logger.error(f"Error getting video thumbnail: {e}")
        return None


async def ensure_valid_thumbnail(
    thumbnail_path: Path, video_width: int, video_height: int
) -> Path:
    """
    Ensure thumbnail meets Telegram's requirements

    Args:
        thumbnail_path: Path to thumbnail image
        video_width: Original video width
        video_height: Original video height

    Returns:
        Path to valid thumbnail
    """
    if not os.path.exists(thumbnail_path):
        logger.error(f"Thumbnail file not found: {thumbnail_path}")
        return None

    try:
        # Open the image
        with Image.open(thumbnail_path) as img:
            original_width, original_height = img.size
            logger.info(
                f"Original thumbnail dimensions: {original_width}x{original_height}"
            )

            # Check if dimensions are already valid
            if is_valid_dimensions(original_width, original_height):
                logger.info("Thumbnail dimensions are valid")
                return thumbnail_path

            # Calculate new dimensions that maintain aspect ratio and meet Telegram's requirements
            # Telegram thumbnail requirements appear to be:
            # - Minimum dimensions: 90x90
            # - Maximum dimensions: around 1280x1280 (though this varies)
            # - Must maintain reasonable aspect ratio (not too extreme)

            # Use the video's aspect ratio to guide thumbnail creation
            video_aspect = video_width / video_height

            # Determine target dimensions based on video aspect ratio
            if video_aspect >= 1:  # Landscape or square video
                # For landscape, set width to 800-1000px and adjust height
                new_width = 1000
                new_height = int(new_width / video_aspect)
            else:  # Portrait video
                # For portrait, set height to 800-1000px and adjust width
                new_height = 1000
                new_width = int(new_height * video_aspect)

            # Ensure minimum dimensions
            new_width = max(new_width, 90)
            new_height = max(new_height, 90)

            # Ensure reasonable aspect ratio (not too extreme)
            if new_width / new_height > 5:  # Very wide
                new_height = int(new_width / 5)
            elif new_height / new_width > 5:  # Very tall
                new_width = int(new_height / 5)

            # Resize the image
            logger.info(f"Resizing thumbnail to {new_width}x{new_height}")
            resized_img = img.resize((new_width, new_height), Image.LANCZOS)

            # Save to a new file to avoid any issues
            fixed_path = thumbnail_path.with_name(
                f"{thumbnail_path.stem}_fixed{thumbnail_path.suffix}"
            )
            resized_img.save(fixed_path)

            # Replace original with fixed version
            shutil.move(str(fixed_path), str(thumbnail_path))

            return thumbnail_path
    except Exception as e:
        logger.error(f"Error ensuring valid thumbnail: {e}")
        return None


def is_valid_dimensions(width: int, height: int) -> bool:
    """
    Check if image dimensions are valid for Telegram

    Args:
        width: Image width
        height: Image height

    Returns:
        True if dimensions are valid, False otherwise
    """
    # Minimum dimensions
    if width < 90 or height < 90:
        return False

    # Maximum dimensions (conservative estimate)
    if width > 4000 or height > 4000:
        return False

    # Aspect ratio check
    aspect_ratio = width / height
    if aspect_ratio > 5 or aspect_ratio < 0.2:
        return False

    return True


async def resize_thumbnail(image_path: Path) -> Path:
    """
    Resize a thumbnail to ensure it meets Telegram's requirements.
    Telegram requires thumbnails with specific dimensions.

    Args:
        image_path: Path to the image to resize

    Returns:
        Path to the resized image
    """
    if not os.path.exists(image_path):
        logger.error(f"Image not found for resizing: {image_path}")
        return None

    try:
        # Open and resize image to 320x180 (16:9 aspect ratio commonly used for video thumbnails)
        # These dimensions are known to work well with Telegram
        with Image.open(image_path) as img:
            # Calculate dimensions to maintain aspect ratio
            width, height = img.size
            target_width, target_height = 320, 180

            # Create a new image with black background
            new_img = Image.new("RGB", (target_width, target_height), color=(0, 0, 0))

            # Calculate resize dimensions maintaining aspect ratio
            if width / height > target_width / target_height:
                # Image is wider than target
                new_width = target_width
                new_height = int(height * (target_width / width))
            else:
                # Image is taller than target
                new_height = target_height
                new_width = int(width * (target_height / height))

            # Resize the original image
            resized_img = img.resize((new_width, new_height), Image.LANCZOS)

            # Calculate position to center the image
            x = (target_width - new_width) // 2
            y = (target_height - new_height) // 2

            # Paste the resized image onto the black background
            new_img.paste(resized_img, (x, y))

            # Save the image
            new_img.save(image_path)
            logger.info(
                f"Resized thumbnail to {target_width}x{target_height}: {image_path}"
            )
            return image_path
    except Exception as e:
        logger.error(f"Error resizing thumbnail: {e}")

        # Try a more direct approach if the above fails
        try:
            img = Image.new("RGB", (320, 180), color=(0, 0, 0))
            img.save(image_path)
            logger.warning(f"Created replacement thumbnail: {image_path}")
            return image_path
        except Exception as e2:
            logger.error(f"Failed to create replacement thumbnail: {e2}")
            return None


async def move_metadata_to_start(video_path: Path):
    """
    Move metadata to start of video file for faster streaming

    Args:
        video_path: Path to the video file
    """
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return

    try:
        tmp_video_path = video_path.with_suffix(".tmp.mp4")

        cmd = [
            "ffmpeg",
            "-i",
            str(video_path),
            "-c",
            "copy",
            "-movflags",
            "faststart",
            "-y",
            str(tmp_video_path),
        ]

        process = await asyncio.create_subprocess_exec(*cmd, stderr=PIPE, stdout=PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode == 0 and os.path.exists(tmp_video_path):
            # Replace original with optimized version
            os.replace(str(tmp_video_path), str(video_path))
        else:
            logger.warning(f"Failed to optimize video {video_path}: {stderr.decode()}")
    except FileNotFoundError as e:
        logger.error(f"Error optimizing video (ffmpeg not found): {e}")
    except Exception as e:
        logger.error(f"Error optimizing video: {e}")


async def extract_frames(
    video_path: Path, frames_count: int, output_folder: Path
) -> list:
    """
    Extract frames from a video

    Args:
        video_path: Path to the video file
        frames_count: Number of frames to extract
        output_folder: Folder to save frames

    Returns:
        List of paths to extracted frames
    """
    try:
        # Ensure output folder exists
        os.makedirs(output_folder, exist_ok=True)

        # Get video duration and FPS
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.error(f"Failed to open video: {video_path}")
            return []

        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        # Check if video is valid
        if duration <= 0 or total_frames <= 0:
            logger.error(f"Invalid video duration or frame count: {video_path}")
            cap.release()
            return []

        # Calculate frame intervals
        interval = duration / frames_count

        frame_paths = []

        # Extract frames directly with OpenCV
        for i in range(frames_count):
            # Calculate position in seconds
            position_sec = i * interval
            position_frame = int(position_sec * fps)

            # Set position
            cap.set(cv2.CAP_PROP_POS_FRAMES, position_frame)

            # Read frame
            success, frame = cap.read()
            if not success:
                logger.warning(f"Failed to read frame at position {position_sec}s")
                continue

            # Save frame
            frame_path = output_folder / f"thumb{i+1:03d}.jpg"
            cv2.imwrite(str(frame_path), frame)

            # Add timestamp
            await draw_time_on_image(frame_path, position_sec)

            frame_paths.append(frame_path)

        cap.release()

        logger.info(
            f"Successfully extracted {len(frame_paths)} frames from {video_path}"
        )
        return frame_paths

    except Exception as e:
        logger.error(f"Error extracting frames: {e}")
        return []


async def draw_time_on_image(image_path: Path, time_seconds: float):
    """
    Add timestamp to an image

    Args:
        image_path: Path to the image
        time_seconds: Timestamp in seconds
    """
    try:
        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)

        # Format time string
        hours, remainder = divmod(int(time_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
        else:
            time_str = f"{minutes:02}:{seconds:02}"

        # Get font size proportional to image width
        font_size = int(min(img.width, img.height) * 0.1)
        font_size = max(10, min(font_size, 40))  # Keep font size reasonable

        # Try to use available fonts
        font = None
        try:
            font = ImageFont.truetype("Arial.ttf", font_size)
        except IOError:
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", font_size)
            except IOError:
                # Use default font if no specific font is found
                font = ImageFont.load_default()

        # Calculate text size
        text_bbox = draw.textbbox((0, 0), time_str, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Position text at top right
        padding = 10
        text_position = (img.width - text_width - padding, padding)

        # Draw semi-transparent background
        bg_margin = 5
        background_position = [
            text_position[0] - bg_margin,
            text_position[1] - bg_margin,
            text_position[0] + text_width + bg_margin,
            text_position[1] + text_height + bg_margin,
        ]

        # Draw background with alpha
        draw.rectangle(background_position, fill=(0, 0, 0, 128))

        # Draw text
        draw.text(text_position, time_str, font=font, fill="white")

        # Save image
        img.save(image_path)

    except Exception as e:
        logger.error(f"Error drawing time on image: {e}")


async def create_thumb_grid(
    frames_folder: Path, frame_paths: list, output_path: Path, grid_size: tuple = (4, 4)
) -> Path:
    """
    Create a grid of thumbnails

    Args:
        frames_folder: Folder containing frame images
        frame_paths: List of paths to frame images
        output_path: Path to save the grid image
        grid_size: Grid dimensions (width, height)

    Returns:
        Path to the grid image
    """
    try:
        # Ensure we have frames
        if not frame_paths:
            logger.error("No frames provided for grid creation")
            return None

        # Open the first image to get dimensions
        first_img = Image.open(frame_paths[0])
        frame_width, frame_height = first_img.size

        # Calculate grid dimensions
        grid_width = grid_size[0] * frame_width
        grid_height = grid_size[1] * frame_height

        # Create grid image
        grid_img = Image.new("RGB", (grid_width, grid_height))

        # Paste images into grid
        for index, frame_path in enumerate(frame_paths):
            if index >= grid_size[0] * grid_size[1]:
                break

            try:
                img = Image.open(frame_path)
                x = (index % grid_size[0]) * frame_width
                y = (index // grid_size[0]) * frame_height
                grid_img.paste(img, (x, y))
            except Exception as e:
                logger.warning(f"Error processing frame {frame_path}: {e}")

        # Ensure output directory exists
        os.makedirs(output_path.parent, exist_ok=True)

        # Save grid image
        grid_img.save(output_path)
        logger.info(f"Created thumbnail grid at {output_path}")

        # Clean up frames folder
        try:
            import shutil

            shutil.rmtree(frames_folder)
        except Exception as e:
            logger.warning(f"Failed to clean up frames folder: {e}")

        return output_path

    except Exception as e:
        logger.error(f"Error creating thumbnail grid: {e}")
        return None


async def process_video_thumb(
    video_path: Path, thumb_path: Path, duration: int
) -> Path:
    """
    Process video to create a thumbnail grid

    Args:
        video_path: Path to the video file
        thumb_path: Path to save the thumbnail grid
        duration: Video duration in seconds

    Returns:
        Path to the thumbnail grid
    """
    try:
        settings = Settings()
        # Create folder for frames
        frames_folder = settings.THUMBS_DIR / video_path.stem

        # Determine grid layout based on duration
        if duration < 300:  # < 5 minutes
            frames = 12
            grid = (4, 3)
        elif duration < 600:  # < 10 minutes
            frames = 16
            grid = (4, 4)
        elif duration < 1800:  # < 30 minutes
            frames = 25
            grid = (5, 5)
        else:  # >= 30 minutes
            frames = 36
            grid = (6, 6)

        # Extract frames
        frame_paths = await extract_frames(video_path, frames, frames_folder)

        if not frame_paths:
            logger.warning(
                "No frames extracted for thumbnail grid, getting single thumbnail"
            )
            # Fallback to just using a single thumbnail
            return await get_video_thumbnail(video_path, thumb_path)

        # Create thumbnail grid
        return await create_thumb_grid(frames_folder, frame_paths, thumb_path, grid)

    except Exception as e:
        logger.error(f"Error in process_video_thumb: {e}")
        # Try to get a single frame as fallback
        return await get_video_thumbnail(video_path, thumb_path)
