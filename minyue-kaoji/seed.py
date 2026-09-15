"""灌入示例简章与一对兄妹的报考数据，便于直接演示。

    python seed.py            # 仅在空库时灌入
    python seed.py --reset    # 删库重建后灌入
"""
from __future__ import annotations

import json
import sys

from db import DB_PATH, get_db, init_db

J = lambda d: json.dumps(d, ensure_ascii=False)

CLAUSES = [
    # category, ref, title, body, spec, sort
    ("instrument", "LZ-01", "开考乐种",
     "本次开考：古筝、二胡、琵琶、竹笛、扬琴。",
     J({"instruments": ["古筝", "二胡", "琵琶", "竹笛", "扬琴"]}), 1),
    ("level", "JB-01", "级别设置",
     "各乐种均设 1—10 级；10 级须加试乐理（另行通知）。",
     J({"min": 1, "max": 10}), 2),
    ("skip", "TJ-01", "跳级凭证（3—7 级）",
     "报考 3—7 级者允许跳级，但须持本乐种前一级（含）以上社会艺术水平考级证书原件，"
     "并加试所报级别前一级的一首曲目。",
     J({"levels": [3, 7], "need_level_from": "skip_from", "need_original": True,
        "extra_required": True}), 3),
    ("skip", "TJ-02", "跳级凭证（8—10 级）",
     "报考 8 级（含）以上者不得跳级超过两级；须持本乐种前两级内证书原件，且加试两首前一级曲目。",
     J({"levels": [8, 10], "need_level": 6, "need_original": True,
        "extra_required": True}), 4),
    ("photo", "ZP-01", "照片规格",
     "交本人近期二寸免冠蓝底彩色证件照 3 张，背面用正楷写明姓名、乐种、级别。",
     J({"size": "二寸", "count": 3, "background": "蓝", "color": "彩色"}), 5),
    ("form", "ZB-01", "报名表与签章",
     "统一使用简章附表，一式两份；内容须与准考证一致，由考生监护人签字并加盖报名点公章。",
     J({"copies": 2, "require_sign": True, "require_seal": True}), 6),
    ("id_copy", "ZJ-01", "证件复印件份数",
     "交考生户口本本人页复印件 1 份；跳级考生须同时携带户口本原件到场核验。",
     J({"copies": 1, "doc": "户口本", "need_original": True}), 7),
    ("slot", "HK-01", "候考时段",
     "考生按准考证时段提前 30 分钟到相应入口候考，迟到 15 分钟视为弃考。",
     J({"lead_minutes": 30, "late_minutes": 15}), 8),
    ("entrance", "RK-01", "北门（民乐考场 A 区）",
     "北门考试日 07:30 开放，通往古筝、二胡考场。",
     J({"name": "北门", "open_after": "07:30"}), 9),
    ("entrance", "RK-02", "南门（民乐考场 B 区）",
     "南门考试日 08:00 开放，通往琵琶、竹笛考场。",
     J({"name": "南门", "open_after": "08:00"}), 10),
    ("route", "XL-01", "南北门步行时间",
     "北门至南门沿校内步道步行约 15 分钟，无校内摆渡车。",
     J({"pairs": [["北门", "南门", 15]]}), 11),
    ("note", "QT-01", "原件交还",
     "跳级证书原件、户口本原件核验后在各入口考务台当场发还，请妥善保管。",
     J({}), 12),
]


def reset_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


def seed():
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO version(title, issuer, published, note, is_active) "
            "VALUES (?,?,?,?,1)",
            ("2026 年暑期民乐考级报考简章", "市青少年艺术考级中心",
             "2026-06-20", "纸质简章，家长自行核对录入；条款以考点公告为准。"))
        vid = cur.lastrowid
        for category, ref, title, body, sp, order in CLAUSES:
            conn.execute(
                "INSERT INTO clause(version_id, category, ref, title, body, spec, sort_order) "
                "VALUES (?,?,?,?,?,?,?)",
                (vid, category, ref, title, body, sp, order))

        # 哥哥：二胡，6 级跳报 8 级，凭 6 级证书原件 —— 基本满足
        c1 = conn.execute(
            "INSERT INTO child(name, instrument, apply_level, skip_from, exam_date, "
            "slot_start, slot_end, entrance, exam_number, birth_date, id_type, id_number, "
            "guardian, bag_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
            ("林知远", "二胡", 8, 6, "2026-07-12", "08:00", "09:00", "北门",
             "MY20260712088", "2011-03-04", "户口本", "H-1101...", "林建国")).lastrowid
        conn.execute(
            "INSERT INTO cert(child_id, instrument, level, issuer, has_original) "
            "VALUES (?,?,?,?,1)",
            (c1, "二胡", 6, "市青少年艺术考级中心"))
        conn.execute(
            "INSERT INTO piece(child_id, title, is_extra, ready) VALUES (?,?,1,1)",
            (c1, "《良宵》（前一级加试）"))
        conn.execute(
            "INSERT INTO piece(child_id, title, is_extra, ready) VALUES (?,?,0,1)",
            (c1, "《二泉映月》"))

        # 弟弟：古筝，3 级跳报 4 级，但只登记了 2 级证书 —— 触发跳级 fail
        c2 = conn.execute(
            "INSERT INTO child(name, instrument, apply_level, skip_from, exam_date, "
            "slot_start, slot_end, entrance, exam_number, birth_date, id_type, id_number, "
            "guardian, bag_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,2)",
            ("林知微", "古筝", 4, 3, "2026-07-12", "08:20", "09:10", "南门",
             "MY20260712132", "2014-09-21", "户口本", "H-1101...", "林建国")).lastrowid
        conn.execute(
            "INSERT INTO cert(child_id, instrument, level, issuer, has_original) "
            "VALUES (?,?,?,?,1)",
            (c2, "古筝", 2, "区少年宫"))
        conn.execute(
            "INSERT INTO piece(child_id, title, is_extra, ready) VALUES (?,?,1,0)",
            (c2, "《渔舟唱晚》（前一级加试，尚未练成）"))

        # 哥哥材料：报名表（已签章且字段一致）、照片缺 1 张、户口本复印件、跳级证书原件
        conn.execute(
            "INSERT INTO material(child_id, req_key, mtype, label, status, copies, "
            "uses_original, hold_start, hold_end, location, detail, bag_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (c1, "form", "form", "林知远 报名表 ×2", "ok", 2, "",
             "07:40", "07:55", "北门",
             J({"name": "林知远", "instrument": "二胡", "apply_level": 8,
                "exam_number": "MY20260712088", "signed": True, "sealed": True}), 1))
        conn.execute(
            "INSERT INTO material(child_id, req_key, mtype, label, status, copies, "
            "uses_original, hold_start, hold_end, location, detail, bag_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (c1, "photo", "photo", "林知远 二寸蓝底照片", "partial", 2, "",
             "", "", "", J({"background": "蓝"}), 2))
        conn.execute(
            "INSERT INTO material(child_id, req_key, mtype, label, status, copies, "
            "uses_original, hold_start, hold_end, location, detail, bag_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (c1, "id_copy", "id_copy", "林知远 户口本复印件", "ok", 1,
             "户口本原件", "07:40", "07:55", "北门", "{}", 3))
        conn.execute(
            "INSERT INTO material(child_id, req_key, mtype, label, status, copies, "
            "uses_original, hold_start, hold_end, location, detail, bag_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (c1, "cert:skip", "cert", "林知远 二胡6级证书原件", "ok", 1,
             "证书(二胡6级)", "07:45", "08:00", "北门", "{}", 4))

        # 弟弟材料：报名表级别被错填成 3 级且未盖章（字段矛盾）；照片蓝底但 3 张齐
        conn.execute(
            "INSERT INTO material(child_id, req_key, mtype, label, status, copies, "
            "uses_original, hold_start, hold_end, location, detail, bag_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (c2, "form", "form", "林知微 报名表 ×2", "ok", 2, "",
             "08:05", "08:20", "南门",
             J({"name": "林知微", "instrument": "古筝", "apply_level": 3,
                "exam_number": "MY20260712132", "signed": True, "sealed": False}), 1))
        conn.execute(
            "INSERT INTO material(child_id, req_key, mtype, label, status, copies, "
            "uses_original, hold_start, hold_end, location, detail, bag_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (c2, "photo", "photo", "林知微 二寸蓝底照片", "ok", 3, "",
             "", "", "", J({"background": "蓝"}), 2))
        conn.execute(
            "INSERT INTO material(child_id, req_key, mtype, label, status, copies, "
            "uses_original, hold_start, hold_end, location, detail, bag_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (c2, "id_copy", "id_copy", "林知微 户口本复印件", "ok", 1,
             "户口本原件", "08:05", "08:25", "南门", "{}", 3))

        # 同行安排：爸爸一人先送哥哥（北门 07:40–08:10），再赶南门陪弟弟（08:20 起）
        # —— 15 分钟步行、仅 10 分钟间隔，触发转场 fail
        conn.execute(
            "INSERT INTO companion_window(child_id, adult_name, start, end, entrance) "
            "VALUES (?,?,?,?,?)",
            (c1, "林建国（爸爸）", "07:40", "08:10", "北门"))
        conn.execute(
            "INSERT INTO companion_window(child_id, adult_name, start, end, entrance) "
            "VALUES (?,?,?,?,?)",
            (c2, "林建国（爸爸）", "08:20", "09:10", "南门"))

        # 户口本原件同时被哥哥（北门 07:40–07:55）和弟弟（南门 08:05–08:25）使用
        # —— 不重叠但 10 分钟 < 15 分钟步行，触发原件转送 fail

        conn.commit()
        print(f"已灌入简章 v{vid} 与 2 名孩子的示例数据。")
    finally:
        conn.close()


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset_db()
        seed()
    else:
        init_db()
        conn = get_db()
        empty = conn.execute("SELECT COUNT(*) c FROM version").fetchone()["c"] == 0
        conn.close()
        if empty:
            seed()
        else:
            print("数据库已有数据，未改动。用 python seed.py --reset 重建。")
