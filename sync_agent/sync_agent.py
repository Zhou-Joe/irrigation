"""
Maxicom2 Sync Agent — PyQt5 GUI Application
Reads Maxicom2.mdb via DAO and syncs to Django server via HTTP API.

Rebuilt workflow:
    • Import the latest 7 / 15 / 30 days of Maxicom data (user-selectable),
      anchored to "now" so it stays current as Maxicom keeps writing the MDB.
    • Filter repetitive rows: client-side watermark (with a 2-min overlap buffer)
      plus the server's per-row get_or_create dedup — re-syncs are idempotent.
    • Non-freezing GUI with a progress bar and a clear import summary
      (per-table counts + date range actually sent).

Usage:
    python sync_agent.py                  # GUI mode
    python sync_agent.py --once           # Single sync, no GUI (uses --days)
    python sync_agent.py --once --days 7

Build EXE:
    pip install pyinstaller
    pyinstaller --onefile --windowed --name MaxicomSync sync_agent.py
"""

import sys
import os
import json
import time
from datetime import datetime, timedelta

# ─── Configuration ────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "server_url": "http://127.0.0.1:8000",
    "api_key": "dev-sync-key-change-in-production",
    "mdb_path": r"C:\Users\czhou7\PythonProjects\irrigation\Database\Maxicom2.mdb",
    "mdb_password": "RLM6808",
    "sync_interval_minutes": 5,
    "overlap_buffer_minutes": 2,
    "days_window": 7,
}

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "sync_config.json")
LAST_SYNC_FILE = os.path.join(APP_DIR, "last_sync.json")

# The six time-series tables the agent imports. Each entry is
# (payload_key, mdb_table, timestamp_column). Note XA_RuntimeProject uses
# TimeStamps (plural); the other five use XactStamp. This mirrors both the
# legacy agent and the import_maxicom_mdb management command.
TIME_SERIES_TABLES = [
    ("weather_logs", "XA_WETHR", "XactStamp"),
    ("events", "XA_EVENT", "XactStamp"),
    ("et_checkbook", "XA_ETCheckBook", "XactStamp"),
    ("runtime", "XA_RuntimeProject", "TimeStamps"),
    ("signal_logs", "XA_LOG", "XactStamp"),
    ("flow_readings", "XA_FLOZO", "XactStamp"),
]


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = v
        return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)


def load_last_sync():
    if os.path.exists(LAST_SYNC_FILE):
        with open(LAST_SYNC_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_last_sync(data):
    with open(LAST_SYNC_FILE, 'w') as f:
        json.dump(data, f, indent=2)


# ─── Timestamp helpers ────────────────────────────────────────────────

def _subtract_minutes(timestamp_str, minutes):
    """Subtract minutes from a YYYYMMDDHHmmSS timestamp string."""
    if not timestamp_str or len(timestamp_str) < 14:
        return "0"
    try:
        ts = datetime.strptime(timestamp_str[:14], "%Y%m%d%H%M%S")
        ts = ts - timedelta(minutes=minutes)
        return ts.strftime("%Y%m%d%H%M%S")
    except (ValueError, TypeError):
        return "0"


def _days_ago_timestamp(days):
    """Timestamp string for N days ago (the window's `since` bound, anchored now)."""
    ts = datetime.now() - timedelta(days=days)
    return ts.strftime("%Y%m%d%H%M%S")


def _format_ts(ts_str):
    """Pretty-print a YYYYMMDDHHmmSS stamp as YYYY-MM-DD HH:MM:SS."""
    if not ts_str or ts_str == "0" or len(ts_str) < 14:
        return ""
    try:
        return datetime.strptime(ts_str[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ts_str


def _format_date(ts_str):
    """Pretty-print a YYYYMMDDHHmmSS stamp as YYYY-MM-DD."""
    if not ts_str or len(ts_str) < 8:
        return ""
    try:
        return datetime.strptime(ts_str[:8], "%Y%m%d").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ts_str


# ─── MDB Reader (generator with progress) ────────────────────────────

def _row_from_recordset(rs):
    """Read one row from a DAO recordset into a plain dict."""
    row = {}
    for i in range(rs.Fields.Count):
        field = rs.Fields.Item(i)
        val = field.Value
        if val is None:
            row[field.Name] = None
        elif isinstance(val, (int, float, str, bool)):
            row[field.Name] = val
        else:
            row[field.Name] = str(val)
    return row


def _read_table_windowed(db, table_name, ts_column, since_ts):
    """Read rows where timestamp > since_ts (server-side filtered on the MDB).

    Server-side filtering is essential for XA_FLOZO (~4M rows): pulling the
    whole table would freeze the agent. The 14-digit fixed-width timestamp
    string sorts lexicographically == chronologically, so a string `>` works.
    Falls back to a full table read only if the filtered query itself errors.
    """
    if not since_ts or since_ts == "0":
        sql = f"SELECT * FROM [{table_name}]"
    else:
        sql = f"SELECT * FROM [{table_name}] WHERE [{ts_column}] > '{since_ts}'"
    rs = db.OpenRecordset(sql)
    rows = []
    try:
        while not rs.EOF:
            rows.append(_row_from_recordset(rs))
            rs.MoveNext()
    finally:
        rs.Close()
    return rows


def read_mdb_with_progress(cfg, days, last_sync, progress_cb=None, log_cb=None):
    """Read the latest `days` of Maxicom data, yielding progress as it goes.

    `progress_cb(percent, message)` and `log_cb(message)` are optional callbacks
    (the GUI wires these to the progress bar and log). Returns
    (time_series, sent_range, new_sync) where sent_range is (min_ts, max_ts)
    over all rows actually selected (for the summary), or (None, None) if empty.

    Config tables are deliberately NOT re-sent (already loaded once via the
    import_maxicom command); the payload's `config` stays empty.
    """
    mdb_path = cfg["mdb_path"]
    if not os.path.exists(mdb_path):
        raise FileNotFoundError(f"MDB file not found: {mdb_path}")

    overlap = cfg.get("overlap_buffer_minutes", 2)
    # The window's lower bound is anchored to NOW (real-time). The agent is
    # meant to run regularly while Maxicom actively updates the MDB.
    window_since = _days_ago_timestamp(days)

    import win32com.client
    if log_cb:
        log_cb(f"打开 MDB: {os.path.basename(mdb_path)}")
    if progress_cb:
        progress_cb(3, "正在打开数据库…")
    db_engine = win32com.client.Dispatch("DAO.DBEngine.120")
    db = db_engine.OpenDatabase(mdb_path, False, True, ";pwd=" + cfg["mdb_password"])

    # watermark key per payload table
    wm_keys = {
        "weather_logs": "last_weather_timestamp",
        "events": "last_event_timestamp",
        "et_checkbook": "last_etcheckbook_timestamp",
        "runtime": "last_runtime_timestamp",
        "signal_logs": "last_signal_timestamp",
        "flow_readings": "last_flow_timestamp",
    }

    time_series = {}
    all_ts = []                 # collect every selected timestamp for the range
    new_sync = dict(last_sync)

    try:
        n_tables = len(TIME_SERIES_TABLES)
        # Phase 2: read each table. Reading occupies the bulk of wall-clock
        # time, so map each completed table to a slice of 5%→55%.
        for i, (key, table, ts_col) in enumerate(TIME_SERIES_TABLES):
            if progress_cb:
                progress_cb(5 + int(50 * i / n_tables), f"读取 {table} …")
            if log_cb:
                log_cb(f"读取 {table}（窗口 ≥ {_format_ts(window_since)}）…")

            # Use the later of (window start) and (watermark − overlap buffer).
            # The watermark path only narrows the window further on re-syncs,
            # never widens it past the user's day selection.
            wm = last_sync.get(wm_keys[key], "0")
            overlap_ts = _subtract_minutes(wm, overlap) if wm and wm != "0" else "0"
            # The user asked for "latest N days", so the window start always wins
            # when the watermark is older than it. Take the MAX (most recent).
            if overlap_ts and overlap_ts != "0" and overlap_ts > window_since:
                since_ts = overlap_ts
            else:
                since_ts = window_since

            rows = _read_table_windowed(db, table, ts_col, since_ts)

            # Client-side re-filter: drop any rows <= watermark (overlap dedup).
            if wm and wm != "0":
                rows = [r for r in rows if (r.get(ts_col) or "0") > wm]

            time_series[key] = rows
            for r in rows:
                t = r.get(ts_col)
                if t:
                    all_ts.append(str(t))

            # Advance the watermark to the max timestamp seen in this batch.
            if rows:
                max_ts = max(str(r.get(ts_col) or "0") for r in rows)
                if max_ts > new_sync.get(wm_keys[key], "0"):
                    new_sync[wm_keys[key]] = max_ts

            if log_cb:
                log_cb(f"  {table}: {len(rows):,} 行")
            if progress_cb:
                progress_cb(5 + int(50 * (i + 1) / n_tables), f"{table}: {len(rows):,} 行")
    finally:
        db.Close()

    sent_range = (min(all_ts), max(all_ts)) if all_ts else (None, None)
    return time_series, sent_range, new_sync


# ─── Sync Worker ──────────────────────────────────────────────────────

def do_sync(cfg, days, last_sync, progress_cb=None, log_cb=None):
    """Perform one windowed sync cycle.

    Returns (success, message, new_sync, summary) where summary is a dict with
    per-table results, the sent date range, and totals — ready for the UI.
    """
    import urllib.request
    import urllib.error

    try:
        time_series, sent_range, new_sync = read_mdb_with_progress(
            cfg, days, last_sync, progress_cb=progress_cb, log_cb=log_cb,
        )
    except FileNotFoundError as e:
        return False, f"MDB 未找到: {e}", last_sync, {}
    except Exception as e:
        return False, f"MDB 读取错误: {e}", last_sync, {}

    total = sum(len(v) for v in time_series.values())
    min_ts, max_ts = sent_range

    if total == 0:
        if progress_cb:
            progress_cb(100, "完成（窗口内无新数据）")
        summary = {
            'total': 0, 'inserted': 0, 'skipped': 0,
            'date_from': None, 'date_to': None,
            'window_days': days,
            'tables': {key: {'sent': 0, 'inserted': 0, 'skipped': 0}
                       for key, _, _ in TIME_SERIES_TABLES},
        }
        return True, f"窗口内无新数据（最近 {days} 天）", last_sync, summary

    payload = {
        "sync_timestamp": datetime.now().strftime("%Y%m%d%H%M%S"),
        "agent_version": "2.0",
        "config": {},                 # config tables already imported via management command
        "time_series": time_series,
    }

    url = cfg["server_url"].rstrip("/") + "/api/sync/receive"
    headers = {
        "Content-Type": "application/json",
        "X-Sync-Key": cfg["api_key"],
    }

    if progress_cb:
        progress_cb(60, f"上传 {total:,} 行到服务器…")
    if log_cb:
        log_cb(f"发送 {total:,} 行到 {url} …")

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return False, f"服务器错误 {e.code}: {body}", last_sync, {}
    except urllib.error.URLError as e:
        return False, f"连接失败: {e.reason}", last_sync, {}
    except Exception as e:
        return False, f"网络错误: {e}", last_sync, {}

    if progress_cb:
        progress_cb(92, "解析服务器结果…")

    # Server returns results: {table: {inserted, skipped}} for time-series.
    srv_results = result.get("results", {}) if result.get("status") == "ok" else {}

    # Build the summary the UI displays.
    tables_summary = {}
    inserted_total = 0
    skipped_total = 0
    for key, table, _ in TIME_SERIES_TABLES:
        sent = len(time_series.get(key, []))
        info = srv_results.get(key, {}) or {}
        ins = int(info.get('inserted', 0) or 0)
        skp = int(info.get('skipped', 0) or 0)
        # Some servers return {'created':..} for config; time-series use inserted/skipped.
        if 'inserted' not in info and 'skipped' not in info and sent:
            ins = sent
        inserted_total += ins
        skipped_total += skp
        tables_summary[key] = {'sent': sent, 'inserted': ins, 'skipped': skp, 'table': table}

    summary = {
        'total': total,
        'inserted': inserted_total,
        'skipped': skipped_total,
        'date_from': min_ts,
        'date_to': max_ts,
        'window_days': days,
        'tables': tables_summary,
    }

    if progress_cb:
        progress_cb(100, "完成")
    if result.get("status") == "ok":
        return True, f"同步完成：{inserted_total:,} 新增 · {skipped_total:,} 跳过", new_sync, summary
    else:
        return False, f"服务器返回: {result}", last_sync, summary


# ─── CLI Mode ─────────────────────────────────────────────────────────

def run_cli(days=None):
    cfg = load_config()
    if days is None:
        days = cfg.get("days_window", 7)
    last_sync = load_last_sync()
    print(f"MDB:     {cfg['mdb_path']}")
    print(f"Server:  {cfg['server_url']}")
    print(f"Window:  最近 {days} 天\n")

    def p(pct, msg):
        print(f"  [{pct:>3}%] {msg}")

    success, message, new_sync, summary = do_sync(
        cfg, days, last_sync, progress_cb=p, log_cb=lambda m: print("  " + m),
    )
    print(f"\n{'=' * 56}")
    if success:
        print(f"✓ {message}")
        if new_sync != last_sync and summary.get('total', 0) > 0:
            save_last_sync(new_sync)
        if summary:
            print(_format_summary(summary))
    else:
        print(f"✗ {message}")
    sys.exit(0 if success else 1)


def _format_summary(s):
    """Render the summary dict as a multi-line text block (CLI + GUI log)."""
    lines = []
    if s.get('date_from') and s.get('date_to'):
        lines.append(f"日期范围: {_format_date(s['date_from'])} — {_format_date(s['date_to'])}  "
                     f"(最近 {s.get('window_days', '?')} 天)")
    else:
        lines.append(f"日期范围: (无数据)  (最近 {s.get('window_days', '?')} 天)")
    lines.append(f"总计: {s.get('total', 0):,} 行 · 新增 {s.get('inserted', 0):,} · 重复跳过 {s.get('skipped', 0):,}")
    lines.append("")
    lines.append(f"{'表':<22}{'发送':>10}{'新增':>10}{'跳过':>10}")
    lines.append("-" * 52)
    for key, _, _ in TIME_SERIES_TABLES:
        t = s.get('tables', {}).get(key, {})
        lines.append(f"{t.get('table', key):<22}{t.get('sent', 0):>10,}{t.get('inserted', 0):>10,}{t.get('skipped', 0):>10,}")
    return "\n".join(lines)


# ─── PyQt5 GUI ────────────────────────────────────────────────────────

def run_gui():
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QTextEdit, QDialog, QFormLayout, QLineEdit,
        QSpinBox, QFileDialog, QSystemTrayIcon, QMenu, QGroupBox,
        QProgressBar, QComboBox,
    )
    from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
    from PyQt5.QtGui import QIcon, QColor, QTextCursor, QPixmap, QPainter

    DARK_STYLE = """
    QMainWindow { background-color: #1e1e2e; }
    QWidget { background-color: #1e1e2e; color: #cdd6f4; font-family: "Segoe UI", sans-serif; }
    QGroupBox {
        border: 1px solid #45475a; border-radius: 8px; margin-top: 12px; padding-top: 16px;
        font-weight: bold; font-size: 13px;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
    QLabel { font-size: 13px; }
    QPushButton {
        background-color: #313244; border: 1px solid #45475a; border-radius: 6px;
        padding: 8px 20px; font-size: 13px; font-weight: bold; color: #cdd6f4;
    }
    QPushButton:hover { background-color: #45475a; }
    QPushButton:pressed { background-color: #585b70; }
    QPushButton#syncBtn { background-color: #a6e3a1; color: #1e1e2e; }
    QPushButton#syncBtn:hover { background-color: #94e2d5; }
    QPushButton#syncBtn:disabled { background-color: #45475a; color: #6c7086; }
    QPushButton#settingsBtn { background-color: #89b4fa; color: #1e1e2e; }
    QTextEdit {
        background-color: #11111b; border: 1px solid #45475a; border-radius: 6px;
        font-family: "Consolas", monospace; font-size: 12px; color: #a6adc8; padding: 4px;
    }
    QLineEdit, QSpinBox, QComboBox {
        background-color: #313244; border: 1px solid #45475a; border-radius: 4px;
        padding: 6px; color: #cdd6f4; font-size: 13px;
    }
    QComboBox QAbstractItemView { background-color: #313244; color: #cdd6f4; selection-background-color: #45475a; }
    QProgressBar {
        background-color: #313244; border: 1px solid #45475a; border-radius: 6px;
        text-align: center; color: #cdd6f4; font-size: 12px; height: 18px;
    }
    QProgressBar::chunk { background-color: #a6e3a1; border-radius: 5px; }
    QDialog { background-color: #1e1e2e; }
    """

    class SyncThread(QThread):
        log_signal = pyqtSignal(str, str)
        progress_signal = pyqtSignal(int, str)
        summary_signal = pyqtSignal(dict)
        finished_signal = pyqtSignal(bool, str)

        def __init__(self, cfg, days):
            super().__init__()
            self.cfg = cfg
            self.days = days

        def run(self):
            last_sync = load_last_sync()
            success, message, new_sync, summary = do_sync(
                self.cfg, self.days, last_sync,
                progress_cb=lambda pct, msg: self.progress_signal.emit(pct, msg),
                log_cb=lambda m: self.log_signal.emit(m, "info"),
            )
            if success and new_sync != last_sync and summary.get('total', 0) > 0:
                save_last_sync(new_sync)
            self.log_signal.emit(message, "success" if success else "error")
            if summary:
                self.summary_signal.emit(summary)
            self.finished_signal.emit(success, message)

    class SettingsDialog(QDialog):
        def __init__(self, cfg, parent=None):
            super().__init__(parent)
            self.setWindowTitle("设置")
            self.setMinimumWidth(450)
            layout = QFormLayout(self)
            layout.setSpacing(12)

            self.server_edit = QLineEdit(cfg["server_url"])
            layout.addRow("服务器地址:", self.server_edit)
            self.key_edit = QLineEdit(cfg["api_key"])
            self.key_edit.setEchoMode(QLineEdit.Password)
            layout.addRow("API Key:", self.key_edit)
            self.mdb_edit = QLineEdit(cfg["mdb_path"])
            mdb_btn = QPushButton("浏览…")
            mdb_btn.clicked.connect(self._browse_mdb)
            mdb_row = QHBoxLayout()
            mdb_row.addWidget(self.mdb_edit)
            mdb_row.addWidget(mdb_btn)
            layout.addRow("MDB 路径:", mdb_row)
            self.pwd_edit = QLineEdit(cfg["mdb_password"])
            layout.addRow("MDB 密码:", self.pwd_edit)
            self.interval_spin = QSpinBox()
            self.interval_spin.setRange(1, 1440)
            self.interval_spin.setValue(cfg.get("sync_interval_minutes", 5))
            layout.addRow("自动同步间隔 (分钟):", self.interval_spin)
            self.days_spin = QSpinBox()
            self.days_spin.setRange(1, 365)
            self.days_spin.setValue(cfg.get("days_window", 7))
            layout.addRow("默认导入天数:", self.days_spin)
            btn_layout = QHBoxLayout()
            save_btn = QPushButton("保存")
            save_btn.clicked.connect(self.accept)
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(self.reject)
            btn_layout.addWidget(save_btn)
            btn_layout.addWidget(cancel_btn)
            layout.addRow(btn_layout)

        def _browse_mdb(self):
            path, _ = QFileDialog.getOpenFileName(self, "选择 MDB 文件", "", "Access DB (*.mdb)")
            if path:
                self.mdb_edit.setText(path)

        def get_config(self):
            return {
                "server_url": self.server_edit.text().strip(),
                "api_key": self.key_edit.text(),
                "mdb_path": self.mdb_edit.text(),
                "mdb_password": self.pwd_edit.text(),
                "sync_interval_minutes": self.interval_spin.value(),
                "overlap_buffer_minutes": 2,
                "days_window": self.days_spin.value(),
            }

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.cfg = load_config()
            self.sync_thread = None
            self.setWindowTitle("Maxicom2 同步助手")
            self.setMinimumSize(560, 680)
            self.resize(600, 720)

            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)
            layout.setSpacing(10)
            layout.setContentsMargins(16, 16, 16, 16)

            # ── Status group ──
            status_group = QGroupBox("连接状态")
            status_layout = QVBoxLayout(status_group)
            self.status_label = QLabel("● 未连接")
            self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #f38ba8;")
            status_layout.addWidget(self.status_label)
            self.server_label = QLabel(f"服务器: {self.cfg['server_url']}")
            status_layout.addWidget(self.server_label)
            self.last_sync_label = QLabel("上次同步: 从未")
            status_layout.addWidget(self.last_sync_label)
            self.next_sync_label = QLabel(f"下次自动同步: 每 {self.cfg['sync_interval_minutes']} 分钟")
            status_layout.addWidget(self.next_sync_label)
            layout.addWidget(status_group)

            # ── Sync controls: day window + progress bar ──
            ctrl_group = QGroupBox("同步")
            ctrl_layout = QVBoxLayout(ctrl_group)
            row = QHBoxLayout()
            row.addWidget(QLabel("导入范围:"))
            self.window_combo = QComboBox()
            self.window_combo.addItems(["最近 7 天", "最近 15 天", "最近 30 天"])
            default_days = self.cfg.get("days_window", 7)
            idx = {7: 0, 15: 1, 30: 2}.get(default_days, 0)
            self.window_combo.setCurrentIndex(idx)
            self.window_combo.currentIndexChanged.connect(self._on_window_changed)
            row.addWidget(self.window_combo, stretch=1)
            self.sync_btn = QPushButton("▶  立即同步")
            self.sync_btn.setObjectName("syncBtn")
            self.sync_btn.clicked.connect(self.manual_sync)
            row.addWidget(self.sync_btn)
            self.settings_btn = QPushButton("⚙  设置")
            self.settings_btn.setObjectName("settingsBtn")
            self.settings_btn.clicked.connect(self.open_settings)
            row.addWidget(self.settings_btn)
            ctrl_layout.addLayout(row)

            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setVisible(False)
            ctrl_layout.addWidget(self.progress)
            layout.addWidget(ctrl_group)

            # ── Summary group ──
            self.summary_group = QGroupBox("导入结果")
            sl = QVBoxLayout(self.summary_group)
            self.summary_label = QLabel("尚未同步。")
            self.summary_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 12px; color: #a6adc8;")
            self.summary_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            self.summary_label.setWordWrap(True)
            sl.addWidget(self.summary_label)
            self.summary_group.setVisible(False)
            layout.addWidget(self.summary_group)

            # ── Log group ──
            log_group = QGroupBox("日志")
            log_layout = QVBoxLayout(log_group)
            self.log_text = QTextEdit()
            self.log_text.setReadOnly(True)
            log_layout.addWidget(self.log_text)
            layout.addWidget(log_group, stretch=1)

            # ── Timers ──
            interval_ms = self.cfg.get("sync_interval_minutes", 5) * 60 * 1000
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.auto_sync)
            self.timer.start(interval_ms)

            self.conn_timer = QTimer(self)
            self.conn_timer.timeout.connect(lambda: self._check_connection(silent=True))
            self.conn_timer.start(30000)

            self._setup_tray()
            self._check_connection()
            self._log("同步助手已启动", "info")
            self._log(f"导入范围: 最近 {self._current_days()} 天 · 自动同步每 {self.cfg['sync_interval_minutes']} 分钟", "info")

        def _current_days(self):
            return {0: 7, 1: 15, 2: 30}.get(self.window_combo.currentIndex(), 7)

        def _on_window_changed(self, _idx):
            days = self._current_days()
            self.cfg["days_window"] = days
            save_config(self.cfg)
            self._log(f"导入范围已切换为最近 {days} 天", "info")

        def _setup_tray(self):
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor("#a6e3a1"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(2, 2, 28, 28)
            painter.end()
            icon = QIcon(pixmap)
            self.tray_icon = QSystemTrayIcon(icon, self)
            tray_menu = QMenu()
            tray_menu.addAction("显示").triggered.connect(self.showNormal)
            tray_menu.addAction("立即同步").triggered.connect(self.manual_sync)
            tray_menu.addAction("退出").triggered.connect(self._quit)
            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.activated.connect(self._tray_activated)
            self.tray_icon.setToolTip("Maxicom2 同步助手")
            self.tray_icon.show()

        def _tray_activated(self, reason):
            if reason == QSystemTrayIcon.DoubleClick:
                self.showNormal()

        def changeEvent(self, event):
            if event.type() == event.WindowStateChange and self.windowState() & Qt.WindowMinimized:
                QTimer.singleShot(0, self.hide)
                self.tray_icon.showMessage("Maxicom2 同步助手", "正在后台运行。", QSystemTrayIcon.Information, 2000)
            super().changeEvent(event)

        def closeEvent(self, event):
            event.ignore()
            self.hide()
            self.tray_icon.showMessage("Maxicom2 同步助手", "已最小化到托盘，右键退出。", QSystemTrayIcon.Information, 3000)

        def _quit(self):
            self.tray_icon.hide()
            QApplication.quit()

        def _log(self, message, level="info"):
            ts = datetime.now().strftime("%H:%M:%S")
            colors = {"info": "#a6adc8", "success": "#a6e3a1", "warning": "#f9e2af", "error": "#f38ba8"}
            icons = {"info": "ℹ", "success": "✓", "warning": "⚠", "error": "✗"}
            color = colors.get(level, "#a6adc8")
            icon = icons.get(level, " ")
            self.log_text.append(f'<span style="color:#585b70">{ts}</span> <span style="color:{color}">{icon} {message}</span>')
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.log_text.setTextCursor(cursor)

        def _check_connection(self, silent=False):
            import urllib.request
            url = self.cfg["server_url"].rstrip("/") + "/api/sync/status"
            req = urllib.request.Request(url, headers={"X-Sync-Key": self.cfg["api_key"]})
            old_status = self.status_label.text()
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.status_label.setText("● 已连接")
                    self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #a6e3a1;")
                    total = sum(data.get("counts", {}).values())
                    self.server_label.setText(f"服务器: {self.cfg['server_url']} ({total:,} 条记录)")
                    if not silent or "未连接" in old_status or "错误" in old_status:
                        self._log(f"已连接服务器 — 共 {total:,} 条记录", "info")
            except Exception:
                self.status_label.setText("● 未连接")
                self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #f38ba8;")
                self.server_label.setText(f"服务器: {self.cfg['server_url']} (离线)")
                if not silent or "已连接" in old_status:
                    self._log("服务器未连接", "error")

        def _set_syncing(self, syncing):
            self.sync_btn.setEnabled(not syncing)
            self.sync_btn.setText("同步中…" if syncing else "▶  立即同步")
            self.progress.setVisible(syncing)
            if syncing:
                self.progress.setValue(0)

        def _on_progress(self, pct, msg):
            self.progress.setValue(pct)
            self.progress.setFormat(f"{pct}%  {msg}")

        def _on_summary(self, summary):
            self.summary_group.setVisible(True)
            self.summary_label.setText(_format_summary(summary))

        def manual_sync(self):
            self._do_sync()

        def auto_sync(self):
            self._log("触发自动同步", "info")
            self._do_sync()

        def _do_sync(self):
            if self.sync_thread and self.sync_thread.isRunning():
                return
            self._set_syncing(True)
            days = self._current_days()
            self._log(f"开始同步（最近 {days} 天）…", "info")
            self.sync_thread = SyncThread(self.cfg, days)
            self.sync_thread.log_signal.connect(self._log)
            self.sync_thread.progress_signal.connect(self._on_progress)
            self.sync_thread.summary_signal.connect(self._on_summary)
            self.sync_thread.finished_signal.connect(self._on_sync_done)
            self.sync_thread.start()

        def _on_sync_done(self, success, message):
            self._set_syncing(False)
            if success:
                last_sync = load_last_sync()
                latest = max((v for v in last_sync.values() if v and v != "0"), default="")
                self.last_sync_label.setText(f"上次同步: {_format_ts(latest) or '刚刚'}  ✓")
                self.status_label.setText("● 已连接")
                self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #a6e3a1;")
                self.progress.setFormat("完成")
            else:
                self.last_sync_label.setText("上次同步: 失败  ✗")
                self.status_label.setText("● 错误")
                self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #f38ba8;")
                self.tray_icon.showMessage("同步错误", message[:100], QSystemTrayIcon.Critical, 5000)

        def open_settings(self):
            dlg = SettingsDialog(self.cfg, self)
            if dlg.exec_() == QDialog.Accepted:
                self.cfg = dlg.get_config()
                save_config(self.cfg)
                self.timer.setInterval(self.cfg["sync_interval_minutes"] * 60 * 1000)
                self.next_sync_label.setText(f"下次自动同步: 每 {self.cfg['sync_interval_minutes']} 分钟")
                idx = {7: 0, 15: 1, 30: 2}.get(self.cfg.get("days_window", 7), 0)
                self.window_combo.setCurrentIndex(idx)
                self._log("设置已保存", "success")
                self._check_connection()

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--once" in args:
        days = None
        if "--days" in args:
            i = args.index("--days")
            if i + 1 < len(args):
                try:
                    days = int(args[i + 1])
                except ValueError:
                    pass
        run_cli(days)
    else:
        run_gui()
