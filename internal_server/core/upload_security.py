"""Shared validation for user-uploaded media files.

Centralizes the allow-list and content-sniffing so every upload path
(web admin upload, DRF upload, workorder photo upload) applies the same
rules. Without this an attacker could upload `.html`/`.svg` files that,
served from the app origin under `/media/`, become stored-XSS payloads.

Two kinds of files are accepted:
  - Images: validated by actually decoding the bytes with Pillow (so a
    renamed `.exe` is rejected regardless of its name).
  - Videos: extension-only check (no ffmpeg-based content sniff here; the
    downstream `_make_video_thumbnail` is best-effort and tolerates fakes).
"""
import os

# Image extensions Pillow can both identify AND we want to accept.
ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
# Video extensions the thumbnail pipeline knows how to handle.
ALLOWED_VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.m4v', '.webm', '.mkv'}
ALLOWED_EXTS = ALLOWED_IMAGE_EXTS | ALLOWED_VIDEO_EXTS

# Per-file size cap (50 MB). The global DATA_UPLOAD_MAX_MEMORY_SIZE is 100 MB,
# but capping individual photos/videos well below that limits memory abuse.
MAX_FILE_BYTES = 50 * 1024 * 1024


def validate_upload(uploaded_file):
    """Validate a single Django UploadedFile. Returns (ok, error_message).

    `ok` is True when the file passes both the extension and content checks.
    On failure, `error_message` is a user-facing string (Chinese, matching the
    rest of the app); on success it is None.
    """
    name = getattr(uploaded_file, 'name', '') or ''
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTS:
        return False, f'不支持的文件类型: {ext or "(无扩展名)"}。仅允许图片(jpg/png/webp等)或视频(mp4/mov等)。'

    # Size check — read .size (already buffered by Django), cheap.
    size = getattr(uploaded_file, 'size', 0) or 0
    if size == 0:
        # 0-byte parts happen on iOS when iCloud photos aren't downloaded locally
        # before the picker returns them; the multipart header arrives but the body
        # is empty. PIL.verify() catches this for images, but videos skip the content
        # check, so reject by size up front for every file type.
        return False, '文件为空，可能是设备未完成下载/转码。请在相册中确认照片已下载到本地后重试。'
    if size > MAX_FILE_BYTES:
        return False, f'文件过大({size // (1024*1024)}MB)，单文件上限 {MAX_FILE_BYTES//(1024*1024)}MB。'

    # For images, confirm the bytes really decode — blocks renamed-payload uploads.
    if ext in ALLOWED_IMAGE_EXTS:
        try:
            from PIL import Image, UnidentifiedImageError
            # Seek to start in case the file was already read downstream.
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
            with Image.open(uploaded_file) as img:
                img.verify()  # only parses headers; doesn't decode pixels
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
        except UnidentifiedImageError:
            return False, '图片内容无法识别，可能已损坏或不是真正的图片文件。'
        except Exception:
            return False, '图片校验失败，请确认文件未损坏。'

    return True, None
