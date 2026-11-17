"""Generated Python runs only in a disposable, resource-limited container."""
import hashlib
import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from django.conf import settings

ALLOWED = {'.xlsx', '.xls', '.csv', '.json', '.txt', '.png', '.jpg', '.pdf'}
MAX_FILE = 20 * 1024 * 1024

# Runs inside the container. /input is read-only; /work and /tmp are bounded
# tmpfs mounts. Only this small JSON envelope leaves the container.
BOOTSTRAP = r'''
import base64, hashlib, json, os, pathlib, resource, shutil, signal, subprocess, sys, tempfile
root = pathlib.Path('/work')
for p in pathlib.Path('/input').iterdir():
    if p.is_file() and not p.is_symlink(): shutil.copyfile(p, root / p.name)
before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
resource.setrlimit(resource.RLIMIT_FSIZE, (33554432, 33554432))
with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
    p = subprocess.Popen([sys.executable, '-I', '-c', CODE], stdout=out, stderr=err, start_new_session=True)
    try: p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL); p.wait()
    out.seek(0); err.seek(0)
    result = {'exit_code': p.returncode, 'stdout': out.read(4000).decode('utf8', 'replace'), 'stderr': err.read(2000).decode('utf8', 'replace'), 'files': []}
    total = 0
    for p in sorted(root.iterdir()):
        if p.is_symlink() or not p.is_file() or p.name.startswith('.') or p.suffix.lower() not in ALLOWED: continue
        size = p.stat().st_size
        if size > 20971520 or total + size > 20971520 or len(result['files']) >= 20: continue
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() == before.get(p.name): continue
        total += size
        result['files'].append({'name': p.name, 'data': base64.b64encode(data).decode('ascii')})
    print(json.dumps(result))
'''


def execute(code, workspace, cancel=None):
    binary = getattr(settings, 'AI_EXECUTOR_BINARY', 'docker')
    image = getattr(settings, 'AI_EXECUTOR_IMAGE', '')
    if not image:
        return {'error': '数据计算执行器尚未启用；查询和报表导出仍可使用，请联系管理员完成配置。'}
    if not isinstance(code, str) or len(code) > 100000:
        return {'error': '分析代码为空或过长'}
    cancel = cancel or threading.Event()
    if cancel.is_set():
        return {'error': '任务已停止'}
    name = 'irrigation-analysis-' + uuid.uuid4().hex
    root = Path(workspace).resolve()
    with tempfile.TemporaryDirectory(prefix='analysis-') as temporary:
        staged = Path(temporary)
        # Copy only explicit tabular inputs; never mount an app/private parent,
        # a Docker socket, credentials, or symlinks from a previous run.
        for path in root.iterdir():
            if not path.is_symlink() and path.is_file() and path.suffix.lower() in {'.csv', '.xlsx', '.json'} and path.stat().st_size <= MAX_FILE:
                shutil.copyfile(path, staged / path.name)
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in staged.iterdir()}
        os.chmod(staged, 0o755)
        for p in staged.iterdir():
            os.chmod(p, 0o644)
        command = [binary, 'run', '--rm', '--name', name, '--pull=never', '--network=none',
            '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64',
            '--memory=512m', '--memory-swap=512m', '--cpus=1', '--user=65534:65534',
            '--tmpfs=/tmp:rw,noexec,nosuid,size=64m', '--tmpfs=/work:rw,noexec,nosuid,size=128m,mode=1777',
            '--mount', f'type=bind,src={staged.resolve()},dst=/input,readonly', '--workdir=/work',
            '--env', 'HOME=/tmp', '--env', 'MPLBACKEND=Agg', '--env', 'OPENBLAS_NUM_THREADS=1',
            image, 'python', '-I', '-c', 'CODE=' + repr(code) + '\nALLOWED=' + repr(ALLOWED) + '\n' + BOOTSTRAP]
        # Output goes to capped files (RLIMIT_FSIZE) rather than accumulating
        # unlimited PIPE output in a web worker's memory.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                proc = subprocess.Popen(command, stdout=out, stderr=err)
                deadline = time.monotonic() + 35
                while proc.poll() is None and time.monotonic() < deadline and not cancel.wait(0.15):
                    if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > 32 * 1024 * 1024:
                        break
                if proc.poll() is None:
                    subprocess.run([binary, 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    proc.kill(); proc.wait(timeout=5)
                    return {'error': '任务已停止' if cancel.is_set() else '分析超出执行时间或输出限制'}
                out.seek(0); err.seek(0)
                payload = out.read(32 * 1024 * 1024 + 1)
                if len(payload) > 32 * 1024 * 1024:
                    return {'error': '分析输出超出限制'}
                if proc.returncode != 0:
                    return {'error': '数据计算执行失败或达到资源限制，请缩小分析范围后重试。'}
                result = json.loads(payload)
            except (OSError, subprocess.SubprocessError, ValueError):
                return {'error': '数据计算执行器不可用，请稍后重试或联系管理员。'}
            finally:
                # Remove any still-running container after a client disconnect,
                # daemon failure, unexpected exception, or process timeout.
                try:
                    subprocess.run([binary, 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                except (OSError, subprocess.SubprocessError):
                    pass
        used = 0
        if not isinstance(result, dict) or not isinstance(result.get('files', []), list):
            return {'error': '执行器返回格式无效'}
        accepted = []
        for info in result.get('files', [])[:20]:
            if not isinstance(info, dict):
                continue
            name = info.get('name', '')
            if (not isinstance(name, str) or not name or Path(name).name != name or '/' in name or '\\' in name
                    or Path(name).suffix.lower() not in ALLOWED or name.startswith('.')):
                continue
            try:
                data = base64.b64decode(info.get('data', ''), validate=True)
            except (ValueError, TypeError):
                continue
            size = len(data)
            used += size
            if size > MAX_FILE or used > MAX_FILE:
                continue
            digest = hashlib.sha256(data).hexdigest()
            if before.get(name) == digest:
                continue
            destination = root / name
            if destination.is_symlink():
                continue
            destination.write_bytes(data)
            accepted.append({'name': name, 'size': size})
        result['files'] = accepted
        result['stdout'] = str(result.get('stdout', ''))[:4000]
        result['stderr'] = str(result.get('stderr', ''))[:2000]
        result['generated_count'] = len(accepted)
        return result
