"""核查引擎：跳级条件、字段矛盾、材料缺漏、原件占用、兄妹候考与跨入口冲突。

每条 finding：
  rule      eligibility / skip / material / contradiction / original / timing
  severity  fail / warn / ok / pending
  message   结论文字
  cites     公告依据 [{cid, ref, title}]
  child_id  涉及孩子（可空）
  req_key   涉及清单键（可空）
"""
from __future__ import annotations

import json
from collections import defaultdict

from db import fingerprint

STATUS_OK, STATUS_PARTIAL, STATUS_MISSING = "ok", "partial", "missing"

CATEGORIES = {
    "instrument": "乐种",
    "level": "级别",
    "skip": "跳级凭证",
    "photo": "照片规格",
    "form": "纸表签章",
    "id_copy": "证件份数",
    "slot": "候考时段",
    "entrance": "入口开放",
    "route": "跨入口步行",
    "note": "其他脚注",
}

# 纸表 detail JSON 键 -> (孩子字段, 中文名)
FORM_FIELDS = {
    "name": ("name", "姓名"),
    "instrument": ("instrument", "乐种"),
    "apply_level": ("apply_level", "报考级别"),
    "exam_number": ("exam_number", "准考证号"),
    "birth_date": ("birth_date", "出生日期"),
    "id_number": ("id_number", "证件号码"),
    "guardian": ("guardian", "监护人"),
}


# ---------------------------------------------------------------- 基础工具

def cite(clause) -> dict:
    return {"cid": clause["id"], "ref": clause["ref"], "title": clause["title"]}


def to_min(hhmm):
    """'08:30' -> 510；无法解析返回 None。"""
    if not hhmm:
        return None
    try:
        h, m = str(hhmm).strip().split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def hhmm(minutes):
    if minutes is None:
        return ""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def overlap(a_start, a_end, b_start, b_end) -> bool:
    s1, e1, s2, e2 = map(to_min, (a_start, a_end, b_start, b_end))
    if None in (s1, e1, s2, e2):
        return False
    return s1 < e2 and s2 < e1


def group_clauses(clauses):
    grouped = defaultdict(list)
    for row in clauses:
        grouped[row["category"]].append(row)
    return grouped


def spec(clause) -> dict:
    try:
        return json.loads(clause["spec"] or "{}")
    except (ValueError, TypeError):
        return {}


# ---------------------------------------------------------------- 乐种与级别

def check_eligibility(child, grouped, add):
    instrument = child["instrument"]
    level = child["apply_level"]
    instr_clauses = grouped.get("instrument", [])
    level_clauses = grouped.get("level", [])

    if instrument:
        covered = None
        for c in instr_clauses:
            sp = spec(c)
            names = sp.get("instruments") or []
            if not names or instrument in names:
                covered = c
                break
        if covered is None:
            add("eligibility", "fail",
                f"{child['name']} 报考乐种“{instrument}”不在简章开考乐种范围内",
                child_id=child["id"],
                cites=[cite(c) for c in instr_clauses])
        elif spec(covered).get("uncertain"):
            add("eligibility", "pending",
                f"{child['name']}：乐种条款“{covered['ref']}”含不明项，开考范围待确认",
                child_id=child["id"], cites=[cite(covered)])
    else:
        add("eligibility", "pending", f"{child['name']}：尚未填写报考乐种",
            child_id=child["id"])

    if level is None:
        add("eligibility", "pending", f"{child['name']}：尚未填写报考级别",
            child_id=child["id"])
    elif level_clauses:
        matched = None
        for c in level_clauses:
            sp = spec(c)
            lo, hi = sp.get("min"), sp.get("max")
            if (lo is None or level >= int(lo)) and (hi is None or level <= int(hi)):
                instrs = sp.get("instruments") or []
                if not instrs or instrument in instrs:
                    matched = c
                    break
        if matched is None:
            add("eligibility", "fail",
                f"{child['name']} 报考 {instrument}{level} 级，超出简章级别设置范围",
                child_id=child["id"],
                cites=[cite(c) for c in level_clauses])
        elif spec(matched).get("uncertain"):
            add("eligibility", "pending",
                f"{child['name']}：级别条款“{matched['ref']}”含不明项，级别范围待确认",
                child_id=child["id"], cites=[cite(matched)])


# ---------------------------------------------------------------- 清单需求

def requirements_for(child, grouped, add):
    """根据简章条款 + 报考信息生成应备材料需求，返回 (reqs, is_skip, skip_clause)。"""
    reqs = []
    cid = child["id"]
    instrument = child["instrument"]
    apply_level = child["apply_level"]
    skip_from = child["skip_from"]
    is_skip = bool(skip_from and apply_level and int(skip_from) < int(apply_level))
    skip_clauses = grouped.get("skip", [])

    # 报名纸表
    form_clauses = grouped.get("form", [])
    if form_clauses:
        c = form_clauses[0]
        sp = spec(c)
        reqs.append({
            "child_id": cid, "req_key": "form", "mtype": "form",
            "label": f"{child['name']} 报名表（纸表签章）",
            "copies": int(sp.get("copies") or 1),
            "uses_original": "",
            "uncertain": bool(sp.get("uncertain")),
            "cites": [cite(c)],
        })
    else:
        add("material", "pending",
            f"{child['name']}：简章未见纸表签章条款，报名表要求待确认",
            child_id=cid, req_key="form")
        reqs.append({
            "child_id": cid, "req_key": "form", "mtype": "form",
            "label": f"{child['name']} 报名表（要求待确认）",
            "copies": 1, "uses_original": "", "uncertain": True, "cites": [],
        })

    # 照片
    photo_clauses = grouped.get("photo", [])
    if photo_clauses:
        c = photo_clauses[0]
        sp = spec(c)
        if sp.get("uncertain"):
            add("material", "pending",
                f"{child['name']}：照片规格条款“{c['ref']}”有不明项（{c['title']}），"
                f"需向考点确认",
                child_id=cid, req_key="photo", cites=[cite(c)])
        spec_text = sp.get("size") or sp.get("spec_text") or c["title"]
        reqs.append({
            "child_id": cid, "req_key": "photo", "mtype": "photo",
            "label": f"{child['name']} 照片（{spec_text}）",
            "copies": int(sp.get("count") or 1),
            "uses_original": "",
            "uncertain": bool(sp.get("uncertain")),
            "cites": [cite(c)],
        })
    else:
        add("material", "pending",
            f"{child['name']}：简章未见照片规格条款，照片要求待确认",
            child_id=cid, req_key="photo")
        reqs.append({
            "child_id": cid, "req_key": "photo", "mtype": "photo",
            "label": f"{child['name']} 照片（要求待确认）",
            "copies": 1, "uses_original": "", "uncertain": True, "cites": [],
        })

    # 证件复印件份数
    idc_clauses = grouped.get("id_copy", [])
    if idc_clauses:
        c = idc_clauses[0]
        sp = spec(c)
        copies = int(sp.get("copies") or 1)
        doc = sp.get("doc") or child["id_type"] or "证件"
        reqs.append({
            "child_id": cid, "req_key": "id_copy", "mtype": "id_copy",
            "label": f"{child['name']} {doc}复印件 ×{copies}",
            "copies": copies,
            "uses_original": f"{doc}原件" if sp.get("need_original") else "",
            "uncertain": bool(sp.get("uncertain")),
            "cites": [cite(c)],
        })
        if sp.get("uncertain"):
            add("material", "pending",
                f"{child['name']}：证件份数条款“{c['ref']}”有不明项，需向考点确认",
                child_id=cid, req_key="id_copy", cites=[cite(c)])
    else:
        add("material", "pending",
            f"{child['name']}：简章未见证件份数条款，复印件要求待确认",
            child_id=cid, req_key="id_copy")
        reqs.append({
            "child_id": cid, "req_key": "id_copy", "mtype": "id_copy",
            "label": f"{child['name']} 证件复印件（要求待确认）",
            "copies": 1, "uses_original": "", "uncertain": True, "cites": [],
        })

    matched_clause = None
    if is_skip:
        matched = None
        for c in skip_clauses:
            sp = spec(c)
            levels = sp.get("levels")
            instrs = sp.get("instruments") or []
            if levels:
                lo, hi = int(levels[0]), int(levels[1])
                if lo <= apply_level <= hi and (not instrs or instrument in instrs):
                    matched, matched_clause = sp, c
                    break
            elif not instrs or instrument in instrs:
                matched, matched_clause = sp, c
                break

        if matched is None:
            if skip_clauses:
                add("skip", "fail",
                    f"{child['name']} 报 {instrument}{apply_level} 级（{skip_from}级跳报），"
                    f"简章跳级条款未覆盖该乐种/级别，不允许如此报考，需改报或向考点确认",
                    child_id=cid, cites=[cite(c) for c in skip_clauses])
            else:
                add("skip", "pending",
                    f"{child['name']} 拟从 {skip_from} 级跳报 {apply_level} 级，"
                    f"简章未见跳级凭证条款，能否报考待确认",
                    child_id=cid)
            cert_uncertain = True
            cert_cites = [cite(c) for c in skip_clauses]
            need_original = True
        else:
            need_level = int(matched.get("need_level", skip_from))
            need_original = bool(matched.get("need_original", True))
            cert_uncertain = bool(matched.get("uncertain"))
            cert_cites = [cite(matched_clause)]

            held = [r["level"] for r in child["certs"]
                    if r["level"] is not None
                    and (not matched.get("instruments") or r["instrument"] == instrument)]
            best = max(held, default=None)
            if best is None:
                add("skip", "fail",
                    f"{child['name']} 跳报 {apply_level} 级：未登记任何 {instrument} 已有证书，"
                    f"依“{matched_clause['ref']}”须持 {need_level} 级（含）以上证书",
                    child_id=cid, req_key="cert:skip", cites=cert_cites)
            elif best < need_level:
                add("skip", "fail",
                    f"{child['name']} 跳报 {apply_level} 级：已登记最高仅 {best} 级，"
                    f"依“{matched_clause['ref']}”须持 {need_level} 级（含）以上",
                    child_id=cid, req_key="cert:skip", cites=cert_cites)
            else:
                add("skip", "ok",
                    f"{child['name']} 持有 {instrument}{best} 级证书，满足"
                    f"“{matched_clause['ref']}”跳报 {apply_level} 级的级别要求",
                    child_id=cid, req_key="cert:skip", cites=cert_cites)

            if matched.get("extra_required"):
                extras = [p for p in child["pieces"] if p["is_extra"]]
                if not extras:
                    add("skip", "fail",
                        f"{child['name']} 跳级须按“{matched_clause['ref']}”加试前一级曲目，"
                        f"尚未登记加试曲目",
                        child_id=cid, cites=cert_cites)
                elif not all(p["ready"] for p in extras):
                    add("skip", "pending",
                        f"{child['name']} 已登记加试曲目，但标记为尚未练成，赴考前确认",
                        child_id=cid, cites=cert_cites)
                else:
                    add("skip", "ok",
                        f"{child['name']} 已登记加试曲目并练成，符合“{matched_clause['ref']}”",
                        child_id=cid, cites=cert_cites)
            if cert_uncertain:
                add("skip", "pending",
                    f"{child['name']}：跳级条款“{matched_clause['ref']}”含不明项，"
                    f"需向考点确认后结论才作数",
                    child_id=cid, cites=cert_cites)

        reqs.append({
            "child_id": cid, "req_key": "cert:skip", "mtype": "cert",
            "label": f"{child['name']} {instrument}{skip_from}级证书原件（跳级凭证）",
            "copies": 1,
            "uses_original": f"证书({instrument}{skip_from}级)" if need_original else "",
            "uncertain": cert_uncertain,
            "cites": cert_cites,
        })
    else:
        held = [r for r in child["certs"]
                if r["instrument"] == instrument and r["level"] is not None]
        if held and apply_level is not None:
            best = max(r["level"] for r in held)
            if best < apply_level - 1:
                add("skip", "warn",
                    f"{child['name']} 登记为逐级报考 {apply_level} 级，已登记最高为 {best} 级，"
                    f"中间级别凭证未见；若简章要求逐级请确认",
                    child_id=cid)

    return reqs, is_skip, matched_clause


# ---------------------------------------------------------------- 材料核查

def check_materials(child, reqs, grouped, add):
    by_key = defaultdict(list)
    for m in child["materials"]:
        by_key[m["req_key"] or f"x{m['id']}"].append(m)

    req_map = {r["req_key"]: r for r in reqs}

    for req in reqs:
        rows = by_key.get(req["req_key"], [])
        if not rows:
            sev = "pending" if req["uncertain"] else "fail"
            tail = "（条款待确认，暂不判缺）" if req["uncertain"] else "，须补齐再赴考"
            add("material", sev,
                f"{child['name']}：缺《{req['label']}》{tail}",
                child_id=child["id"], req_key=req["req_key"], cites=req["cites"])
            continue
        for m in rows:
            label = m["label"] or req["label"]
            if m["status"] == STATUS_MISSING:
                add("material", "fail",
                    f"{child['name']}：《{label}》状态为未备齐",
                    child_id=child["id"], req_key=req["req_key"], cites=req["cites"])
            elif m["status"] == STATUS_PARTIAL:
                add("material", "warn",
                    f"{child['name']}：《{label}》部分备齐，出发前清点",
                    child_id=child["id"], req_key=req["req_key"], cites=req["cites"])
            else:
                add("material", "ok", f"{child['name']}：《{label}》已备齐",
                    child_id=child["id"], req_key=req["req_key"], cites=req["cites"])
            if m["copies"] < req["copies"]:
                add("material", "fail",
                    f"{child['name']}：《{label}》仅 {m['copies']} 份，"
                    f"公告要求 {req['copies']} 份",
                    child_id=child["id"], req_key=req["req_key"], cites=req["cites"])

            detail = {}
            try:
                detail = json.loads(m["detail"] or "{}")
            except ValueError:
                detail = {}

            if m["mtype"] == "form":
                for key, (field, zh) in FORM_FIELDS.items():
                    val = detail.get(key)
                    if val not in (None, ""):
                        want = child[field]
                        if want is not None and str(val).strip() != str(want):
                            add("contradiction", "fail",
                                f"{child['name']} 报名表“{zh}”填 {val}，"
                                f"与报考登记 {want} 不一致，纸表字段矛盾需重填",
                                child_id=child["id"], req_key=req["req_key"],
                                cites=req["cites"])
                form_sp = spec(grouped["form"][0]) if grouped.get("form") else {}
                if m["status"] == STATUS_OK:
                    if form_sp.get("require_seal", True) and detail.get("sealed") is False:
                        add("contradiction", "fail",
                            f"{child['name']} 报名表未盖章，纸表签章不全",
                            child_id=child["id"], req_key=req["req_key"], cites=req["cites"])
                    if form_sp.get("require_sign", True) and detail.get("signed") is False:
                        add("contradiction", "fail",
                            f"{child['name']} 报名表未签字，纸表签章不全",
                            child_id=child["id"], req_key=req["req_key"], cites=req["cites"])

            if m["mtype"] == "photo" and m["status"] == STATUS_OK:
                bg = detail.get("background")
                photo_clause = grouped.get("photo", [None])[0]
                if bg and photo_clause is not None:
                    want_bg = spec(photo_clause).get("background")
                    if want_bg and bg != want_bg:
                        add("material", "fail",
                            f"{child['name']} 照片底色为 {bg}，"
                            f"“{photo_clause['ref']}”要求 {want_bg} 底",
                            child_id=child["id"], req_key=req["req_key"],
                            cites=[cite(photo_clause)])

    for m in child["materials"]:
        if not m["req_key"]:
            if m["status"] == STATUS_MISSING:
                add("material", "fail",
                    f"{child['name']}：自加材料《{m['label']}》未备齐", child_id=child["id"])
            elif m["status"] == STATUS_PARTIAL:
                add("material", "warn",
                    f"{child['name']}：自加材料《{m['label']}》部分备齐", child_id=child["id"])


def check_cert_original(child, add):
    """声明携原件的跳级证书材料，核对登记证书确有原件。"""
    for m in child["materials"]:
        if m["mtype"] != "cert" or m["req_key"] != "cert:skip" or not m["uses_original"]:
            continue
        target = next((r for r in child["certs"]
                       if f"证书({r['instrument']}{r['level']}级)" == m["uses_original"]), None)
        if target is None:
            add("material", "fail",
                f"{child['name']}：《{m['label']}》声明携带“{m['uses_original']}”，"
                f"但已有证书登记中找不到对应项，原件来源不明",
                child_id=child["id"], req_key="cert:skip")
        elif not target["has_original"]:
            add("material", "fail",
                f"{child['name']}：{target['instrument']}{target['level']}级证书"
                f"登记为无原件，跳级交验会被拒，须先取回或补办原件",
                child_id=child["id"], req_key="cert:skip")


# ---------------------------------------------------------------- 入口与时间

def check_entrance_open(child, grouped, add):
    entrances = grouped.get("entrance", [])
    if not entrances:
        add("timing", "pending",
            f"{child['name']}：简章未录入口开放脚注，{child['exam_date']} "
            f"{child['slot_start']} 到 {child['entrance'] or '入口'} 是否可进入待确认",
            child_id=child["id"])
        return
    by_name = {spec(c).get("name") or c["title"]: c for c in entrances}
    targets = [("候考", child["slot_start"], child["entrance"])]
    for w in child["windows"]:
        targets.append((f"同行人{w['adult_name']}", w["start"],
                        w["entrance"] or child["entrance"]))
    for who, start, ent in targets:
        if not start:
            continue
        c = by_name.get(ent)
        if c is None:
            add("timing", "pending",
                f"{child['name']}：入口“{ent or '未填'}”在简章中无开放脚注，待确认",
                child_id=child["id"], cites=[cite(x) for x in entrances])
            continue
        open_min, start_min = to_min(spec(c).get("open_after")), to_min(start)
        if open_min is None:
            add("timing", "pending",
                f"{child['name']} {who} 走“{c['title']}”，开放时刻未录，到达时间待确认",
                child_id=child["id"], cites=[cite(c)])
        elif start_min < open_min:
            add("timing", "fail",
                f"{child['name']} {who} {start} 到达 {ent}，早于“{c['ref']}”开放时间"
                f" {spec(c).get('open_after')}，进不去",
                child_id=child["id"], cites=[cite(c)])
        else:
            add("timing", "ok",
                f"{child['name']} {who} {start} 到 {ent}，入口已开放（{c['ref']}）",
                child_id=child["id"], cites=[cite(c)])


def route_table(grouped):
    """{入口A: {入口B: 分钟}}。"""
    table = defaultdict(dict)
    for c in grouped.get("route", []):
        sp = spec(c)
        for pair in sp.get("pairs", []):
            a, b, mins = pair[0], pair[1], int(pair[2])
            table[a][b] = mins
            table[b][a] = mins
    return dict(table)


def walk_minutes(routes, a, b):
    if a == b:
        return 0
    return routes.get(a, {}).get(b)


# ---------------------------------------------------------------- 兄妹陪护

def check_companions(children, grouped, add):
    routes = route_table(grouped)
    route_cites = [cite(c) for c in grouped.get("route", [])]

    adults = defaultdict(list)  # 成人 -> [(child, window)]
    for child in children:
        for w in child["windows"]:
            adults[w["adult_name"]].append((child, w))

    for adult, items in adults.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                c1, w1 = items[i]
                c2, w2 = items[j]
                if c1["id"] == c2["id"]:
                    continue
                ent1, ent2 = w1["entrance"] or c1["entrance"], w2["entrance"] or c2["entrance"]
                same_place = ent1 == ent2
                if overlap(w1["start"], w1["end"], w2["start"], w2["end"]):
                    if same_place:
                        add("timing", "warn",
                            f"同行人 {adult} 在 {w1['start']}–{w1['end']} 须同时陪护兄妹，"
                            f"同在 {ent1} 可同区照看，但两边叫号可能撞期",
                            child_id=c1["id"])
                    else:
                        add("timing", "fail",
                            f"同行人 {adult} 分身冲突：{c1['name']} "
                            f"{w1['start']}–{w1['end']} 在 {ent1}，{c2['name']} "
                            f"{w2['start']}–{w2['end']} 在 {ent2}，时段重叠且入口不同，"
                            f"一人无法兼顾",
                            child_id=c1["id"], cites=route_cites)
                    continue

                # 不重叠：判断先后转场是否赶得到
                if to_min(w1["end"]) <= to_min(w2["start"]):
                    first, second = (c1, w1, ent1), (c2, w2, ent2)
                else:
                    first, second = (c2, w2, ent2), (c1, w1, ent1)
                need = walk_minutes(routes, first[2], second[2])
                gap = to_min(second[1]["start"]) - to_min(first[1]["end"])
                if need is None:
                    add("timing", "pending",
                        f"同行人 {adult} 需在 {first[1]['end']} 后从 {first[2]} 转往 "
                        f"{second[2]}（{second[0]['name']} {second[1]['start']}），"
                        f"简章未录该段步行时间，能否赶到待确认",
                        child_id=first[0]["id"], cites=route_cites)
                elif gap < need:
                    add("timing", "fail",
                        f"同行人 {adult} 转场冲突：{first[0]['name']} "
                        f"{first[1]['start']}–{first[1]['end']} 在 {first[2]}，"
                        f"转往 {second[2]} 陪 {second[0]['name']} {second[1]['start']} 候考，"
                        f"步行需 {need} 分钟、间隔仅 {max(gap, 0)} 分钟，赶不到",
                        child_id=first[0]["id"], cites=route_cites)
                else:
                    add("timing", "ok",
                        f"同行人 {adult} 可先陪 {first[0]['name']}（{first[2]}），"
                        f"{first[1]['end']} 后步行 {need} 分钟转往 {second[2]} 陪 "
                        f"{second[0]['name']}，余 {gap - need} 分钟",
                        child_id=first[0]["id"], cites=route_cites)

    for child in children:
        if not child["windows"]:
            add("timing", "pending",
                f"{child['name']}：未登记同行成人候考安排，兄妹如何分流待确认",
                child_id=child["id"])


# ---------------------------------------------------------------- 原件占用

def check_originals(children, grouped, add):
    routes = route_table(grouped)
    route_cites = [cite(c) for c in grouped.get("route", [])]
    by_original = defaultdict(list)
    for child in children:
        for m in child["materials"]:
            if m["uses_original"]:
                by_original[m["uses_original"]].append((m, child))
                if not (m["hold_start"] and m["hold_end"]):
                    add("original", "pending",
                        f"{child['name']}：《{m['label']}》占用“{m['uses_original']}”，"
                        f"但未填交验时段，无法判断与另一份材料是否打架",
                        child_id=child["id"])

    pair_rows = []
    for name, items in by_original.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                m1, c1 = items[i]
                m2, c2 = items[j]
                loc1 = m1["location"] or c1["entrance"]
                loc2 = m2["location"] or c2["entrance"]
                pair_rows.append({
                    "original": name,
                    "child_ids": [c1["id"], c2["id"]],
                    "windows": [
                        {"child_id": c1["id"], "name": c1["name"], "label": m1["label"],
                         "start": m1["hold_start"], "end": m1["hold_end"], "location": loc1},
                        {"child_id": c2["id"], "name": c2["name"], "label": m2["label"],
                         "start": m2["hold_start"], "end": m2["hold_end"], "location": loc2},
                    ],
                })
                if c1["id"] == c2["id"]:
                    add("original", "warn",
                        f"{c1['name']} 的两份材料《{m1['label']}》《{m2['label']}》"
                        f"都要用“{name}”，同一孩子交表注意顺序即可",
                        child_id=c1["id"])
                    continue
                if not (m1["hold_start"] and m1["hold_end"]
                        and m2["hold_start"] and m2["hold_end"]):
                    continue
                if overlap(m1["hold_start"], m1["hold_end"], m2["hold_start"], m2["hold_end"]):
                    if loc1 == loc2:
                        add("original", "warn",
                            f"“{name}”同刻被两份材料占用：{c1['name']}《{m1['label']}》"
                            f"{m1['hold_start']}–{m1['hold_end']} 与 {c2['name']}"
                            f"《{m2['label']}》{m2['hold_start']}–{m2['hold_end']}；"
                            f"同在 {loc1}，可一人持原件连交两表",
                            child_id=c1["id"])
                    else:
                        add("original", "fail",
                            f"同一原件“{name}”分身无术：{c1['name']} 须于 "
                            f"{m1['hold_start']}–{m1['hold_end']} 在 {loc1} 交验，"
                            f"{c2['name']} 须于 {m2['hold_start']}–{m2['hold_end']} 在 {loc2} "
                            f"交验，时段重叠且地点不同",
                            child_id=c1["id"])
                else:
                    if to_min(m1["hold_end"]) <= to_min(m2["hold_start"]):
                        first = (c1, m1, loc1)
                        second = (c2, m2, loc2)
                    else:
                        first = (c2, m2, loc2)
                        second = (c1, m1, loc1)
                    need = walk_minutes(routes, first[2], second[2])
                    gap = to_min(second[1]["hold_start"]) - to_min(first[1]["hold_end"])
                    if need is None:
                        add("original", "pending",
                            f"“{name}”需在 {first[1]['hold_end']} 于 {first[2]} 交验后，"
                            f"转送 {second[2]} 供 {second[0]['name']} "
                            f"{second[1]['hold_start']} 使用，该段步行时间未录，是否够待确认",
                            child_id=first[0]["id"], cites=route_cites)
                    elif gap < need:
                        add("original", "fail",
                            f"原件“{name}”转送不及：{first[0]['name']} 在 {first[2]} 用到 "
                            f"{first[1]['hold_end']}，{second[0]['name']} 须 "
                            f"{second[1]['hold_start']} 在 {second[2]} 使用，"
                            f"步行 {need} 分钟、间隔仅 {max(gap, 0)} 分钟",
                            child_id=first[0]["id"], cites=route_cites)
                    else:
                        add("original", "ok",
                            f"“{name}”可从 {first[2]}（{first[0]['name']} 截至 "
                            f"{first[1]['hold_end']}）转送 {second[2]}（{second[0]['name']} "
                            f"{second[1]['hold_start']} 起），步行 {need} 分钟、余 {gap - need} 分钟",
                            child_id=first[0]["id"], cites=route_cites)
    return pair_rows


# ---------------------------------------------------------------- 指纹与主流程

def version_fingerprint(clauses):
    return fingerprint([
        {"category": c["category"], "ref": c["ref"], "title": c["title"],
         "body": c["body"], "spec": c["spec"], "sort_order": c["sort_order"]}
        for c in clauses
    ])


def data_fingerprint(children):
    obj = {"children": []}
    for ch in children:
        obj["children"].append({
            "child": {k: ch[k] for k in (
                "name", "instrument", "apply_level", "skip_from", "exam_date",
                "slot_start", "slot_end", "entrance", "exam_number", "birth_date",
                "id_type", "id_number", "guardian")},
            "certs": [
                {"instrument": r["instrument"], "level": r["level"],
                 "issuer": r["issuer"], "has_original": r["has_original"]}
                for r in ch["certs"]],
            "pieces": [
                {"title": r["title"], "is_extra": r["is_extra"], "ready": r["ready"]}
                for r in ch["pieces"]],
            "materials": [
                {k: r[k] for k in (
                    "req_key", "mtype", "label", "status", "copies", "uses_original",
                    "hold_start", "hold_end", "location", "detail", "bag_order")}
                for r in ch["materials"]],
            "windows": [
                {"adult_name": r["adult_name"], "start": r["start"], "end": r["end"],
                 "entrance": r["entrance"]}
                for r in ch["windows"]],
        })
    return fingerprint(obj)


def earliest_conflict(kids, findings):
    """时间带上最早出问题的节点：该孩子/原件在该时刻存在 fail 结论。"""
    candidates = []
    for ch in kids:
        if ch["slot_start"]:
            candidates.append((to_min(ch["slot_start"]), f"{ch['name']} 候考开始",
                               ch["id"], "slot"))
        for w in ch["windows"]:
            if w["start"]:
                candidates.append((to_min(w["start"]),
                                   f"{w['adult_name']} 陪护 {ch['name']} 到达",
                                   ch["id"], "window"))
        for m in ch["materials"]:
            if m["hold_start"] and m["uses_original"]:
                candidates.append((to_min(m["hold_start"]),
                                   f"{ch['name']} 交验 {m['uses_original']}",
                                   ch["id"], "original"))
    for t, label, cid, kind in sorted(candidates, key=lambda x: (x[0] is None, x[0] or 0)):
        if any(f["severity"] == "fail" and f["child_id"] == cid for f in findings):
            return {"time": hhmm(t), "label": label, "child_id": cid}
    return None


def run_checks(conn, version_id: int) -> dict:
    version = conn.execute("SELECT * FROM version WHERE id=?", (version_id,)).fetchone()
    if version is None:
        raise ValueError("版本不存在")
    clauses = conn.execute(
        "SELECT * FROM clause WHERE version_id=? ORDER BY sort_order, id",
        (version_id,)).fetchall()

    def hydrate():
        rows = conn.execute("SELECT * FROM child ORDER BY bag_order, id").fetchall()
        out = []
        for ch in rows:
            d = dict(ch)
            d["certs"] = [dict(r) for r in conn.execute(
                "SELECT * FROM cert WHERE child_id=? ORDER BY id", (ch["id"],))]
            d["pieces"] = [dict(r) for r in conn.execute(
                "SELECT * FROM piece WHERE child_id=? ORDER BY id", (ch["id"],))]
            d["materials"] = [dict(r) for r in conn.execute(
                "SELECT * FROM material WHERE child_id=? ORDER BY bag_order, id", (ch["id"],))]
            d["windows"] = [dict(r) for r in conn.execute(
                "SELECT * FROM companion_window WHERE child_id=? ORDER BY id", (ch["id"],))]
            out.append(d)
        return out

    kids = hydrate()
    grouped = group_clauses(clauses)
    findings = []

    def add(rule, severity, message, child_id=None, req_key=None, cites=None):
        findings.append({
            "rule": rule, "severity": severity, "message": message,
            "child_id": child_id, "req_key": req_key, "cites": cites or [],
        })

    all_reqs = {}
    for ch in kids:
        check_eligibility(ch, grouped, add)
        reqs, _, _ = requirements_for(ch, grouped, add)
        all_reqs[ch["id"]] = reqs
        check_materials(ch, reqs, grouped, add)
        check_cert_original(ch, add)
        check_entrance_open(ch, grouped, add)

    check_companions(kids, grouped, add)
    original_pairs = check_originals(kids, grouped, add)

    earliest = earliest_conflict(kids, findings)
    carried = sorted({m["uses_original"] for ch in kids for m in ch["materials"]
                      if m["uses_original"]})

    vfp = version_fingerprint(clauses)
    dfp = data_fingerprint(kids)

    cur = conn.execute(
        "INSERT INTO check_run(version_id, version_fingerprint, data_fingerprint, findings, "
        "original_pairs, earliest_conflict, carried_originals) VALUES (?,?,?,?,?,?,?)",
        (version_id, vfp, dfp,
         json.dumps(findings, ensure_ascii=False),
         json.dumps(original_pairs, ensure_ascii=False),
         earliest["time"] if earliest else "",
         json.dumps(carried, ensure_ascii=False)))
    conn.commit()
    return {
        "id": cur.lastrowid, "findings": findings, "requirements": all_reqs,
        "original_pairs": original_pairs, "earliest_conflict": earliest,
        "carried_originals": carried,
        "version_fingerprint": vfp, "data_fingerprint": dfp,
    }


def run_staleness(conn, run_row, current_vfp, current_dfp) -> str:
    """fresh / stale_data / stale_version / old_version"""
    version = conn.execute("SELECT is_active FROM version WHERE id=?",
                           (run_row["version_id"],)).fetchone()
    if version is None or not version["is_active"]:
        return "old_version"
    if run_row["version_fingerprint"] != current_vfp:
        return "stale_version"
    if run_row["data_fingerprint"] != current_dfp:
        return "stale_data"
    return "fresh"
