#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四柱双引擎对拍校验。

两个互相独立的实现同时算一张盘，逐柱比对：
  A. pai_pan.py   —— 本目录下的零依赖自实现（太阳视黄经定气 + 定朔）
  B. lunar_python —— 第三方历法库 6tail/lunar-python（MIT，已装 1.4.8）

四柱全一致 → pass；任一支不一致 → fail 并列出差异柱。

口径约定（2026-11-05 用户拍板）
------------------------------
夜子时（23:00–24:00）以 pai_pan 口径为准：日柱进位到次日。
lunar_python 默认 sect=2（日柱不进位），本脚本统一强制 setSect(1) 对齐，
不做「两版并列」。这条差异是已知的两派口径分歧，不是 bug。

退出码
------
0  pass 全部一致
1  fail 有柱子不一致
3  in_doubt 无法完成比对（时辰未知、库缺失等）

用法
----
    python -I bazi_verify.py --solar 1972-06-09 --hour 12:00 --sex 女
    python -I bazi_verify.py --solar 1990-02-03 --hour 10:00 --sex 男 --json
    python -I bazi_verify.py --solar 1990-05-15 --shichen 午 --sex 男

注意：-I 会屏蔽用户级 site-packages，lunar_python 装在那里，
      所以本脚本内部用 --user 路径兜底导入；直接跑建议不加 -I。
"""

import argparse
import importlib.util
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PAI_PAN_PATH = os.path.join(HERE, "pai_pan.py")

GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"
PILLAR_NAMES = ("年柱", "月柱", "日柱", "时柱")


def load_pai_pan():
    if not os.path.exists(PAI_PAN_PATH):
        raise FileNotFoundError("找不到同目录的 pai_pan.py：%s" % PAI_PAN_PATH)
    spec = importlib.util.spec_from_file_location("pai_pan_local", PAI_PAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_lunar():
    """导入 lunar_python；-I 屏蔽用户 site-packages 时手动挂回 user-site。"""
    try:
        from lunar_python import Solar
        return Solar
    except ModuleNotFoundError:
        import site
        candidates = []
        if hasattr(site, "getusersitepackages"):
            candidates.append(site.getusersitepackages())
        candidates.append(site.USER_SITE)
        for p in candidates:
            if p and p not in sys.path and os.path.isdir(p):
                sys.path.append(p)
        from lunar_python import Solar
        return Solar


def lunar_four_pillars(Solar, y, m, d, hh, mm):
    """lunar_python 侧四柱。强制 sect=1，与 pai_pan 夜子时口径对齐。"""
    ec = Solar.fromYmdHms(y, m, d, hh, mm, 0).getLunar().getEightChar()
    ec.setSect(1)
    return [ec.getYear(), ec.getMonth(), ec.getDay(), ec.getTime()]


def pai_four_pillars(pai_pan, solar_date, hour, minute, shichen, sex, place):
    res = pai_pan.compute(
        solar_date=solar_date,
        hour=hour,
        minute=minute,
        shichen=shichen,
        sex=sex,
        place=place,
    )
    p = res["pillars"]
    out = []
    for k in ("year", "month", "day", "hour"):
        gan, zhi = p[k][0], p[k][1]
        out.append("未知" if gan == "未知" or zhi == "未知" else gan + zhi)
    return res, out


def parse_iso_date(text):
    y, m, d = text.split("-")
    return date(int(y), int(m), int(d))


def parse_hour(text):
    hh, mm = text.split(":")
    return int(hh), int(mm)


def main(argv=None):
    ap = argparse.ArgumentParser(description="四柱双引擎对拍校验（pai_pan × lunar_python）")
    ap.add_argument("--solar", required=True, help="公历生日 YYYY-MM-DD")
    ap.add_argument("--hour", help="出生钟点 HH:MM（北京时间）")
    ap.add_argument("--shichen", choices=list(ZHI), help="时辰地支（与 --hour 二选一）")
    ap.add_argument("--sex", required=True, choices=("男", "女"))
    ap.add_argument("--no-hour", action="store_true", dest="no_hour", help="时辰未知，只校年月日三柱")
    ap.add_argument("--place", help="出生地，仅透传给 pai_pan 做时辰边界警告")
    ap.add_argument("--json", action="store_true", dest="as_json", help="输出 JSON")
    args = ap.parse_args(argv)

    given = [bool(args.hour), bool(args.shichen), bool(args.no_hour)]
    if sum(given) != 1:
        ap.error("--hour / --shichen / --no-hour 三选一")

    solar_date = parse_iso_date(args.solar)

    hour = minute = None
    if args.hour:
        hour, minute = parse_hour(args.hour)
    elif args.shichen:
        hour, minute = 12, 0  # 与 pai_pan 的时辰中点一致
    # --no-hour：保持 hour=None，pai_pan 按时辰未知处理

    try:
        pai_pan = load_pai_pan()
        Solar = load_lunar()
    except Exception as exc:
        print("依赖加载失败：%s" % exc, file=sys.stderr)
        return 3

    pai_result, pai_pillars = pai_four_pillars(
        pai_pan, solar_date, hour, minute, args.shichen, args.sex, args.place
    )
    lh, lm = (12, 0) if hour is None else (hour, minute)
    lunar_pillars = lunar_four_pillars(
        Solar, solar_date.year, solar_date.month, solar_date.day, lh, lm
    )

    diffs = []
    for i, name in enumerate(PILLAR_NAMES):
        a, b = pai_pillars[i], lunar_pillars[i]
        if a == "未知" or b == "未知":
            continue
        if a != b:
            diffs.append({"pillar": name, "pai_pan": a, "lunar_python": b})

    notes = list(pai_result.get("warnings") or [])
    if args.hour and hour >= 23:
        notes.append("夜子时：lunar_python 已强制 sect=1 对齐 pai_pan 口径")
    if pai_result.get("hour_unknown"):
        notes.append("时柱不参与比对")

    if diffs:
        verdict = "fail"
        code = 1
    elif pai_result.get("hour_unknown"):
        verdict = "in_doubt"
        code = 3
    else:
        verdict = "pass"
        code = 0

    payload = {
        "verdict": verdict,
        "input": {
            "solar": args.solar,
            "hour": args.hour,
            "shichen": args.shichen,
            "sex": args.sex,
        },
        "pai_pan": pai_pillars,
        "lunar_python": lunar_pillars,
        "diffs": diffs,
        "lunar_text": pai_result.get("lunar_text"),
        "jie_name": pai_result.get("jie_name"),
        "notes": sorted(set(notes)),
    }

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return code

    print("判定：%s" % {"pass": "通过（四柱一致）", "fail": "不一致", "in_doubt": "存疑"}[verdict])
    in_time = args.hour or (args.shichen + "时" if args.shichen else "时辰未知")
    print("输入：%s %s %s" % (args.solar, in_time, args.sex))
    print("农历：%s    节气：%s" % (payload["lunar_text"], payload["jie_name"]))
    print("")
    print("        %-8s %-8s %-8s %-8s" % PILLAR_NAMES)
    print("pai_pan %-8s %-8s %-8s %-8s" % tuple(pai_pillars))
    print("lunar   %-8s %-8s %-8s %-8s" % tuple(lunar_pillars))
    if diffs:
        print("")
        for d in diffs:
            print("  ✗ %s：pai_pan=%s  lunar_python=%s" % (d["pillar"], d["pai_pan"], d["lunar_python"]))
    if payload["notes"]:
        print("")
        for n in payload["notes"]:
            print("  · %s" % n)
    return code


if __name__ == "__main__":
    sys.exit(main())
