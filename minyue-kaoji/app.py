"""民乐考级纸件与赴考脚注核对 —— Flask API。

本机运行：python app.py  →  http://127.0.0.1:5000
"""
from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from check import (CATEGORIES, data_fingerprint, run_checks, run_staleness,
                   version_fingerprint)
from db import DB_PATH, get_db, init_db, spec_of

app = Flask(__name__, static_folder="static", static_url_path="")

# 通用子表配置：API 名 -> (外键列, 物理表名, 可写字段)
SUBTABLES = {
    "certs": ("child_id", "cert", ["instrument", "level", "issuer", "has_original"]),
    "pieces": ("child_id", "piece", ["title", "is_extra", "ready"]),
    "materials": ("child_id", "material", [
        "req_key", "mtype", "label", "status", "copies", "uses_original",
        "hold_start", "hold_end", "location", "detail", "bag_order", "checked"]),
    "windows": ("child_id", "companion_window",
                ["adult_name", "start", "end", "entrance"]),
}

CHILD_FIELDS = [
    "name", "instrument", "apply_level", "skip_from", "exam_date",
    "slot_start", "slot_end", "entrance", "exam_number", "birth_date",
    "id_type", "id_number", "guardian", "bag_order",
]
CLAUSE_FIELDS = ["category", "ref", "title", "body", "spec", "sort_order", "version_id"]
VERSION_FIELDS = ["title", "issuer", "published", "note", "is_active"]


# ---------------------------------------------------------------- 工具

def bad(msg, code=400):
    return jsonify({"error": msg}), code


def clean(payload, fields, ints=(), bools=()):
    data = {}
    for f in fields:
        if f in payload:
            v = payload[f]
            if f in ints:
                data[f] = None if v in (None, "") else int(v)
            elif f in bools:
                data[f] = 1 if v else 0
            else:
                data[f] = v
    return data


def clause_json(row):
    d = dict(row)
    d["spec"] = spec_of(row)
    return d


def child_json(conn, row):
    d = dict(row)
    for sub, (fk, table, _) in SUBTABLES.items():
        d[sub] = [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} WHERE {fk}=? ORDER BY id", (row["id"],))]
    return d


# ---------------------------------------------------------------- 汇总状态

@app.get("/api/state")
def get_state():
    conn = get_db()
    try:
        versions = [dict(r) for r in conn.execute(
            "SELECT * FROM version ORDER BY id DESC")]
        active = next((v for v in versions if v["is_active"]), None)
        clauses = []
        vfp = ""
        dfp = ""
        if active:
            crows = conn.execute(
                "SELECT * FROM clause WHERE version_id=? ORDER BY sort_order, id",
                (active["id"],)).fetchall()
            clauses = [clause_json(r) for r in crows]
            vfp = version_fingerprint([dict(r) for r in crows])
            kids = []
            for r in conn.execute("SELECT * FROM child ORDER BY bag_order, id"):
                ch = dict(r)
                for sub, (fk, tbl, _) in SUBTABLES.items():
                    ch[sub] = [dict(x) for x in conn.execute(
                        f"SELECT * FROM {tbl} WHERE {fk}=? ORDER BY id", (r["id"],))]
                kids.append(ch)
            dfp = data_fingerprint(kids)

        children = [child_json(conn, r) for r in conn.execute(
            "SELECT * FROM child ORDER BY bag_order, id")]

        runs = []
        for r in conn.execute("SELECT * FROM check_run ORDER BY id DESC LIMIT 10"):
            d = dict(r)
            d["findings"] = json.loads(r["findings"])
            d["original_pairs"] = json.loads(r["original_pairs"])
            d["carried_originals"] = json.loads(r["carried_originals"])
            d["staleness"] = (run_staleness(conn, r, vfp, dfp)
                              if active and r["version_id"] == active["id"]
                              else "old_version")
            runs.append(d)

        return jsonify({
            "versions": versions,
            "active_version": active,
            "clauses": clauses,
            "categories": CATEGORIES,
            "children": children,
            "runs": runs,
        })
    finally:
        conn.close()


# ---------------------------------------------------------------- 简章版本

@app.post("/api/versions")
def create_version():
    p = request.get_json(force=True, silent=True) or {}
    if not p.get("title"):
        return bad("请填写简章名称")
    data = clean(p, VERSION_FIELDS, bools=["is_active"])
    conn = get_db()
    try:
        if data.get("is_active"):
            conn.execute("UPDATE version SET is_active=0")
        cur = conn.execute(
            "INSERT INTO version(title, issuer, published, note, is_active) "
            "VALUES (?,?,?,?,?)",
            (data.get("title", ""), data.get("issuer", ""), data.get("published", ""),
             data.get("note", ""), data.get("is_active", 1)))
        if "is_active" not in data:
            # 第一版自动激活
            if conn.execute("SELECT COUNT(*) c FROM version").fetchone()["c"] == 1:
                conn.execute("UPDATE version SET is_active=1 WHERE id=?", (cur.lastrowid,))
        conn.commit()
        return jsonify({"id": cur.lastrowid})
    finally:
        conn.close()


@app.patch("/api/versions/<int:vid>")
def update_version(vid):
    p = request.get_json(force=True, silent=True) or {}
    data = clean(p, VERSION_FIELDS, bools=["is_active"])
    conn = get_db()
    try:
        if conn.execute("SELECT id FROM version WHERE id=?", (vid,)).fetchone() is None:
            return bad("版本不存在", 404)
        if data.get("is_active"):
            conn.execute("UPDATE version SET is_active=0")
        if data:
            sets = ", ".join(f"{k}=?" for k in data)
            conn.execute(f"UPDATE version SET {sets} WHERE id=?",
                         (*data.values(), vid))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.post("/api/versions/<int:vid>/duplicate")
def duplicate_version(vid):
    """简章改版：复制旧版全部条款，旧结论立即失效。"""
    p = request.get_json(force=True, silent=True) or {}
    conn = get_db()
    try:
        src = conn.execute("SELECT * FROM version WHERE id=?", (vid,)).fetchone()
        if src is None:
            return bad("版本不存在", 404)
        conn.execute("UPDATE version SET is_active=0")
        cur = conn.execute(
            "INSERT INTO version(title, issuer, published, note, is_active) "
            "VALUES (?,?,?,?,1)",
            (p.get("title", src["title"] + "（改版）"),
             p.get("issuer", src["issuer"]), p.get("published", ""),
             "由旧版复制，请按新公告逐条修订；旧核对结论已失效"))
        new_id = cur.lastrowid
        for c in conn.execute("SELECT * FROM clause WHERE version_id=?", (vid,)):
            conn.execute(
                "INSERT INTO clause(version_id, category, ref, title, body, spec, sort_order) "
                "VALUES (?,?,?,?,?,?,?)",
                (new_id, c["category"], c["ref"], c["title"], c["body"], c["spec"],
                 c["sort_order"]))
        conn.commit()
        return jsonify({"id": new_id})
    finally:
        conn.close()


# ---------------------------------------------------------------- 条款

@app.post("/api/clauses")
def create_clause():
    p = request.get_json(force=True, silent=True) or {}
    data = clean(p, CLAUSE_FIELDS, ints=["sort_order", "version_id"])
    if not data.get("version_id") or not data.get("ref") or not data.get("title"):
        return bad("版本、依据编号、标题必填")
    if data.get("category") not in CATEGORIES:
        return bad("条款类别无效")
    spec = p.get("spec")
    data["spec"] = json.dumps(spec if isinstance(spec, dict) else {},
                              ensure_ascii=False)
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO clause(version_id, category, ref, title, body, spec, sort_order) "
            "VALUES (?,?,?,?,?,?,?)",
            (data["version_id"], data["category"], data["ref"], data["title"],
             data.get("body", ""), data["spec"], data.get("sort_order", 0)))
        conn.commit()
        return jsonify({"id": cur.lastrowid})
    finally:
        conn.close()


@app.patch("/api/clauses/<int:cid>")
def update_clause(cid):
    p = request.get_json(force=True, silent=True) or {}
    data = clean(p, ["category", "ref", "title", "body", "sort_order"],
                 ints=["sort_order"])
    if "category" in data and data["category"] not in CATEGORIES:
        return bad("条款类别无效")
    conn = get_db()
    try:
        if "spec" in p:
            sp = p["spec"]
            data["spec"] = json.dumps(sp if isinstance(sp, dict) else {},
                                      ensure_ascii=False)
        if data:
            sets = ", ".join(f"{k}=?" for k in data)
            conn.execute(f"UPDATE clause SET {sets} WHERE id=?", (*data.values(), cid))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.delete("/api/clauses/<int:cid>")
def delete_clause(cid):
    conn = get_db()
    try:
        conn.execute("DELETE FROM clause WHERE id=?", (cid,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ---------------------------------------------------------------- 孩子与子表

@app.post("/api/children")
def create_child():
    p = request.get_json(force=True, silent=True) or {}
    if not p.get("name"):
        return bad("请填写孩子姓名")
    data = clean(p, CHILD_FIELDS, ints=["apply_level", "skip_from", "bag_order"])
    conn = get_db()
    try:
        if "bag_order" not in data:
            data["bag_order"] = (conn.execute(
                "SELECT COALESCE(MAX(bag_order),0)+1 m FROM child").fetchone()["m"])
        cols = ", ".join(data)
        qs = ", ".join("?" for _ in data)
        cur = conn.execute(f"INSERT INTO child({cols}) VALUES ({qs})",
                           tuple(data.values()))
        conn.commit()
        return jsonify({"id": cur.lastrowid})
    finally:
        conn.close()


@app.patch("/api/children/<int:chid>")
@app.delete("/api/children/<int:chid>")
def child_detail(chid):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM child WHERE id=?", (chid,)).fetchone()
        if row is None:
            return bad("孩子不存在", 404)
        if request.method == "DELETE":
            conn.execute("DELETE FROM child WHERE id=?", (chid,))
            conn.commit()
            return jsonify({"ok": True})
        p = request.get_json(force=True, silent=True) or {}
        data = clean(p, CHILD_FIELDS, ints=["apply_level", "skip_from", "bag_order"])
        if data:
            sets = ", ".join(f"{k}=?" for k in data)
            conn.execute(f"UPDATE child SET {sets} WHERE id=?",
                         (*data.values(), chid))
            conn.commit()
        return jsonify(child_json(conn, conn.execute(
            "SELECT * FROM child WHERE id=?", (chid,)).fetchone()))
    finally:
        conn.close()


def _sub_route(table, chid):
    fk, tbl, fields = SUBTABLES[table]
    bools = ["has_original", "is_extra", "ready", "checked"]
    ints = ["level", "copies", "bag_order"]
    conn = get_db()
    try:
        if conn.execute("SELECT id FROM child WHERE id=?", (chid,)).fetchone() is None:
            return bad("孩子不存在", 404)
        if request.method == "POST":
            p = request.get_json(force=True, silent=True) or {}
            data = clean(p, fields, ints=[i for i in ints if i in fields],
                         bools=[b for b in bools if b in fields])
            data[fk] = chid
            cols = ", ".join(data)
            qs = ", ".join("?" for _ in data)
            cur = conn.execute(f"INSERT INTO {tbl}({cols}) VALUES ({qs})",
                               tuple(data.values()))
            conn.commit()
            return jsonify({"id": cur.lastrowid})
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM {tbl} WHERE {fk}=? ORDER BY id", (chid,))]
        return jsonify(rows)
    finally:
        conn.close()


@app.route("/api/children/<int:chid>/<table>", methods=["GET", "POST"])
def child_subtable(chid, table):
    if table not in SUBTABLES:
        return bad("未知子表", 404)
    return _sub_route(table, chid)


@app.route("/api/<table>/<int:rid>", methods=["PATCH", "DELETE"])
def sub_row(table, rid):
    if table not in SUBTABLES:
        return bad("未知子表", 404)
    fk, tbl, fields = SUBTABLES[table]
    bools = ["has_original", "is_extra", "ready", "checked"]
    ints = ["level", "copies", "bag_order"]
    conn = get_db()
    try:
        row = conn.execute(f"SELECT * FROM {tbl} WHERE id=?", (rid,)).fetchone()
        if row is None:
            return bad("记录不存在", 404)
        if request.method == "DELETE":
            conn.execute(f"DELETE FROM {tbl} WHERE id=?", (rid,))
            conn.commit()
            return jsonify({"ok": True})
        p = request.get_json(force=True, silent=True) or {}
        data = clean(p, fields, ints=[i for i in ints if i in fields],
                     bools=[b for b in bools if b in fields])
        if data:
            sets = ", ".join(f"{k}=?" for k in data)
            conn.execute(f"UPDATE {tbl} SET {sets} WHERE id=?",
                         (*data.values(), rid))
            conn.commit()
        return jsonify(dict(conn.execute(
            f"SELECT * FROM {tbl} WHERE id=?", (rid,)).fetchone()))
    finally:
        conn.close()


# ---------------------------------------------------------------- 清单生成与核对

@app.post("/api/children/sync-materials")
def sync_materials():
    """按当前简章要求为每个孩子 upsert 系统清单项（家长自加项保留）。"""
    from check import group_clauses, requirements_for

    conn = get_db()
    try:
        active = conn.execute(
            "SELECT * FROM version WHERE is_active=1 ORDER BY id DESC").fetchone()
        if active is None:
            return bad("尚无启用的简章版本")
        clauses = [dict(r) for r in conn.execute(
            "SELECT * FROM clause WHERE version_id=? ORDER BY sort_order, id",
            (active["id"],))]
        grouped = group_clauses(clauses)
        synced = []
        for ch in conn.execute("SELECT * FROM child ORDER BY bag_order, id"):
            d = dict(ch)
            d["certs"] = [dict(r) for r in conn.execute(
                "SELECT * FROM cert WHERE child_id=?", (ch["id"],))]
            d["pieces"] = [dict(r) for r in conn.execute(
                "SELECT * FROM piece WHERE child_id=?", (ch["id"],))]
            d["materials"] = [dict(r) for r in conn.execute(
                "SELECT * FROM material WHERE child_id=?", (ch["id"],))]
            d["windows"] = []

            def swallow(*a, **k):
                pass

            reqs, _, _ = requirements_for(d, grouped, swallow)
            req_keys = {r["req_key"] for r in reqs}
            existing = {m["req_key"]: m for m in d["materials"] if m["req_key"]}
            # 简章不再要求、且尚未备齐也未勾选的系统项直接清掉；
            # 已有准备的项保留，由家长手动删除以免丢记录。
            for m in d["materials"]:
                if (m["req_key"] and m["req_key"] not in req_keys
                        and m["status"] == "missing" and not m["checked"]):
                    conn.execute("DELETE FROM material WHERE id=?", (m["id"],))
            order = len(d["materials"])
            for req in reqs:
                if req["req_key"] in existing:
                    m = existing[req["req_key"]]
                    conn.execute(
                        "UPDATE material SET mtype=?, label=?, copies=?, uses_original=? "
                        "WHERE id=?",
                        (req["mtype"], req["label"], req["copies"],
                         req["uses_original"], m["id"]))
                else:
                    order += 1
                    conn.execute(
                        "INSERT INTO material(child_id, req_key, mtype, label, status, "
                        "copies, uses_original, bag_order) VALUES (?,?,?,?,?,?,?,?)",
                        (ch["id"], req["req_key"], req["mtype"], req["label"],
                         "missing", req["copies"], req["uses_original"], order))
                    synced.append(req["label"])
        conn.commit()
        return jsonify({"ok": True, "added": synced})
    finally:
        conn.close()


@app.post("/api/checks")
def create_check():
    conn = get_db()
    try:
        active = conn.execute(
            "SELECT * FROM version WHERE is_active=1 ORDER BY id DESC").fetchone()
        if active is None:
            return bad("尚无启用的简章版本，请先录入简章")
        result = run_checks(conn, active["id"])
        return jsonify(result)
    except ValueError as e:
        return bad(str(e))
    finally:
        conn.close()


# ---------------------------------------------------------------- 页面

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


init_db(DB_PATH)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
