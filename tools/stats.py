#!/usr/bin/env python3
"""统计并校验 book/ 条目。用法：
  python3 tools/stats.py            # 各节条目数与 A/B/C 分布
  python3 tools/stats.py --check    # 格式校验，违规退出码 1
  python3 tools/stats.py --sync     # 用统计结果重写 README 状态行
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "book"
README = ROOT / "README.md"
FIELDS = ("成本", "说人话", "收益", "来源", "备注")
WORDS = ("HR", "RR", "OR", "CI", "队列", "荟萃")
ENTRY_RE = re.compile(r"^### (\d+)\. (.+)$")
TAG_RE = re.compile(r"^<!-- 成本标签: (.+) -->$")
GRADE_RE = re.compile(r"^- 证据等级：([ABC])$")


def parse_section(text):
    """解析一个节文件，返回条目 dict 列表。"""
    entries, cur = [], None
    for raw in text.splitlines():
        m = ENTRY_RE.match(raw)
        if m:
            cur = {"num": int(m.group(1)), "title": m.group(2),
                   "tag": None, "grade": None, "body": [], "lines": 1}
            entries.append(cur)
            continue
        if cur is None:
            continue
        cur["lines"] += 1
        t = TAG_RE.match(raw)
        if t:
            cur["tag"] = t.group(1)
        elif GRADE_RE.match(raw):
            cur["grade"] = GRADE_RE.match(raw).group(1)
        else:
            cur["body"].append(raw)
    return entries


def check(entries):
    """返回违规信息列表：禁词、缺栏、缺标签、超行数、裸条号与相对引用。"""
    out = []
    for e in entries:
        shuo = next((b for b in e["body"] if b.startswith("- 说人话")), "")
        for w in WORDS:
            if re.search(rf"\b{w}\b", shuo) or w in shuo:
                out.append(f'条{e["num"]} 说人话出现禁词 {w}')
        for f in FIELDS:
            if not any(b.startswith(f"- {f}：") for b in e["body"]):
                out.append(f'条{e["num"]} 缺「{f}」栏')
        if e["grade"] is None:
            out.append(f'条{e["num"]} 缺「证据等级」栏')
        if e["tag"] is None:
            out.append(f'条{e["num"]} 缺成本标签注释')
        if e["lines"] > 10:
            out.append(f'条{e["num"]} 共 {e["lines"]} 行，超 10 行')
        joined = " ".join(e["body"])
        for m in re.finditer(r"第 ?(\d+) ?条", joined):
            if not re.search(rf"第 ?\d+ ?节第 ?{m.group(1)} ?条（[^）]+）", joined):
                out.append(f'条{e["num"]} 裸条号引用「{m.group(0)}」')
        for kw in ("同上一条", "见上一条", "上上条"):
            if kw in joined:
                out.append(f'条{e["num"]} 相对引用「{kw}」')
    return out


def section_counts():
    """按文件序返回（节号, 节名, 条数, {A, B, C}），只含已有条目的节。"""
    rows = []
    for f in sorted(BOOK.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        es = parse_section(text)
        if not es:
            continue
        g = {k: sum(1 for e in es if e["grade"] == k) for k in "ABC"}
        title = re.search(r"^# \d+\. (.+)$", text, re.M).group(1)
        rows.append((int(f.name.split("-")[0]), title, len(es), g))
    return rows


def sync_readme():
    """用统计结果重写 README 的状态行。"""
    rows = section_counts()
    parts = [f"第 {n} 节「{t}」{c} 条（A{g['A']}/B{g['B']}/C{g['C']}）"
             for n, t, c, g in rows]
    total = sum(c for *_, c, g in rows)
    line = "> 状态：已写 " + f"{total} 条 —— " + "；".join(parts) + "；其余各节待补。"
    readme = README.read_text(encoding="utf-8")
    readme = re.sub(r"> 状态：.*", line, readme, count=1)
    README.write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    if "--check" in sys.argv:
        bad = []
        for f in sorted(BOOK.glob("*.md")):
            bad += check(parse_section(f.read_text(encoding="utf-8")))
        print("\n".join(bad) or "OK")
        sys.exit(1 if bad else 0)
    if "--sync" in sys.argv:
        sync_readme()
        print("README 状态行已更新")
        sys.exit(0)
    for n, t, c, g in section_counts():
        print(f"第{n}节 {t}: {c} 条 (A{g['A']}/B{g['B']}/C{g['C']})")
