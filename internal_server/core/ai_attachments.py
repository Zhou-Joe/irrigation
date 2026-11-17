"""Private, calendar-day attachments for the general EnGenie conversation.

Uploads never invoke a model or change business data. Every read rechecks the
conversation owner/day; opaque files and parsing caches live inside its workspace.
"""
import base64
import binascii
import csv
import io
import json
import logging
import os
import re
import stat
import time
import unicodedata
import uuid
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import OperationalError
from django.http import FileResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .ai_history import maybe_prune_history, policy
from .ai_storage import ConversationExpired, conversation_for, private_root
from .models import AISettings
from .role_utils import get_user_role, ROLE_MANAGER, ROLE_SUPER_ADMIN

logger = logging.getLogger(__name__)
MAX_FILE = 10 * 1024 * 1024
MAX_THREAD = 50 * 1024 * 1024
MAX_FILES = 5
MAX_EXPANDED = 40 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_PDF_PAGE = 8 * 1024 * 1024
MAX_TEXT = 2_000_000
MAX_ROWS = 5000
MAX_COLUMNS = 200
READ_LIMIT = 12000
PARSE_VERSION = 2
TYPES = {
    '.txt': ('text', 'text/plain'), '.md': ('text', 'text/markdown'),
    '.log': ('text', 'text/plain'), '.json': ('text', 'application/json'),
    '.csv': ('spreadsheet', 'text/csv'),
    '.xlsx': ('spreadsheet', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    '.docx': ('document', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    '.pdf': ('pdf', 'application/pdf'), '.png': ('image', 'image/png'),
    '.jpg': ('image', 'image/jpeg'), '.jpeg': ('image', 'image/jpeg'),
    '.webp': ('image', 'image/webp'),
}
TABULAR = {'.csv', '.xlsx', '.json'}
ORIGINAL_RE = re.compile(r'[0-9a-f]{32}\.(?:txt|md|log|json|csv|xlsx|docx|pdf|png|jpg|jpeg|webp)\Z')


class AttachmentError(ValueError):
    def __init__(self, message, *, status=400):
        self.status = status
        super().__init__(message)


def _error(exc):
    response = JsonResponse({'success': False, 'error': str(exc), 'message': str(exc)}, status=exc.status)
    response['Cache-Control'] = 'private, no-store'
    return response


def _conversation(thread_id, user_id, *, create=False):
    try:
        user = get_user_model().objects.get(pk=user_id, is_active=True)
    except (get_user_model().DoesNotExist, ValueError, TypeError):
        raise AttachmentError('请先登录有权限的账号。', status=403) from None
    try:
        return conversation_for(user, thread_id, create=create, title='附件分析')
    except ConversationExpired:
        raise AttachmentError('对话已过期，请开启今天的新对话后上传。', status=410) from None
    except (PermissionDenied, ValueError, TypeError):
        raise AttachmentError('无权访问此对话的附件。', status=403) from None


def _directory(thread_id, *, create=False):
    """Validate every directory component, including workspaces itself."""
    parent = private_root()
    for name in ('workspaces', thread_id, 'uploads'):
        child = parent / name
        if child.is_symlink():
            raise AttachmentError('附件目录不可用，请联系管理员。', status=409)
        if not child.exists():
            if not create:
                return None
            try:
                child.mkdir(mode=0o700)
            except FileExistsError:
                pass
        if child.is_symlink() or not child.is_dir() or child.resolve().parent != parent.resolve():
            raise AttachmentError('附件目录不可用，请联系管理员。', status=409)
        parent = child
    return parent


def _regular_open(path, *, exclusive=False):
    if path.is_symlink():
        raise AttachmentError('附件不可用。', status=404)
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL) if exclusive else os.O_RDONLY
    flags |= getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise AttachmentError('附件不可用。', status=404)
    return os.fdopen(fd, 'wb' if exclusive else 'rb')


@contextmanager
def _upload_lock(directory):
    """One quota/write lock across Django workers, on Windows and Linux."""
    path = directory / '.attachments.lock'
    if path.is_symlink():
        raise AttachmentError('附件目录正在更新，请稍后重试。', status=409)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise AttachmentError('附件目录不可用。', status=409)
        if os.fstat(fd).st_size == 0:
            os.write(fd, b'\0')
        deadline = time.monotonic() + 3
        while not locked:
            try:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise AttachmentError('附件正在上传，请稍后重试。', status=409) from None
                time.sleep(.05)
        yield
    finally:
        if locked:
            if os.name == 'nt':
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic_json(path, data):
    temporary = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    try:
        with _regular_open(temporary, exclusive=True) as handle:
            handle.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
        if path.is_symlink():
            raise AttachmentError('附件索引不可用。', status=409)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise AttachmentError('附件编号无效。', status=404) from None


def _public(meta):
    fields = ('id', 'name', 'size', 'kind', 'mime', 'created_at', 'analysis_name', 'width', 'height')
    result = {key: meta[key] for key in fields if key in meta}
    result['url'] = reverse('core:ai_attachment_download', kwargs={'thread_id': meta['thread_id'], 'attachment_id': meta['id']})
    return result


def _metadata(directory, thread_id, user_id, attachment_id):
    key = _uuid(attachment_id)
    try:
        with _regular_open(directory / (key.hex + '.meta.json')) as handle:
            raw = handle.read(32 * 1024 + 1)
        if len(raw) > 32 * 1024:
            raise ValueError
        meta = json.loads(raw)
        ext = meta.get('ext')
        if (meta.get('id') != str(key) or meta.get('thread_id') != thread_id or
                meta.get('user_id') != int(user_id) or ext not in TYPES or
                meta.get('kind') != TYPES[ext][0] or not isinstance(meta.get('name'), str) or
                not isinstance(meta.get('created_at'), str) or
                not isinstance(meta.get('size'), int) or not 0 < meta['size'] <= MAX_FILE or
                meta.get('mime') not in ({'image/png', 'image/jpeg', 'image/webp'} if TYPES[ext][0] == 'image' else {TYPES[ext][1]})):
            raise ValueError
        if meta.get('analysis_name') and meta['analysis_name'] != 'attachment_' + key.hex + ext:
            raise ValueError
        path = directory / (key.hex + ext)
        if path.is_symlink() or not path.is_file() or path.stat().st_size != meta.get('size'):
            raise ValueError
        return meta, path
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        raise AttachmentError('附件不存在或已清理。', status=404) from None


def _zip(data, required):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
        if (len(entries) > 3000 or sum(item.file_size for item in entries) > MAX_EXPANDED or
                any(item.flag_bits & 1 or (item.file_size > 1024 * 1024 and item.file_size > 300 * max(item.compress_size, 1)) for item in entries)):
            archive.close()
            raise AttachmentError('文档解压后内容过大或已加密，请拆分或另存后上传。')
        if required not in archive.namelist():
            archive.close()
            raise AttachmentError('文件内容与扩展名不符，请另存为标准文档后上传。')
        return archive
    except (zipfile.BadZipFile, OSError):
        raise AttachmentError('文档格式无效，请另存后上传。') from None


def _decode(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        try:
            return data.decode('utf-16')
        except UnicodeError:
            raise AttachmentError('文本编码无效，请另存为 UTF-8 后上传。') from None
    if b'\0' in data:
        raise AttachmentError('该文件包含二进制内容，请上传文字文档。')
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return data.decode(encoding)
        except UnicodeError:
            pass
    raise AttachmentError('文本编码无法识别，请另存为 UTF-8 后上传。')


def _image_info(data):
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if not width or not height or width * height > MAX_PIXELS:
                raise AttachmentError('图片最多支持 2000 万像素，请缩小后上传。', status=413)
            if image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise AttachmentError('请上传 PNG、JPEG 或 WebP 图片。')
            mime = Image.MIME[image.format]
            image.verify()
        return {'width': width, 'height': height, 'mime': mime}
    except AttachmentError:
        raise
    except Exception:
        raise AttachmentError('图片损坏或格式无效，请重新导出后上传。') from None


def _validate(data, ext):
    if TYPES[ext][0] == 'image':
        return _image_info(data)
    if ext in ('.xlsx', '.docx'):
        with _zip(data, 'xl/workbook.xml' if ext == '.xlsx' else 'word/document.xml'):
            pass
    elif ext == '.pdf':
        if not data[:1024].lstrip().startswith(b'%PDF-'):
            raise AttachmentError('PDF 格式无效，请重新导出后上传。')
    else:
        _decode(data)
    return {}


@require_POST
@never_cache
def upload(request):
    if not request.user.is_authenticated or get_user_role(request.user) not in (ROLE_MANAGER, ROLE_SUPER_ADMIN):
        return _error(AttachmentError('无权限使用 AI 附件。', status=403))
    cfg = AISettings.get_settings()
    if not (cfg.enabled and cfg.api_base_url and cfg.api_key and cfg.model_name):
        return _error(AttachmentError('AI 助手尚未配置，请联系管理员。'))
    written = []
    try:
        maybe_prune_history()
        thread_id = (request.POST.get('thread_id') or '').strip()
        if thread_id:
            _conversation(thread_id, request.user.pk)
        files = [item for key in request.FILES for item in request.FILES.getlist(key)]
        if not files or len(files) > MAX_FILES:
            raise AttachmentError('每次请选择 1 至 5 个附件。')
        prepared = []
        for uploaded in files:
            original = unicodedata.normalize('NFC', str(uploaded.name or '').replace('\\', '/').rsplit('/', 1)[-1])
            original = ''.join(char for char in original if ord(char) >= 32 and ord(char) != 127).strip()
            ext = Path(original).suffix.lower()
            if ext not in TYPES:
                raise AttachmentError('支持文字、CSV、Excel、Word、PDF 及 PNG/JPEG/WebP 图片。')
            if not uploaded.size or uploaded.size > MAX_FILE:
                raise AttachmentError('单个附件不能为空，且不能超过 10 MB。', status=413)
            data = uploaded.read(MAX_FILE + 1)
            if not data or len(data) > MAX_FILE:
                raise AttachmentError('单个附件不能为空，且不能超过 10 MB。', status=413)
            info = _validate(data, ext)
            prepared.append((original[:180 - len(ext)] + ext if len(original) > 180 else original, ext, data, info))
        if not thread_id:
            thread_id = f'u{request.user.pk}-{uuid.uuid4().hex}'
            _conversation(thread_id, request.user.pk, create=True)
        directory = _directory(thread_id, create=True)
        attachments = []
        with _upload_lock(directory):
            _conversation(thread_id, request.user.pk)
            used = 0
            for entry in directory.iterdir():
                if ORIGINAL_RE.fullmatch(entry.name):
                    if entry.is_symlink() or not entry.is_file():
                        raise AttachmentError('附件目录不可用，请联系管理员。', status=409)
                    used += entry.stat().st_size
            if used + sum(len(item[2]) for item in prepared) > MAX_THREAD:
                raise AttachmentError('本对话附件总量不能超过 50 MB，请开启新对话。', status=413)
            for name, ext, data, info in prepared:
                key = uuid.uuid4()
                meta = {'id': str(key), 'thread_id': thread_id, 'user_id': request.user.pk,
                        'name': name, 'ext': ext, 'size': len(data), 'kind': TYPES[ext][0],
                        'mime': TYPES[ext][1], 'created_at': timezone.now().isoformat(), **info}
                path = directory / (key.hex + ext)
                with _regular_open(path, exclusive=True) as handle:
                    written.append(path)
                    handle.write(data)
                if ext in TABULAR:
                    meta['analysis_name'] = 'attachment_' + key.hex + ext
                    # Unique, opaque sandbox input; never overwrite business exports.
                    copy = directory.parent / meta['analysis_name']
                    with _regular_open(copy, exclusive=True) as handle:
                        written.append(copy)
                        handle.write(data)
                index = directory / (key.hex + '.meta.json')
                _atomic_json(index, meta)
                written.append(index)
                attachments.append(_public(meta))
            _conversation(thread_id, request.user.pk)
        response = JsonResponse({'success': True, 'thread_id': thread_id, 'attachments': attachments, **policy()})
        response['Cache-Control'] = 'private, no-store'
        return response
    except AttachmentError as exc:
        result = _error(exc)
    except OperationalError:
        result = _error(AttachmentError('附件目录正在更新，请稍后重试。', status=409))
    except (OSError, ValueError):
        logger.exception('Unable to save private AI attachments')
        result = _error(AttachmentError('附件保存失败，请稍后重试。', status=409))
    for path in reversed(written):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception('Unable to clean an incomplete AI attachment')
    return result


def list_attachments(thread_id, user_id):
    _conversation(thread_id, user_id)
    directory = _directory(thread_id)
    if directory is None:
        return []
    found = []
    for index in directory.glob('*.meta.json'):
        try:
            key = uuid.UUID(hex=index.name[:-10])
        except ValueError:
            continue
        meta, _ = _metadata(directory, thread_id, user_id, key)
        found.append(_public(meta))
    return sorted(found, key=lambda item: (item['created_at'], item['id']))


def _content(thread_id, user_id, attachment_id):
    _conversation(thread_id, user_id)
    directory = _directory(thread_id)
    if directory is None:
        raise AttachmentError('附件不存在或已清理。', status=404)
    meta, path = _metadata(directory, thread_id, user_id, attachment_id)
    try:
        with _regular_open(path) as handle:
            data = handle.read(MAX_FILE + 1)
    except OSError:
        raise AttachmentError('附件不存在或已清理。', status=404) from None
    if len(data) > MAX_FILE or len(data) != meta['size']:
        raise AttachmentError('附件内容已变化，请重新上传。', status=409)
    return meta, data, directory


class _Text:
    def __init__(self):
        self.parts = []
        self.total = 0
        self.stored = 0
        self.truncated = False
        self.notes = []
        self.unreadable_pages = []

    def add(self, text):
        text = str(text) + '\n'
        self.total += len(text)
        remaining = MAX_TEXT - self.stored
        if remaining > 0:
            self.parts.append(text[:remaining])
            self.stored += min(len(text), remaining)
        if len(text) > remaining:
            self.truncated = True

    def result(self):
        return {'version': PARSE_VERSION, 'text': ''.join(self.parts), 'total_chars': self.total,
                'extraction_truncated': self.truncated, 'notes': self.notes,
                'has_unreadable_pages': bool(self.unreadable_pages), 'unreadable_pages': self.unreadable_pages}


def _pdf_content_size(page):
    """Check content-stream expansion before pypdf performs its own decoding."""
    contents = page.get('/Contents')
    if contents is None:
        return 0
    contents = contents.get_object()
    streams = contents if isinstance(contents, list) else [contents]
    total = 0
    for reference in streams:
        stream = reference.get_object()
        payload = getattr(stream, '_data', None)
        if not isinstance(payload, bytes):
            raise AttachmentError('文本流格式无法安全解析，未读取此页。')
        filters = stream.get('/Filter', [])
        filters = filters.get_object() if hasattr(filters, 'get_object') else filters
        filters = [filters] if isinstance(filters, str) else filters
        try:
            for codec in filters:
                codec = str(codec)
                if codec in ('/FlateDecode', '/Fl'):
                    decoder = zlib.decompressobj()
                    payload = decoder.decompress(payload, MAX_PDF_PAGE + 1)
                    if len(payload) > MAX_PDF_PAGE or decoder.unconsumed_tail:
                        raise AttachmentError('文本流解压后超过 8 MB，未读取此页。')
                    if not decoder.eof:
                        raise AttachmentError('文本流压缩数据不完整，未读取此页。')
                elif codec in ('/ASCIIHexDecode', '/AHx'):
                    payload = b''.join(payload.split()).rstrip(b'>')
                    payload = binascii.unhexlify(payload + (b'0' if len(payload) % 2 else b''))
                elif codec in ('/ASCII85Decode', '/A85'):
                    payload = payload.strip()
                    payload = base64.a85decode(payload, adobe=True) if payload.startswith(b'<~') else base64.a85decode(payload.removesuffix(b'~>'))
                else:
                    raise AttachmentError('文本流采用暂不支持的压缩格式，未读取此页。')
                if len(payload) > MAX_PDF_PAGE:
                    raise AttachmentError('文本流解压后超过 8 MB，未读取此页。')
        except AttachmentError:
            raise
        except (zlib.error, ValueError, TypeError, binascii.Error):
            raise AttachmentError('文本流压缩数据无效，未读取此页。') from None
        total += len(payload)
        if total > MAX_PDF_PAGE:
            raise AttachmentError('本页文本流合计超过 8 MB，未读取此页。')
    return total


def _parse(meta, data):
    out = _Text()
    ext = meta['ext']
    if meta['kind'] == 'image':
        out.add(f'图片附件：{meta["name"]}（{meta.get("width")} × {meta.get("height")} 像素）。请使用视觉分析；此工具不会将图片伪作已识别文字。')
    elif ext == '.xlsx':
        import openpyxl
        with _zip(data, 'xl/workbook.xml'):
            pass
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
        scanned = 0
        try:
            for sheet in workbook.worksheets:
                if sheet.max_column and sheet.max_column > MAX_COLUMNS:
                    raise AttachmentError('Excel 工作表超过 200 列，请只保留需要分析的列。')
                out.add(f'工作表：{sheet.title}')
                for number, row in enumerate(sheet.iter_rows(max_col=min(sheet.max_column or MAX_COLUMNS, MAX_COLUMNS), values_only=True), 1):
                    scanned += 1
                    if scanned > MAX_ROWS:
                        out.truncated = True
                        out.notes.append('最多扫描 5000 行，后续内容未解析。')
                        break
                    cells = [str(value) if value is not None else '' for value in row]
                    if any(cells):
                        out.add(f'[{sheet.title}] 第 {number} 行\t' + '\t'.join(cells))
                if scanned > MAX_ROWS:
                    break
        finally:
            workbook.close()
        out.notes.append('Excel 公式仅读取文件中保存的结果，不执行公式或宏。')
    elif ext == '.docx':
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        tag = lambda name: '{' + ns['w'] + '}' + name
        def paragraph(element):
            return ''.join((node.text or '') if node.tag == tag('t') else '\t' if node.tag == tag('tab') else '\n' if node.tag in (tag('br'), tag('cr')) else '' for node in element.iter())
        with _zip(data, 'word/document.xml') as archive:
            document = ElementTree.fromstring(archive.read('word/document.xml'))
            body = document.find('w:body', ns)
            table_count = 0
            for block in body if body is not None else []:
                if block.tag == tag('p'):
                    out.add(paragraph(block))
                elif block.tag == tag('tbl'):
                    table_count += 1
                    for number, row in enumerate(block.findall('w:tr', ns), 1):
                        cells = [' / '.join(paragraph(p) for p in cell.iter(tag('p'))) for cell in row.findall('w:tc', ns)]
                        out.add(f'表格 {table_count} 第 {number} 行\t' + '\t'.join(cells))
    elif ext == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError:
            raise AttachmentError('PDF 读取组件尚未安装，请联系管理员或先转换为文字文档。') from None
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(''):
            raise AttachmentError('该 PDF 已加密，请解密后上传。')
        expanded = 0
        for number, page in enumerate(reader.pages, 1):
            if number > 200:
                out.truncated = True
                out.notes.append('最多解析前 200 页。')
                break
            try:
                expanded += _pdf_content_size(page)
                if expanded > MAX_EXPANDED:
                    out.truncated = True
                    out.notes.append('PDF 文本流累计解压超过 40 MB，后续页面未解析。')
                    break
                text = page.extract_text() or ''
            except Exception as exc:
                out.truncated = True
                out.unreadable_pages.append(number)
                out.notes.append(f'第 {number} 页：' + (str(exc) if isinstance(exc, AttachmentError) else '文字读取失败，未读取此页。'))
                continue
            if text.strip():
                out.add(f'第 {number} 页\n{text}')
            else:
                out.truncated = True
                out.unreadable_pages.append(number)
                out.notes.append(f'第 {number} 页无可提取文字，可能是扫描页，未进行 OCR。')
        if not out.total:
            out.add('此 PDF 没有可提取文字，可能是扫描件。当前附件读取不支持扫描件 OCR，请上传清晰图片供视觉分析，或提供可复制文字的 PDF。')
            out.notes.append('扫描件未进行 OCR。')
    elif ext == '.csv':
        for number, row in enumerate(csv.reader(io.StringIO(_decode(data))), 1):
            if number > MAX_ROWS:
                out.truncated = True
                out.notes.append('最多扫描 5000 行，后续内容未解析。')
                break
            if len(row) > MAX_COLUMNS:
                raise AttachmentError('CSV 超过 200 列，请只保留需要分析的列。')
            out.add(f'第 {number} 行\t' + '\t'.join(row))
    else:
        out.add(_decode(data))
    return out.result()


def read_attachment(thread_id, user_id, attachment_id, start=0, limit=READ_LIMIT):
    try:
        start, limit = int(start), int(limit)
        if start < 0 or limit < 1 or limit > READ_LIMIT:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise AttachmentError('读取范围无效：起点须非负，每次最多读取 12000 字。') from None
    meta, data, directory = _content(thread_id, user_id, attachment_id)
    cached = directory / (_uuid(attachment_id).hex + '.parsed.json')
    parsed = None
    try:
        if cached.exists() and not cached.is_symlink() and cached.stat().st_size <= MAX_TEXT * 6 + 32768:
            with _regular_open(cached) as handle:
                candidate = json.load(handle)
            if (candidate.get('version') == PARSE_VERSION and isinstance(candidate.get('text'), str) and
                    len(candidate['text']) <= MAX_TEXT and isinstance(candidate.get('total_chars'), int) and
                    candidate['total_chars'] >= len(candidate['text']) and isinstance(candidate.get('extraction_truncated'), bool)):
                parsed = candidate
    except (ValueError, OSError, TypeError, AttributeError):
        pass
    if parsed is None:
        try:
            parsed = _parse(meta, data)
        except AttachmentError:
            raise
        except Exception:
            logger.exception('Unable to parse a private AI attachment')
            raise AttachmentError('该附件无法读取，请另存为标准文档或文字文件后重试。') from None
        try:
            _atomic_json(cached, parsed)
        except OSError:
            # A cache is optional; a concurrent day-prune must not expose a path.
            logger.info('Private AI attachment parsing cache could not be saved')
    start = min(start, len(parsed['text']))
    text = parsed['text'][start:start + limit]
    end = start + len(text)
    return {'attachment': _public(meta), 'kind': meta['kind'], 'text': text,
            'total_chars': parsed['total_chars'], 'available_chars': len(parsed['text']),
            'start': start, 'end': end, 'truncated': end < parsed['total_chars'] or parsed['extraction_truncated'],
            'extraction_truncated': parsed['extraction_truncated'], 'parser_truncated': parsed['extraction_truncated'],
            'has_unreadable_pages': parsed.get('has_unreadable_pages', False),
            'unreadable_pages': parsed.get('unreadable_pages', []),
            'notes': parsed.get('notes', [])}


def image_attachment(thread_id, user_id, attachment_id):
    meta, data, _ = _content(thread_id, user_id, attachment_id)
    if meta['kind'] != 'image':
        raise AttachmentError('此附件不是图片。')
    _image_info(data)
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(data)) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            if image.mode == 'P' and 'transparency' in image.info:
                image = image.convert('RGBA')
            canvas = Image.new('RGB', image.size, 'white')
            if 'A' in image.getbands():
                canvas.paste(image, mask=image.getchannel('A'))
            else:
                canvas.paste(image.convert('RGB'))
            encoded = None
            for quality in (85, 70, 55):
                buffer = io.BytesIO()
                canvas.save(buffer, format='JPEG', quality=quality, optimize=True)
                if buffer.tell() <= 2 * 1024 * 1024:
                    encoded = buffer.getvalue()
                    break
            if encoded is None:
                raise AttachmentError('图片内容过大，请缩小后上传。', status=413)
            width, height = canvas.size
        return {'attachment': _public(meta), 'mime': 'image/jpeg', 'width': width, 'height': height,
                'data_url': 'data:image/jpeg;base64,' + base64.b64encode(encoded).decode('ascii')}
    except AttachmentError:
        raise
    except Exception:
        raise AttachmentError('图片读取失败，请重新导出后上传。') from None


@require_GET
@never_cache
def download(request, thread_id, attachment_id):
    try:
        if not request.user.is_authenticated:
            raise AttachmentError('请先登录。', status=403)
        _conversation(thread_id, request.user.pk)
        directory = _directory(thread_id)
        if directory is None:
            raise AttachmentError('附件不存在或已清理。', status=404)
        meta, path = _metadata(directory, thread_id, request.user.pk, attachment_id)
        response = FileResponse(_regular_open(path), as_attachment=True, filename=meta['name'], content_type=meta['mime'])
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    except AttachmentError as exc:
        return _error(exc)
    except OSError:
        return _error(AttachmentError('附件不存在或已清理。', status=404))
