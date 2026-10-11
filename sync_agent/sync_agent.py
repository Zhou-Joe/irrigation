"""
Maxicom2 Sync Agent — PyQt5 GUI Application
Reads Maxicom2.mdb via DAO and syncs to Django server via HTTP API.

Usage:
    python sync_agent.py                  # GUI mode
    python sync_agent.py --once           # Single sync, no GUI (for testing)
    
Build EXE:
    pip install pyinstaller
    pyinstaller --onefile --windowed --name MaxicomSync sync_agent.py
"""

import sys
import os
import json
from datetime import datetime, timedelta

# ─── Configuration ────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "server_url": "http://localhost:8888",
    "api_key": "dev-sync-key-change-in-production",
    "mdb_path": r"C:\Users\czhou7\PythonProjects\irrigation\Database\Maxicom2.mdb",
    "mdb_password": "RLM6808",
    "sync_interval_minutes": 5,
    "overlap_buffer_minutes": 2,
}

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "sync_config.json")
LAST_SYNC_FILE = os.path.join(APP_DIR, "last_sync.json")


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


# ─── MDB Reader ───────────────────────────────────────────────────────

def read_mdb_data(cfg, last_sync):
    """Read data from Maxicom2.mdb via DAO, return dict of records."""
    mdb_path = cfg["mdb_path"]
    mdb_pwd = cfg["mdb_password"]
    overlap = cfg.get("overlap_buffer_minutes", 2)

    if not os.path.exists(mdb_path):
        raise FileNotFoundError(f"MDB file not found: {mdb_path}")

    import win32com.client
    db_engine = win32com.client.Dispatch("DAO.DBEngine.120")
    db = db_engine.OpenDatabase(mdb_path, False, True, ";pwd=" + mdb_pwd)

    try:
        # Skip config tables — already loaded via import_maxicom command.
        # Only send config on explicit first sync (empty dict = no update).
        config = {}

        first_sync = _is_first_sync(last_sync)
        if first_sync:
            recent_ts = _hours_ago_timestamp(24)
        else:
            recent_ts = None

        time_series = {}
        ts = last_sync.get("last_weather_timestamp", "0") if not first_sync else recent_ts
        overlap_ts = _subtract_minutes(ts, overlap) if ts and ts != "0" else recent_ts
        time_series["weather_logs"] = _read_table_filtered(db, "XA_WETHR", "XactStamp", overlap_ts)
        ts = last_sync.get("last_event_timestamp", "0") if not first_sync else recent_ts
        overlap_ts = _subtract_minutes(ts, overlap) if ts and ts != "0" else recent_ts
        time_series["events"] = _read_table_filtered(db, "XA_EVENT", "XactStamp", overlap_ts)
        ts = last_sync.get("last_etcheckbook_timestamp", "0") if not first_sync else recent_ts
        overlap_ts = _subtract_minutes(ts, overlap) if ts and ts != "0" else recent_ts
        time_series["et_checkbook"] = _read_table_filtered(db, "XA_ETCheckBook", "XactStamp", overlap_ts)
        ts = last_sync.get("last_runtime_timestamp", "0") if not first_sync else recent_ts
        overlap_ts = _subtract_minutes(ts, overlap) if ts and ts != "0" else recent_ts
        time_series["runtime"] = _read_table_filtered(db, "XA_RuntimeProject", "TimeStamps", overlap_ts)
        ts = last_sync.get("last_signal_timestamp", "0") if not first_sync else recent_ts
        overlap_ts = _subtract_minutes(ts, overlap) if ts and ts != "0" else recent_ts
        time_series["signal_logs"] = _read_table_filtered(db, "XA_LOG", "XactStamp", overlap_ts)
        ts = last_sync.get("last_flow_timestamp", "0") if not first_sync else recent_ts
        overlap_ts = _subtract_minutes(ts, overlap) if ts and ts != "0" else recent_ts
        time_series["flow_readings"] = _read_table_filtered(db, "XA_FLOZO", "XactStamp", overlap_ts)

        # Filter out records already synced (within overlap but <= watermark)
        key_map = {
            "weather_logs": "last_weather_timestamp",
            "events": "last_event_timestamp",
            "et_checkbook": "last_etcheckbook_timestamp",
            "runtime": "last_runtime_timestamp",
            "signal_logs": "last_signal_timestamp",
            "flow_readings": "last_flow_timestamp",
        }
        for key, wm_key in key_map.items():
            ts_col = "TimeStamps" if key == "runtime" else "XactStamp"
            wm = last_sync.get(wm_key, "0")
            if wm and wm != "0" and time_series.get(key):
                time_series[key] = [r for r in time_series[key] if r.get(ts_col, "0") > wm]

        # Compute new watermarks
        new_sync = dict(last_sync)
        for key, wm_key in key_map.items():
            ts_col = "TimeStamps" if key == "runtime" else "XactStamp"
            if time_series.get(key):
                max_ts = max(r.get(ts_col, "0") for r in time_series[key] if r.get(ts_col))
                if max_ts > new_sync.get(wm_key, "0"):
                    new_sync[wm_key] = max_ts

        return config, time_series, new_sync
    finally:
        db.Close()


def _read_table(db, table_name):
    """Read all rows from a table."""
    rs = db.OpenRecordset(f"SELECT * FROM [{table_name}]")
    rows = []
    try:
        while not rs.EOF:
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
            rows.append(row)
            rs.MoveNext()
    finally:
        rs.Close()
    return rows


def _read_table_filtered(db, table_name, ts_column, since_timestamp):
    """Read rows where timestamp > since_timestamp."""
    if not since_timestamp or since_timestamp == "0":
        return _read_table(db, table_name)
    try:
        sql = f"SELECT * FROM [{table_name}] WHERE [{ts_column}] > '{since_timestamp}'"
        rs = db.OpenRecordset(sql)
        rows = []
        try:
            while not rs.EOF:
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
                rows.append(row)
                rs.MoveNext()
        finally:
            rs.Close()
        return rows
    except Exception:
        return _read_table(db, table_name)


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


def _hours_ago_timestamp(hours=24):
    """Get timestamp string for N hours ago."""
    ts = datetime.now() - timedelta(hours=hours)
    return ts.strftime("%Y%m%d%H%M%S")


def _is_first_sync(last_sync):
    """Check if this is the first sync (no watermarks set)."""
    return not last_sync or all(v == "0" or not v for v in last_sync.values())


# ─── Sync Worker ──────────────────────────────────────────────────────

def do_sync(cfg, last_sync, log_callback=None):
    """Perform one sync cycle."""
    import urllib.request
    import urllib.error

    try:
        if log_callback:
            log_callback("Reading MDB database...")
        config, time_series, new_sync = read_mdb_data(cfg, last_sync)
    except FileNotFoundError as e:
        return False, f"MDB not found: {e}", last_sync, {}
    except Exception as e:
        return False, f"MDB read error: {e}", last_sync, {}

    total = sum(len(v) for v in config.values()) + sum(len(v) for v in time_series.values())
    if total == 0:
        return True, "No new data to sync", last_sync, {}

    payload = {
        "sync_timestamp": datetime.now().strftime("%Y%m%d%H%M%S"),
        "config": config,
        "time_series": time_series,
    }

    url = cfg["server_url"].rstrip("/") + "/api/sync/receive"
    headers = {
        "Content-Type": "application/json",
        "X-Sync-Key": cfg["api_key"],
    }

    try:
        if log_callback:
            log_callback(f"Sending {total} records to {url}...")
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return False, f"Server error {e.code}: {body}", last_sync, {}
    except urllib.error.URLError as e:
        return False, f"Connection failed: {e.reason}", last_sync, {}
    except Exception as e:
        return False, f"Network error: {e}", last_sync, {}

    if result.get("status") == "ok":
        return True, f"Synced {total} records OK", new_sync, result.get("results", {})
    else:
        return False, f"Server returned: {result}", last_sync, {}


# ─── PyQt5 GUI ────────────────────────────────────────────────────────

def run_gui():
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QTextEdit, QDialog, QFormLayout, QLineEdit,
        QSpinBox, QFileDialog, QSystemTrayIcon, QMenu, QGroupBox,
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
    QPushButton#settingsBtn { background-color: #89b4fa; color: #1e1e2e; }
    QTextEdit {
        background-color: #11111b; border: 1px solid #45475a; border-radius: 6px;
        font-family: "Consolas", monospace; font-size: 12px; color: #a6adc8; padding: 4px;
    }
    QLineEdit, QSpinBox {
        background-color: #313244; border: 1px solid #45475a; border-radius: 4px;
        padding: 6px; color: #cdd6f4; font-size: 13px;
    }
    QDialog { background-color: #1e1e2e; }
    """

    class SyncThread(QThread):
        log_signal = pyqtSignal(str, str)
        finished_signal = pyqtSignal(bool, str)

        def __init__(self, cfg):
            super().__init__()
            self.cfg = cfg

        def run(self):
            last_sync = load_last_sync()
            success, message, new_sync, results = do_sync(
                self.cfg, last_sync, log_callback=lambda m: self.log_signal.emit(m, "info")
            )
            if success and new_sync != last_sync:
                save_last_sync(new_sync)
            self.log_signal.emit(message, "success" if success else "error")
            if results:
                for table, info in results.items():
                    if isinstance(info, dict):
                        detail = ", ".join(f"{k}={v}" for k, v in info.items())
                        self.log_signal.emit(f"  {table}: {detail}", "info")
            self.finished_signal.emit(success, message)

    class SettingsDialog(QDialog):
        def __init__(self, cfg, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Settings")
            self.setMinimumWidth(450)
            layout = QFormLayout(self)
            layout.setSpacing(12)

            self.server_edit = QLineEdit(cfg["server_url"])
            layout.addRow("Server URL:", self.server_edit)
            self.key_edit = QLineEdit(cfg["api_key"])
            self.key_edit.setEchoMode(QLineEdit.Password)
            layout.addRow("API Key:", self.key_edit)
            self.mdb_edit = QLineEdit(cfg["mdb_path"])
            mdb_btn = QPushButton("Browse...")
            mdb_btn.clicked.connect(self._browse_mdb)
            mdb_row = QHBoxLayout()
            mdb_row.addWidget(self.mdb_edit)
            mdb_row.addWidget(mdb_btn)
            layout.addRow("MDB Path:", mdb_row)
            self.pwd_edit = QLineEdit(cfg["mdb_password"])
            layout.addRow("MDB Password:", self.pwd_edit)
            self.interval_spin = QSpinBox()
            self.interval_spin.setRange(1, 60)
            self.interval_spin.setValue(cfg.get("sync_interval_minutes", 5))
            layout.addRow("Sync Interval (min):", self.interval_spin)
            btn_layout = QHBoxLayout()
            save_btn = QPushButton("Save")
            save_btn.clicked.connect(self.accept)
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(self.reject)
            btn_layout.addWidget(save_btn)
            btn_layout.addWidget(cancel_btn)
            layout.addRow(btn_layout)

        def _browse_mdb(self):
            path, _ = QFileDialog.getOpenFileName(self, "Select MDB file", "", "Access DB (*.mdb)")
            if path:
                self.mdb_edit.setText(path)

        def get_config(self):
            return {
                "server_url": self.server_edit.text(),
                "api_key": self.key_edit.text(),
                "mdb_path": self.mdb_edit.text(),
                "mdb_password": self.pwd_edit.text(),
                "sync_interval_minutes": self.interval_spin.value(),
                "overlap_buffer_minutes": 2,
            }

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.cfg = load_config()
            self.sync_thread = None
            self.setWindowTitle("Maxicom2 Sync Agent")
            self.setMinimumSize(500, 520)
            self.resize(520, 560)

            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)
            layout.setSpacing(10)
            layout.setContentsMargins(16, 16, 16, 16)

            # Status group
            status_group = QGroupBox("Connection Status")
            status_layout = QVBoxLayout(status_group)
            self.status_label = QLabel("● Disconnected")
            self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #f38ba8;")
            status_layout.addWidget(self.status_label)
            self.server_label = QLabel(f"Server: {self.cfg['server_url']}")
            status_layout.addWidget(self.server_label)
            self.last_sync_label = QLabel("Last Sync: Never")
            status_layout.addWidget(self.last_sync_label)
            self.next_sync_label = QLabel(f"Next Sync: Every {self.cfg['sync_interval_minutes']} min")
            status_layout.addWidget(self.next_sync_label)
            layout.addWidget(status_group)

            # Log group
            log_group = QGroupBox("Sync Log")
            log_layout = QVBoxLayout(log_group)
            self.log_text = QTextEdit()
            self.log_text.setReadOnly(True)
            log_layout.addWidget(self.log_text)
            layout.addWidget(log_group, stretch=1)

            # Buttons
            btn_layout = QHBoxLayout()
            self.sync_btn = QPushButton("▶  Sync Now")
            self.sync_btn.setObjectName("syncBtn")
            self.sync_btn.clicked.connect(self.manual_sync)
            self.settings_btn = QPushButton("⚙  Settings")
            self.settings_btn.setObjectName("settingsBtn")
            self.settings_btn.clicked.connect(self.open_settings)
            btn_layout.addWidget(self.sync_btn)
            btn_layout.addWidget(self.settings_btn)
            layout.addLayout(btn_layout)

            # Auto sync timer
            interval_ms = self.cfg.get("sync_interval_minutes", 5) * 60 * 1000
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.auto_sync)
            self.timer.start(interval_ms)

            # Connection check timer (every 30 seconds, silent)
            self.conn_timer = QTimer(self)
            self.conn_timer.timeout.connect(lambda: self._check_connection(silent=True))
            self.conn_timer.start(30000)

            self._setup_tray()
            self._check_connection()
            self._log("Sync Agent started", "info")
            self._log(f"Sync interval: {self.cfg['sync_interval_minutes']} minutes", "info")

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
            tray_menu.addAction("Show").triggered.connect(self.showNormal)
            tray_menu.addAction("Sync Now").triggered.connect(self.manual_sync)
            tray_menu.addAction("Quit").triggered.connect(self._quit)
            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.activated.connect(self._tray_activated)
            self.tray_icon.setToolTip("Maxicom2 Sync Agent")
            self.tray_icon.show()

        def _tray_activated(self, reason):
            if reason == QSystemTrayIcon.DoubleClick:
                self.showNormal()

        def changeEvent(self, event):
            if event.type() == event.WindowStateChange and self.windowState() & Qt.WindowMinimized:
                QTimer.singleShot(0, self.hide)
                self.tray_icon.showMessage("Maxicom2 Sync Agent", "Running in background.", QSystemTrayIcon.Information, 2000)
            super().changeEvent(event)

        def closeEvent(self, event):
            event.ignore()
            self.hide()
            self.tray_icon.showMessage("Maxicom2 Sync Agent", "Minimized to tray. Right-click to quit.", QSystemTrayIcon.Information, 3000)

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
                    new_status = "● Connected"
                    self.status_label.setText(new_status)
                    self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #a6e3a1;")
                    total = sum(data.get("counts", {}).values())
                    self.server_label.setText(f"Server: {self.cfg['server_url']} ({total:,} records)")
                    if not silent or "Disconnected" in old_status or "Error" in old_status:
                        self._log(f"Server connected — {total:,} total records", "info")
            except Exception:
                new_status = "● Disconnected"
                self.status_label.setText(new_status)
                self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #f38ba8;")
                self.server_label.setText(f"Server: {self.cfg['server_url']} (offline)")
                if not silent or "Connected" in old_status:
                    self._log("Server disconnected", "error")

        def _set_syncing(self, syncing):
            self.sync_btn.setEnabled(not syncing)
            self.sync_btn.setText("Syncing..." if syncing else "▶  Sync Now")

        def manual_sync(self):
            self._do_sync()

        def auto_sync(self):
            self._log("Auto sync triggered", "info")
            self._do_sync()

        def _do_sync(self):
            if self.sync_thread and self.sync_thread.isRunning():
                return
            self._set_syncing(True)
            self.sync_thread = SyncThread(self.cfg)
            self.sync_thread.log_signal.connect(self._log)
            self.sync_thread.finished_signal.connect(self._on_sync_done)
            self.sync_thread.start()

        def _on_sync_done(self, success, message):
            self._set_syncing(False)
            if success:
                last_sync = load_last_sync()
                latest = max(last_sync.values()) if last_sync else "N/A"
                self.last_sync_label.setText(f"Last Sync: {self._format_ts(latest)}  ✓")
                self.status_label.setText("● Connected")
                self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #a6e3a1;")
            else:
                self.last_sync_label.setText("Last Sync: FAILED  ✗")
                self.status_label.setText("● Error")
                self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #f38ba8;")
                self.tray_icon.showMessage("Sync Error", message[:100], QSystemTrayIcon.Critical, 5000)

        def _format_ts(self, ts_str):
            if not ts_str or ts_str == "0" or len(ts_str) < 14:
                return "N/A"
            try:
                return datetime.strptime(ts_str[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                return ts_str

        def open_settings(self):
            dlg = SettingsDialog(self.cfg, self)
            if dlg.exec_() == QDialog.Accepted:
                self.cfg = dlg.get_config()
                save_config(self.cfg)
                self.timer.setInterval(self.cfg["sync_interval_minutes"] * 60 * 1000)
                self.next_sync_label.setText(f"Next Sync: Every {self.cfg['sync_interval_minutes']} min")
                self._log("Settings saved", "success")
                self._check_connection()

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


# ─── CLI Mode ─────────────────────────────────────────────────────────

def run_cli():
    cfg = load_config()
    last_sync = load_last_sync()
    print(f"MDB Path: {cfg['mdb_path']}")
    print(f"Server:   {cfg['server_url']}")
    print(f"Last sync: {json.dumps(last_sync, indent=2)}\n")
    success, message, new_sync, results = do_sync(cfg, last_sync, log_callback=print)
    print(f"\n{'='*50}")
    if success:
        print(f"✓ {message}")
        if new_sync != last_sync:
            save_last_sync(new_sync)
            print(f"Updated watermarks: {json.dumps(new_sync, indent=2)}")
        if results:
            for table, info in results.items():
                print(f"  {table}: {info}")
    else:
        print(f"✗ {message}")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_cli()
    else:
        run_gui()