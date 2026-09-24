import os
import re
import sqlite3
import logging
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Iterable

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    size INTEGER DEFAULT 0,
    complete INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_segments_start ON segments(start);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    label TEXT DEFAULT '',
    confidence REAL DEFAULT 0,
    snapshot TEXT DEFAULT '',
    clip TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start);
"""


class RecordingIndex:
    """
    Chỉ mục SQLite cho dữ liệu ghi hình:
    - segments: các đoạn ghi liên tục 24/7 (phục vụ timeline tua lại)
    - events: sự kiện phát hiện người / chuyển động / thủ công (kèm snapshot, clip)
    Đường dẫn file được lưu tương đối so với thư mục recordings.
    """

    def __init__(self, base_dir: str = "recordings"):
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(os.path.join(self.base_dir, "index.db"), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._mark_stale_segments()

    # ------------------------------------------------------------------ helpers
    def rel(self, path: str) -> str:
        if not path:
            return ""
        return os.path.relpath(os.path.abspath(path), self.base_dir).replace("\\", "/")

    def abs(self, rel_path: str) -> str:
        return os.path.join(self.base_dir, rel_path.replace("/", os.sep))

    def _exec(self, sql: str, params: Iterable = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: Iterable = ()) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def _mark_stale_segments(self):
        # Các segment đang ghi dở khi tiến trình bị tắt đột ngột -> đánh dấu hoàn tất
        self._exec("UPDATE segments SET complete = 1 WHERE complete = 0")

    # ----------------------------------------------------------------- segments
    def add_segment(self, path: str, start: float) -> int:
        cur = self._exec("INSERT OR REPLACE INTO segments(path, start, end, size, complete) VALUES (?, ?, ?, 0, 0)",
                         (self.rel(path), start, start))
        return cur.lastrowid

    def update_segment(self, seg_id: int, end: float, size: int, complete: bool = False):
        self._exec("UPDATE segments SET end = ?, size = ?, complete = ? WHERE id = ?",
                   (end, size, 1 if complete else 0, seg_id))

    def get_segment(self, seg_id: int) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM segments WHERE id = ?", (seg_id,))
        return rows[0] if rows else None

    def query_segments(self, start: float, end: float) -> List[Dict[str, Any]]:
        return self._query("SELECT id, start, end, complete FROM segments WHERE end >= ? AND start <= ? ORDER BY start",
                           (start, end))

    def segments_for_range(self, start: float, end: float) -> List[Dict[str, Any]]:
        return self._query("SELECT * FROM segments WHERE end >= ? AND start <= ? ORDER BY start", (start, end))

    def delete_segment_by_path(self, abs_path: str):
        self._exec("DELETE FROM segments WHERE path = ?", (self.rel(abs_path),))

    # ------------------------------------------------------------------- events
    def add_event(self, type_: str, start: float, end: Optional[float] = None, label: str = "",
                  confidence: float = 0.0, snapshot: str = "", clip: str = "") -> int:
        cur = self._exec(
            "INSERT INTO events(type, start, end, label, confidence, snapshot, clip) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (type_, start, end if end is not None else start, label, confidence, self.rel(snapshot), self.rel(clip)))
        return cur.lastrowid

    def update_event(self, event_id: int, **fields):
        allowed = {"end", "label", "confidence", "snapshot", "clip"}
        sets, params = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in ("snapshot", "clip"):
                v = self.rel(v)
            sets.append(f"{k} = ?")
            params.append(v)
        if sets:
            params.append(event_id)
            self._exec(f"UPDATE events SET {', '.join(sets)} WHERE id = ?", params)

    def get_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM events WHERE id = ?", (event_id,))
        return rows[0] if rows else None

    def query_events(self, start: float, end: float, types: Optional[List[str]] = None,
                     limit: int = 5000, newest_first: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM events WHERE end >= ? AND start <= ?"
        params: List[Any] = [start, end]
        if types:
            sql += f" AND type IN ({','.join('?' * len(types))})"
            params.extend(types)
        sql += f" ORDER BY start {'DESC' if newest_first else 'ASC'} LIMIT ?"
        params.append(limit)
        return self._query(sql, params)

    def delete_event(self, event_id: int, delete_files: bool = True) -> bool:
        ev = self.get_event(event_id)
        if not ev:
            return False
        if delete_files:
            for key in ("snapshot", "clip"):
                if ev.get(key):
                    p = self.abs(ev[key])
                    if os.path.isfile(p):
                        try:
                            os.remove(p)
                        except OSError as e:
                            logger.warning(f"Không thể xoá {p}: {e}")
        self._exec("DELETE FROM events WHERE id = ?", (event_id,))
        return True

    # -------------------------------------------------------------------- stats
    def day_summary(self) -> Dict[str, Dict[str, Any]]:
        """Thống kê theo ngày (giờ địa phương): số giây đã ghi và số sự kiện."""
        out: Dict[str, Dict[str, Any]] = {}
        for r in self._query("SELECT date(start, 'unixepoch', 'localtime') AS d, SUM(end - start) AS secs "
                             "FROM segments GROUP BY d"):
            out.setdefault(r["d"], {"recorded": 0, "events": 0})["recorded"] = int(r["secs"] or 0)
        for r in self._query("SELECT date(start, 'unixepoch', 'localtime') AS d, COUNT(*) AS n "
                             "FROM events WHERE type != 'motion' GROUP BY d"):
            out.setdefault(r["d"], {"recorded": 0, "events": 0})["events"] = r["n"]
        return out

    def prune_missing(self):
        """Xoá các bản ghi segment trỏ tới file đã bị xoá (do retention) và dọn tham chiếu file của event."""
        with self._lock:
            for r in self._query("SELECT id, path FROM segments"):
                if not os.path.exists(self.abs(r["path"])):
                    self._conn.execute("DELETE FROM segments WHERE id = ?", (r["id"],))
            for r in self._query("SELECT id, snapshot, clip FROM events WHERE snapshot != '' OR clip != ''"):
                snap_ok = not r["snapshot"] or os.path.exists(self.abs(r["snapshot"]))
                clip_ok = not r["clip"] or os.path.exists(self.abs(r["clip"]))
                if not snap_ok or not clip_ok:
                    self._conn.execute("UPDATE events SET snapshot = ?, clip = ? WHERE id = ?",
                                       (r["snapshot"] if snap_ok else "", r["clip"] if clip_ok else "", r["id"]))
            self._conn.commit()

    def import_legacy_files(self):
        """Nhập các ảnh alert_*.jpg / event_*.mp4 cũ (trước khi có web app) thành sự kiện."""
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if n > 0:
            return
        pat = re.compile(r"^(alert|event|cmd_snap)_(\d{8}_\d{6})\.(jpg|mp4)$")
        snaps, clips = {}, {}
        for name in os.listdir(self.base_dir):
            m = pat.match(name)
            if not m:
                continue
            ts = datetime.strptime(m.group(2), "%Y%m%d_%H%M%S").timestamp()
            (clips if m.group(3) == "mp4" else snaps)[ts] = (m.group(1), os.path.join(self.base_dir, name))
        clip_times = sorted(clips)
        count = 0
        for ts, (kind, path) in sorted(snaps.items()):
            # Ghép clip gần nhất trong vòng 5 giây sau ảnh
            clip = next((clips[c][1] for c in clip_times if 0 <= c - ts <= 5), "")
            type_ = "manual" if kind == "cmd_snap" else "person"
            self.add_event(type_, ts, ts + 8, label="person" if type_ == "person" else "snapshot",
                           snapshot=path, clip=clip)
            count += 1
        if count:
            logger.info(f"Đã nhập {count} sự kiện cũ vào chỉ mục.")
