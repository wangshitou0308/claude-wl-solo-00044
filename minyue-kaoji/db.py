"""SQLite 存储层：简章版本、条款、孩子材料与核对结论。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("kaoji.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS version (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    issuer      TEXT DEFAULT '',
    published   TEXT DEFAULT '',          -- 简章公布日期 YYYY-MM-DD
    note        TEXT DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS clause (
    id          INTEGER PRIMARY KEY,
    version_id  INTEGER NOT NULL REFERENCES version(id) ON DELETE CASCADE,
    category    TEXT NOT NULL,            -- instrument/level/skip/photo/form/id_copy/slot/entrance/route/note
    ref         TEXT NOT NULL,            -- 公告依据编号，如 ZP-01
    title       TEXT NOT NULL,
    body        TEXT DEFAULT '',
    spec        TEXT DEFAULT '{}',        -- 结构化字段 JSON
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS child (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    instrument    TEXT DEFAULT '',
    apply_level   INTEGER,
    skip_from     INTEGER,                -- 报跳级时，实际持有的最高级别；逐级报考为空
    exam_date     TEXT DEFAULT '',
    slot_start    TEXT DEFAULT '',        -- HH:MM
    slot_end      TEXT DEFAULT '',
    entrance      TEXT DEFAULT '',
    exam_number   TEXT DEFAULT '',
    birth_date    TEXT DEFAULT '',
    id_type       TEXT DEFAULT '',        -- 身份证/户口本/护照
    id_number     TEXT DEFAULT '',
    guardian      TEXT DEFAULT '',
    bag_order     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cert (
    id           INTEGER PRIMARY KEY,
    child_id     INTEGER NOT NULL REFERENCES child(id) ON DELETE CASCADE,
    instrument   TEXT DEFAULT '',
    level        INTEGER,
    issuer       TEXT DEFAULT '',
    has_original INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS piece (
    id           INTEGER PRIMARY KEY,
    child_id     INTEGER NOT NULL REFERENCES child(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    is_extra     INTEGER NOT NULL DEFAULT 0,   -- 加试曲目
    ready        INTEGER NOT NULL DEFAULT 1    -- 已练成可考
);

CREATE TABLE IF NOT EXISTS material (
    id           INTEGER PRIMARY KEY,
    child_id     INTEGER NOT NULL REFERENCES child(id) ON DELETE CASCADE,
    req_key      TEXT DEFAULT '',              -- 系统清单键：form/photo/id_copy/cert:.../extra，空=家长自加
    mtype        TEXT NOT NULL,                -- form/photo/cert/id_copy/other
    label        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'missing', -- ok/partial/missing
    copies       INTEGER NOT NULL DEFAULT 1,
    uses_original TEXT DEFAULT '',             -- 占用原件名：id/证书(乐种Lv)/''
    hold_start   TEXT DEFAULT '',              -- 候考/交表时段 HH:MM
    hold_end     TEXT DEFAULT '',
    location     TEXT DEFAULT '',              -- 所在入口/考场
    detail       TEXT DEFAULT '',
    bag_order    INTEGER NOT NULL DEFAULT 0,
    checked      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS companion_window (
    id           INTEGER PRIMARY KEY,
    child_id     INTEGER NOT NULL REFERENCES child(id) ON DELETE CASCADE,
    adult_name   TEXT NOT NULL,
    start        TEXT DEFAULT '',
    end          TEXT DEFAULT '',
    entrance     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS check_run (
    id           INTEGER PRIMARY KEY,
    version_id   INTEGER NOT NULL REFERENCES version(id),
    version_fingerprint TEXT NOT NULL,
    data_fingerprint    TEXT NOT NULL,
    findings     TEXT NOT NULL DEFAULT '[]',
    original_pairs     TEXT NOT NULL DEFAULT '[]',
    earliest_conflict  TEXT DEFAULT '',
    carried_originals   TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

# 指纹只纳入会影响结论的字段；装袋顺序、勾选状态变化不影响结论。
CHILD_FP_COLS = [
    "name", "instrument", "apply_level", "skip_from", "exam_date",
    "slot_start", "slot_end", "entrance", "exam_number", "birth_date",
    "id_type", "id_number", "guardian",
]
CERT_FP_COLS = ["child_id", "instrument", "level", "issuer", "has_original"]
PIECE_FP_COLS = ["child_id", "title", "is_extra", "ready"]
MAT_FP_COLS = [
    "child_id", "req_key", "mtype", "label", "status", "copies",
    "uses_original", "hold_start", "hold_end", "location", "detail",
]
WIN_FP_COLS = ["child_id", "adult_name", "start", "end", "entrance"]


def get_db(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path | str | None = None) -> None:
    conn = get_db(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(obj) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()[:16]


def spec_of(clause: sqlite3.Row) -> dict:
    try:
        return json.loads(clause["spec"] or "{}")
    except (ValueError, TypeError):
        return {}
