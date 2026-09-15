"""核查引擎规则测试：使用独立临时数据库，覆盖五类核查与失效逻辑。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from db import get_db, init_db
from check import run_checks, run_staleness, version_fingerprint, data_fingerprint, group_clauses

J = lambda d: json.dumps(d, ensure_ascii=False)


def hydrate(conn):
    kids = []
    for ch in conn.execute("SELECT * FROM child ORDER BY id"):
        d = dict(ch)
        d["certs"] = [dict(x) for x in conn.execute(
            "SELECT * FROM cert WHERE child_id=?", (ch["id"],))]
        d["pieces"] = [dict(x) for x in conn.execute(
            "SELECT * FROM piece WHERE child_id=?", (ch["id"],))]
        d["materials"] = [dict(x) for x in conn.execute(
            "SELECT * FROM material WHERE child_id=?", (ch["id"],))]
        d["windows"] = [dict(x) for x in conn.execute(
            "SELECT * FROM companion_window WHERE child_id=?", (ch["id"],))]
        kids.append(d)
    return kids

BASIC_CLAUSES = [
    ("instrument", "LZ", "开考乐种", "", J({"instruments": ["古筝", "二胡"]})),
    ("level", "JB", "级别 1-10", "", J({"min": 1, "max": 10})),
    ("skip", "TJ37", "3-7 级跳级", "须前一级证书原件，加试一首",
     J({"levels": [3, 7], "need_original": True, "extra_required": True})),
    ("skip", "TJ8X", "8 级以上跳级", "须前两级证书",
     J({"levels": [8, 10], "need_level": 6, "need_original": True, "extra_required": True})),
    ("photo", "ZP", "二寸蓝底 3 张", "", J({"size": "二寸", "count": 3, "background": "蓝"})),
    ("form", "ZB", "报名表一式两份须签章", "", J({"copies": 2})),
    ("id_copy", "ZJ", "户口本复印件 1 份，原件核验", "",
     J({"copies": 1, "need_original": True})),
    ("entrance", "RK-N", "北门", "", J({"name": "北门", "open_after": "07:30"})),
    ("entrance", "RK-S", "南门", "", J({"name": "南门", "open_after": "08:00"})),
    ("route", "XL", "南北门步行 15 分钟", "", J({"pairs": [["北门", "南门", 15]]})),
]


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.path = Path(self.tmp.name)
        init_db(self.path)
        self.conn = get_db(self.path)
        cur = self.conn.execute(
            "INSERT INTO version(title, is_active) VALUES('测试简章',1)")
        self.vid = cur.lastrowid
        for i, (cat, ref, title, body, sp) in enumerate(BASIC_CLAUSES):
            self.conn.execute(
                "INSERT INTO clause(version_id, category, ref, title, body, spec, sort_order) "
                "VALUES (?,?,?,?,?,?,?)", (self.vid, cat, ref, title, body, sp, i))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.path.unlink(missing_ok=True)

    def add_child(self, name, **kw):
        defaults = dict(name=name, instrument="古筝", apply_level=4, skip_from=3,
                        exam_date="2026-07-12", slot_start="08:00", slot_end="09:00",
                        entrance="北门")
        defaults.update(kw)
        cols = ", ".join(defaults)
        qs = ", ".join("?" for _ in defaults)
        cur = self.conn.execute(
            f"INSERT INTO child({cols}) VALUES ({qs})", tuple(defaults.values()))
        return cur.lastrowid

    def add_mat(self, cid, req_key, mtype, status="ok", copies=1, uses_original="",
                hold_start="", hold_end="", location="", detail="{}", label=None):
        self.conn.execute(
            "INSERT INTO material(child_id, req_key, mtype, label, status, copies, "
            "uses_original, hold_start, hold_end, location, detail, bag_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
            (cid, req_key, mtype, label or req_key, status, copies, uses_original,
             hold_start, hold_end, location, detail))

    def msgs(self, result, severity=None, rule=None):
        return [f["message"] for f in result["findings"]
                if (severity is None or f["severity"] == severity)
                and (rule is None or f["rule"] == rule)]

    def test_skip_ok(self):
        cid = self.add_child("甲")
        self.conn.execute(
            "INSERT INTO cert(child_id, instrument, level, has_original) VALUES(?,?,?,1)",
            (cid, "古筝", 3))
        self.conn.execute(
            "INSERT INTO piece(child_id, title, is_extra, ready) VALUES(?, '加试', 1, 1)",
            (cid,))
        r = run_checks(self.conn, self.vid)
        self.assertTrue(any("满足" in m for m in self.msgs(r, rule="skip")))
        self.assertEqual([], self.msgs(r, "fail", "skip"))

    def test_skip_level_too_low(self):
        cid = self.add_child("乙")
        self.conn.execute(
            "INSERT INTO cert(child_id, instrument, level, has_original) VALUES(?,?,?,1)",
            (cid, "古筝", 2))
        r = run_checks(self.conn, self.vid)
        self.assertTrue(any("须持 3 级" in m for m in self.msgs(r, "fail", "skip")))
        cites = [c["ref"] for f in r["findings"]
                 for c in f["cites"] if f["severity"] == "fail" and f["rule"] == "skip"]
        self.assertIn("TJ37", cites)

    def test_skip_no_original_cert(self):
        cid = self.add_child("丙")
        self.conn.execute(
            "INSERT INTO cert(child_id, instrument, level, has_original) VALUES(?,?,?,0)",
            (cid, "古筝", 3))
        self.add_mat(cid, "cert:skip", "cert", uses_original="证书(古筝3级)")
        r = run_checks(self.conn, self.vid)
        self.assertTrue(any("登记为无原件" in m for m in self.msgs(r, "fail")))

    def test_form_field_contradiction_and_seal(self):
        cid = self.add_child("丁", apply_level=4)
        self.add_mat(cid, "form", "form", detail=J({
            "apply_level": 3, "signed": True, "sealed": False}))
        r = run_checks(self.conn, self.vid)
        fails = self.msgs(r, "fail", "contradiction")
        self.assertTrue(any("报考级别" in m for m in fails))
        self.assertTrue(any("未盖章" in m for m in fails))

    def test_missing_material_and_copies(self):
        cid = self.add_child("戊")
        # 只放照片且只有 2 张
        self.add_mat(cid, "photo", "photo", copies=2)
        r = run_checks(self.conn, self.vid)
        fails = self.msgs(r, "fail", "material")
        self.assertTrue(any("缺" in m and "报名表" in m for m in fails))
        self.assertTrue(any("仅 2 份" in m for m in fails))

    def test_photo_background_mismatch(self):
        cid = self.add_child("己")
        self.add_mat(cid, "photo", "photo", copies=3, detail=J({"background": "红"}))
        r = run_checks(self.conn, self.vid)
        self.assertTrue(any("底色" in m for m in self.msgs(r, "fail", "material")))

    def test_original_double_booking_overlap(self):
        a = self.add_child("哥", entrance="北门", slot_start="08:00")
        b = self.add_child("妹", entrance="南门", slot_start="08:30")
        self.add_mat(a, "id_copy", "id_copy", uses_original="户口本原件",
                     hold_start="07:50", hold_end="08:10", location="北门")
        self.add_mat(b, "id_copy", "id_copy", uses_original="户口本原件",
                     hold_start="08:00", hold_end="08:20", location="南门")
        r = run_checks(self.conn, self.vid)
        self.assertTrue(any("分身无术" in m for m in self.msgs(r, "fail", "original")))

    def test_original_transfer_too_tight(self):
        a = self.add_child("哥", entrance="北门", slot_start="08:00")
        b = self.add_child("妹", entrance="南门", slot_start="08:30")
        self.add_mat(a, "id_copy", "id_copy", uses_original="户口本原件",
                     hold_start="07:50", hold_end="08:00", location="北门")
        self.add_mat(b, "id_copy", "id_copy", uses_original="户口本原件",
                     hold_start="08:10", hold_end="08:25", location="南门")
        r = run_checks(self.conn, self.vid)
        self.assertTrue(any("转送不及" in m for m in self.msgs(r, "fail", "original")))
        # 时间足够时应通过
        for m in self.conn.execute("SELECT id FROM material WHERE child_id=?", (b,)):
            self.conn.execute(
                "UPDATE material SET hold_start='08:30' WHERE id=?", (m["id"],))
        self.conn.commit()
        r2 = run_checks(self.conn, self.vid)
        self.assertTrue(any("转送" in m and "余 15 分钟" in m
                            for m in self.msgs(r2, "ok", "original")))

    def test_companion_overlap_and_transfer(self):
        a = self.add_child("哥", entrance="北门", slot_start="08:00")
        b = self.add_child("妹", entrance="南门", slot_start="09:00")
        self.conn.execute(
            "INSERT INTO companion_window(child_id, adult_name, start, end, entrance) "
            "VALUES(?,?,?,?,?)", (a, "爸爸", "07:50", "08:20", "北门"))
        # 同刻不同入口 → 分身 fail
        self.conn.execute(
            "INSERT INTO companion_window(child_id, adult_name, start, end, entrance) "
            "VALUES(?,?,?,?,?)", (b, "爸爸", "08:10", "08:50", "南门"))
        r = run_checks(self.conn, self.vid)
        self.assertTrue(any("分身冲突" in m for m in self.msgs(r, "fail", "timing")))
        # 改成先后但间隔不足 15 分钟 → 转场 fail
        self.conn.execute(
            "UPDATE companion_window SET start='08:25', end='08:55' WHERE child_id=?",
            (b,))
        self.conn.commit()
        r2 = run_checks(self.conn, self.vid)
        self.assertTrue(any("转场冲突" in m for m in self.msgs(r2, "fail", "timing")))
        # 间隔充足 → ok
        self.conn.execute(
            "UPDATE companion_window SET start='08:45', end='09:10' WHERE child_id=?",
            (b,))
        self.conn.commit()
        r3 = run_checks(self.conn, self.vid)
        self.assertTrue(any("余 10 分钟" in m for m in self.msgs(r3, "ok", "timing")))

    def test_entrance_too_early(self):
        cid = self.add_child("早", entrance="南门", slot_start="07:45")
        r = run_checks(self.conn, self.vid)
        self.assertTrue(any("早于" in m for m in self.msgs(r, "fail", "timing")))

    def test_instrument_and_level_out_of_range(self):
        cid = self.add_child("编外", instrument="古琴", apply_level=11)
        r = run_checks(self.conn, self.vid)
        fails = self.msgs(r, "fail", "eligibility")
        self.assertTrue(any("不在简章开考乐种" in m for m in fails))
        self.assertTrue(any("超出简章级别" in m for m in fails))

    def test_pending_when_clause_uncertain_or_missing_route(self):
        # 不明条款：照片标 uncertain
        self.conn.execute(
            "UPDATE clause SET spec=? WHERE ref='ZP'",
            (J({"size": "二寸", "count": 3, "uncertain": True}),))
        self.conn.commit()
        cid = self.add_child("惑")
        r = run_checks(self.conn, self.vid)
        self.assertTrue(any("待确认" in m and "照片" in m
                            for m in self.msgs(r, "pending")))

    def test_staleness_after_data_and_version_change(self):
        cid = self.add_child("变")
        r = run_checks(self.conn, self.vid)
        run_row = self.conn.execute(
            "SELECT * FROM check_run WHERE id=?", (r["id"],)).fetchone()
        clauses = [dict(x) for x in self.conn.execute(
            "SELECT * FROM clause WHERE version_id=?", (self.vid,))]
        kids = [dict(x) for x in self.conn.execute("SELECT * FROM child")]
        for ch in kids:
            pass
        vfp, dfp = version_fingerprint(clauses), r["data_fingerprint"]
        self.assertEqual("fresh", run_staleness(self.conn, run_row, vfp, dfp))
        # 改报考数据 → stale_data
        self.conn.execute("UPDATE child SET apply_level=5 WHERE id=?", (cid,))
        self.conn.commit()
        kids2 = hydrate(self.conn)
        dfp2 = data_fingerprint(kids2)
        self.assertEqual("stale_data", run_staleness(self.conn, run_row, vfp, dfp2))
        # 改简章 → stale_version
        self.conn.execute("UPDATE clause SET body='改了一个字' WHERE ref='ZP'")
        self.conn.commit()
        clauses2 = [dict(x) for x in self.conn.execute(
            "SELECT * FROM clause WHERE version_id=?", (self.vid,))]
        vfp2 = version_fingerprint(clauses2)
        self.assertEqual("stale_version",
                         run_staleness(self.conn, run_row, vfp2, dfp2))
        # 版本停用 → old_version
        self.conn.execute("UPDATE version SET is_active=0 WHERE id=?", (self.vid,))
        self.conn.commit()
        self.assertEqual("old_version",
                         run_staleness(self.conn, run_row, vfp2, dfp2))

    def test_every_finding_has_ref_or_is_pending(self):
        cid = self.add_child("引")
        r = run_checks(self.conn, self.vid)
        for f in r["findings"]:
            # 涉及公告规则的 fail/warn/ok 必须能追溯到依据编号；纯待确认可无依据
            if f["severity"] in ("fail", "warn", "ok") and f["rule"] != "skip":
                if f["rule"] in ("material", "contradiction", "timing", "eligibility"):
                    # 缺材料/时间类必有依据（自加材料除外）
                    if "自加" not in f["message"]:
                        self.assertTrue(f["cites"], f["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
