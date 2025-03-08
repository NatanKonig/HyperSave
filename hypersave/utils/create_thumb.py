import asyncio
from asyncio.subprocess import PIPE
from pathlib import Path
from shutil import rmtree

import cv2
from PIL import Image, ImageDraw, ImageFont

from hypersave.logger import logger


async def extract_frames(video_path: Path, frames: int):
    folder = Path("lives/thumbs") / video_path.stem
    folder.mkdir(parents=True, exist_ok=True)
    duration, _, _ = await get_video_info(video_path)
    interval = duration / frames

    for i in range(frames):
        time = i * interval
        out_path = folder / f"thumb{i+1:03d}.jpg"
        cmd = [
            "ffmpeg",
            "-ss",
            str(time),
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            out_path,
        ]

        p = await asyncio.create_subprocess_exec(*cmd, stderr=PIPE, stdout=PIPE)
        await p.communicate()
        await p.wait()
        await draw_time_on_image(out_path, time)


async def get_video_info(video_path: Path):
    video = cv2.VideoCapture(str(video_path))
    if not video.isOpened():
        raise BufferError(f"erro ao abrir video {video_path}")
    fps = video.get(cv2.CAP_PROP_FPS)
    fc = video.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = int(fc / fps)
    width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))

    video.release()

    return duration, width, height


async def draw_text_in_center(image_path: Path, text: str):
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 80)
    except IOError:
        font = ImageFont.load_default()

    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    image_width, image_height = img.size
    text_position = (
        (image_width - text_width) // 2,
        (image_height - text_height) // 2 + (image_height // 54),
    )
    background_position = [
        text_position[0] - 10,
        text_position[1] - 10,
        text_position[0] + text_width + 20,
        text_position[1] + text_height + 20,
    ]
    draw.rectangle(background_position, fill=(0, 0, 0))

    shadow_offset = (2, 2)
    shadow_color = (0, 0, 0)
    text_color = (255, 255, 255)

    draw.text(
        (text_position[0] + shadow_offset[0], text_position[1] + shadow_offset[1]),
        text,
        font=font,
        fill=shadow_color,
    )
    draw.text(text_position, text, font=font, fill=text_color)
    img = img.convert("RGB")
    img.save(image_path)


async def draw_time_on_image(image_path: Path, time_seconds: float):
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    hours, remainder = divmod(int(time_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
    else:
        time_str = f"{minutes:02}:{seconds:02}"
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 60)
    except IOError:
        font = ImageFont.load_default()
    text_bbox = draw.textbbox((0, 0), time_str, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_position = (10, img.height - text_height - 10)
    background_position = [
        text_position[0] - 5,
        text_position[1] - 5,
        text_position[0] + text_width + 10,
        text_position[1] + text_height + 10,
    ]
    draw.rectangle(background_position, fill=(0, 0, 0))
    shadow_offset = (2, 2)
    shadow_color = (0, 0, 0)
    text_color = (255, 255, 255)
    draw.text(
        (text_position[0] + shadow_offset[0], text_position[1] + shadow_offset[1]),
        time_str,
        font=font,
        fill=shadow_color,
    )
    draw.text(text_position, time_str, font=font, fill=text_color)
    img = img.convert("RGB")
    img.save(image_path)


async def create_thumb_grid(out_path: Path, grid_size: tuple[int, int] = (4, 4)):
    folder = Path("../downloads/thumbs") / out_path.stem
    frame_files = sorted(folder.glob("*.jpg"))

    if len(frame_files) < grid_size[0] * grid_size[1]:
        logger.error("Não há frames suficientes para criar a miniatura.")
    selected_frames = frame_files[: grid_size[0] * grid_size[1]]
    images = [Image.open(frame) for frame in selected_frames]
    width, height = images[0].size
    grid_img = Image.new("RGB", (grid_size[0] * width, grid_size[1] * height))

    for index, img in enumerate(images):
        x = (index % grid_size[0]) * width
        y = (index // grid_size[0]) * height
        grid_img.paste(img, (x, y))

    grid_img.save(out_path)
    rmtree(folder)


async def process_video_thumb(
    video_path: Path, thumb_path: Path, frames: int = 16, grid=(4, 4)
):
    await extract_frames(video_path, frames)
    await create_thumb_grid(thumb_path, grid)
    # await draw_text_in_center(thumb_path, "TG: @BuzzDownloaderBot")
    return thumb_path


async def move_metadata_to_start(video_path: Path):
    tmp_video_path = video_path.with_suffix(".tmp.mp4")
    command = [
        "ffmpeg",
        "-i",
        video_path,
        "-c",
        "copy",
        "-movflags",
        "faststart",
        "-y",
        tmp_video_path,
    ]

    p = await asyncio.create_subprocess_exec(*command, stderr=PIPE, stdout=PIPE)
    await p.wait()
    tmp_video_path.replace(video_path)


async def get_video_thumbnail(video_path: Path, output_path: Path):
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path)
    ]

    process = await asyncio.create_subprocess_exec(*cmd, stderr=PIPE, stdout=PIPE)
    await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"Falha ao extrair thumbnail de {video_path}")

    return output_path