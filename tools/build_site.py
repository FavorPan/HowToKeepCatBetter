#!/usr/bin/env python3
"""把 README.md 和 book/*.md 构建成静态网站，输出到 site/。

用法：python3 -I tools/build_site.py

规则：
- 只读 README.md 和 book/，不改正文。
- 条数、节名、证据分级、交叉引用对不上就报错退出，不写半成品。
  （先用 python3 -I tools/stats.py --check && --sync 同步 README，再跑本脚本。）
- 样式和脚本在 tools/site_assets/，构建时原样拷贝到 site/。
- site/ 是生成物，随仓库提交，GitHub Pages 可直接发布。
"""

import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK_DIR = ROOT / "book"
OUT_DIR = ROOT / "site"
ASSETS_DIR = ROOT / "tools" / "site_assets"
GITHUB = "https://github.com/FavorPan/HowToKeepCatBetter"

FIELDS = ["成本", "说人话", "收益", "证据等级", "来源", "备注"]
TAG_ORDER = ["钱", "时间", "毅力", "收益", "口径"]

SECTIONS = []          # [{no,title,intro,entries:[...]}]
ENTRY_INDEX = set()    # {(sec_no, entry_no)}
UNRESOLVED = []

FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Crect width='64' height='64' rx='14' fill='%239a3412'/%3E"
    "%3Ctext x='32' y='44' font-size='34' text-anchor='middle' fill='%23fff' "
    "font-family='sans-serif'%3E%E7%8C%AB%3C/text%3E%3C/svg%3E"
)


def warn(msg):
    print(f"警告: {msg}")


def die(msg):
    print(f"错误: {msg}")
    sys.exit(1)


# ---------- 行内渲染 ----------

def _unesc_amp(s):
    """href 属性里的 &amp; 还原成 &。"""
    return s.replace("&amp;", "&")


def inline(s):
    """行内 markdown 转 HTML。先转义，再挂链接和交叉引用。"""
    s = html.escape(s, quote=False)
    # <https://...> 自动链接（转义后是 &lt;...&gt;）
    s = re.sub(
        r"&lt;(https?://(?:[^&\s]|&amp;)+)&gt;",
        lambda m: f'<a href="{_unesc_amp(m.group(1))}" target="_blank" rel="noopener">{m.group(1)}</a>',
        s,
    )
    # [文字](链接)
    s = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: f'<a href="{_unesc_amp(m.group(2))}" target="_blank" rel="noopener">{m.group(1)}</a>',
        s,
    )
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)

    def xref(m):
        sec = int(m.group(1))
        if m.group(2) is not None:
            num = int(m.group(2))
            if (sec, num) in ENTRY_INDEX:
                return f'<a class="xref" href="{sec:02d}.html#e-{sec}-{num}">{m.group(0)}</a>'
            UNRESOLVED.append(m.group(0))
            return m.group(0)
        if any(x["no"] == sec for x in SECTIONS):
            return f'<a class="xref" href="{sec:02d}.html">{m.group(0)}</a>'
        UNRESOLVED.append(m.group(0))
        return m.group(0)

    s = re.sub(r"第\s*(\d+)\s*节(?:\s*第\s*(\d+)\s*条)?(?:（([^）]+)）)?", xref, s)
    return s


def block(text):
    """极简 markdown 块：段落、- 列表。只处理 README 用到的子集。"""
    out = []
    in_list = False
    for raw in text.split("\n"):
        s = raw.strip()
        if not s:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if s.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(s[2:])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{inline(s)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# ---------- 解析 ----------

def parse_section(path):
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^# (\d+)\.\s*(.+)$", text, re.M)
    if not m:
        die(f"{path.name}: 找不到「# N. 节名」标题行")
    sec = {"no": int(m.group(1)), "title": m.group(2).strip(), "intro": "", "entries": []}
    q = re.search(r"^>\s*(.+)$", text, re.M)
    if q:
        sec["intro"] = q.group(1).strip()
    body = text[m.end():]
    for chunk in re.split(r"^### ", body, flags=re.M)[1:]:
        lines = chunk.split("\n")
        hm = re.match(r"^(\d+)\.\s*(.+)$", lines[0].strip())
        if not hm:
            die(f"{path.name}: 条目标题行解析失败：{lines[0][:40]}")
        entry = {"no": int(hm.group(1)), "title": hm.group(2).strip(), "tags": {}, "fields": {}}
        cur = None
        for line in lines[1:]:
            s = line.strip()
            if not s:
                continue
            t = re.match(r"<!--\s*成本标签[:：]\s*(.+?)\s*-->", s)
            if t:
                for kv in t.group(1).split():
                    k, v = kv.split("=", 1)
                    entry["tags"][k] = v
                cur = None
                continue
            f = re.match(r"^-\s*([^：]{1,6})：\s*(.*)$", s)
            if f and f.group(1) in FIELDS:
                cur = f.group(1)
                entry["fields"][cur] = f.group(2).strip()
                continue
            if s.startswith("- ") and cur:
                entry["fields"][cur] += "\n" + s[2:].strip()
                continue
            if cur:
                entry["fields"][cur] += s
            else:
                warn(f"{path.name} 条 {entry['no']}：标题后游离行「{s[:24]}…」")
        if "证据等级" not in entry["fields"]:
            die(f"{path.name} 条 {entry['no']}（{entry['title']}）：缺「证据等级」行")
        entry["ev"] = entry["fields"]["证据等级"].strip()[:1].upper()
        if entry["ev"] not in ("A", "B", "C"):
            die(f"{path.name} 条 {entry['no']}：证据等级「{entry['fields']['证据等级']}」不合法")
        if not entry["tags"]:
            warn(f"{path.name} 条 {entry['no']}：缺成本标签注释，筛选页会少标签")
        sec["entries"].append(entry)
    return sec


def parse_readme():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    status = re.search(r"^> 状态：已写 (\d+) 条\s*(.+)$", text, re.M)
    if not status:
        die("README.md: 找不到「> 状态：已写 N 条」状态行")
    data = {"total": int(status.group(1)), "per": {}, "toc": {}, "secs": {}}
    for m in re.finditer(
        r"第 (\d+) 节「([^」]+)」(\d+) 条（A(\d+)/B(\d+)/C(\d+)）", status.group(2)
    ):
        data["per"][int(m.group(1))] = {
            "title": m.group(2),
            "n": int(m.group(3)),
            "A": int(m.group(4)),
            "B": int(m.group(5)),
            "C": int(m.group(6)),
        }
    for m in re.finditer(r"^\| \[(\d+)\. ([^\]]+)\]\(book/[^)]+\) \| (.+?) \|$", text, re.M):
        data["toc"][int(m.group(1))] = m.group(3)
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    for i in range(1, len(parts), 2):
        data["secs"][parts[i].strip()] = parts[i + 1]
    return data


# ---------- 校验 ----------

def validate(readme):
    total_entries = 0
    for sec in SECTIONS:
        for e in sec["entries"]:
            key = (sec["no"], e["no"])
            if key in ENTRY_INDEX:
                die(f"条目编号重复：第 {sec['no']} 节第 {e['no']} 条")
            ENTRY_INDEX.add(key)
        nums = [e["no"] for e in sec["entries"]]
        if nums != list(range(1, len(nums) + 1)):
            die(f"第 {sec['no']} 节条目编号不连续：{nums[:30]}")
        total_entries += len(sec["entries"])

    if set(readme["per"]) != {s["no"] for s in SECTIONS}:
        die(
            "README 状态行与 book/ 节集合不一致："
            f"README={sorted(readme['per'])} book={sorted(s['no'] for s in SECTIONS)}"
        )
    for sec in SECTIONS:
        p = readme["per"][sec["no"]]
        if p["n"] != len(sec["entries"]):
            die(f"第 {sec['no']} 节条数不一致：README 写 {p['n']}，实际 {len(sec['entries'])}")
        if p["title"] != sec["title"]:
            die(f"第 {sec['no']} 节节名不一致：README「{p['title']}」实际「{sec['title']}」")
        counts = {"A": 0, "B": 0, "C": 0}
        for e in sec["entries"]:
            counts[e["ev"]] += 1
        if (p["A"], p["B"], p["C"]) != (counts["A"], counts["B"], counts["C"]):
            die(
                f"第 {sec['no']} 节证据分级不一致：README 写 A{p['A']}/B{p['B']}/C{p['C']}，"
                f"实际 A{counts['A']}/B{counts['B']}/C{counts['C']}"
            )
        if sec["no"] not in readme["toc"]:
            die(f"README 目录表缺第 {sec['no']} 节")
    if total_entries != readme["total"]:
        die(f"总条数不一致：README 写 {readme['total']}，实际 {total_entries}")

    # 干跑一遍行内渲染，把交叉引用全部解析一遍，有解不开的就退出
    for sec in SECTIONS:
        inline(sec["intro"])
        for e in sec["entries"]:
            inline(e["title"])
            for v in e["fields"].values():
                inline(v)
    if UNRESOLVED:
        die(f"交叉引用无法解析（共 {len(UNRESOLVED)} 处）：{UNRESOLVED[:10]}")
    return total_entries


# ---------- 页面模板 ----------

def head(title, desc, toc_btn=False):
    toc_btn_html = (
        '<button type="button" id="toc-toggle" class="linklike toc-btn" '
        'aria-controls="sidebar" aria-expanded="false">目录</button>'
        if toc_btn
        else ""
    )
    bar_cls = "wrap wide bar" if toc_btn else "wrap bar"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc, quote=True)}">
<meta property="og:title" content="{html.escape(title, quote=True)}">
<meta property="og:description" content="{html.escape(desc, quote=True)}">
<meta property="og:type" content="website">
<meta name="theme-color" content="#f4ede0" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#211a11" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{FAVICON}">
<link rel="stylesheet" href="style.css">
<script>
(function(){{try{{var t=localStorage.getItem('theme');if(!t&&matchMedia('(prefers-color-scheme: dark)').matches)t='dark';if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}}})();
</script>
</head>
<body>
<header class="site"><div class="{bar_cls}">
<a class="brand" href="index.html">高性价比养猫指南</a>
<nav><a href="index.html">导读</a><a href="all.html">全部条目</a><a href="{GITHUB}" target="_blank" rel="noopener">GitHub</a>{toc_btn_html}<button type="button" id="theme-toggle" class="linklike" hidden aria-label="切换明暗主题">夜间</button></nav>
</div></header>
<main>"""


def foot(wide=False):
    wrap_cls = "wrap wide" if wide else "wrap"
    return f"""</main>
<footer><div class="{wrap_cls}">
<p>发现错误、想补条目、有数据可核对，去 <a href="{GITHUB}" target="_blank" rel="noopener">GitHub 仓库</a>开 issue 或提 PR。全文以 CC BY 4.0 发布，转载注明出处即可。</p>
</div></footer>
<script>
(function(){{
var b=document.getElementById('theme-toggle');
var r=document.documentElement;
function paint(){{b.textContent=r.dataset.theme==='dark'?'日间':'夜间';b.hidden=false;}}
if(b){{
paint();
b.addEventListener('click',function(){{
var n=r.dataset.theme==='dark'?'light':'dark';
r.dataset.theme=n;
try{{localStorage.setItem('theme',n);}}catch(e){{}}
paint();
}});
}}
var tb=document.getElementById('toc-toggle');
if(tb){{
var sc=document.querySelector('.scrim');
var sb=document.getElementById('sidebar');
var close=function(){{document.body.classList.remove('sb-open');tb.setAttribute('aria-expanded','false');}};
tb.addEventListener('click',function(){{
var o=document.body.classList.toggle('sb-open');
tb.setAttribute('aria-expanded',o?'true':'false');
}});
if(sc){{sc.addEventListener('click',close);}}
if(sb){{sb.addEventListener('click',function(ev){{if(ev.target.closest('a'))close();}});}}
}}
}})();
</script>
</body>
</html>"""


def chips(entry):
    out = [f'<span class="chip ev ev-{entry["ev"]}">证据 {entry["ev"]}</span>']
    for k in TAG_ORDER:
        if k in entry["tags"]:
            out.append(f'<span class="chip">{k} {entry["tags"][k]}</span>')
    return "".join(out)


def render_entry(sec, e):
    f = e["fields"]
    did = f'e-{sec["no"]}-{e["no"]}'
    parts = [f'<article class="entry" id="{did}">']
    parts.append(
        f'<div class="entry-head"><span class="entry-no">{e["no"]}</span>'
        f'<h3>{html.escape(e["title"])}</h3></div>'
    )
    if f.get("说人话"):
        parts.append(f'<p class="plain">{inline(f["说人话"])}</p>')
    parts.append(f'<div class="chips">{chips(e)}</div>')
    parts.append('<dl class="fields">')
    for k in ["成本", "收益", "来源", "备注"]:
        if f.get(k):
            cls = ' class="src"' if k == "来源" else ""
            parts.append(f"<dt>{k}</dt><dd{cls}>{inline(f[k])}</dd>")
    parts.append("</dl></article>")
    return "\n".join(parts)


def render_index(readme):
    n_sec = len(SECTIONS)
    n_a = sum(p["A"] for p in readme["per"].values())
    total = sum(len(s["entries"]) for s in SECTIONS)
    how = block(readme["secs"].get("这本书怎么用", ""))
    ledger = block(readme["secs"].get("收益算成三种账，不互相换算", ""))
    gloss = block(readme["secs"].get("读懂数字（术语表）", ""))
    toc_items = "\n".join(
        f'<a class="toc-item" href="{s["no"]:02d}.html">'
        f'<span class="no">{s["no"]}</span>'
        f'<span class="t"><strong>{html.escape(s["title"])}</strong>'
        f'<em>{html.escape(readme["toc"][s["no"]])}</em></span>'
        f'<span class="c">{len(s["entries"])}</span></a>'
        for s in SECTIONS
    )
    return (
        head(
            "高性价比养猫指南",
            "一本按「性价比」排序的养猫决策指南。每条回答两个问题：花掉什么，换回什么。",
        )
        + f"""
<section class="hero">
<div class="wrap">
<h1>高性价比养猫指南</h1>
<p class="sub">按「性价比」排序的养猫决策指南。每条回答两个问题：花掉什么，换回什么。</p>
<div class="stats">
<div class="stat"><strong>{total}</strong><span>条建议</span></div>
<div class="stat"><strong>{n_sec}</strong><span>个章节</span></div>
<div class="stat"><strong>{n_a}</strong><span>条 A 级证据</span></div>
</div>
<div class="cta">
<a class="btn primary" href="01.html">从第 1 节开始读</a>
<a class="btn" href="all.html">按标签筛选全部条目</a>
</div>
</div>
</section>
<section class="wrap blk" id="how">
<h2>这本书怎么用</h2>
{how}
</section>
<section class="wrap blk" id="ledger">
<h2>收益算成三种账，不互相换算</h2>
{ledger}
</section>
<section class="wrap blk" id="toc">
<h2>目录</h2>
<div class="toc-grid">
{toc_items}
</div>
</section>
<section class="wrap blk" id="glossary">
<h2>读懂数字（术语表）</h2>
{gloss}
</section>"""
        + foot()
    )


def render_sidebar(cur):
    """左侧目录：全部节平铺，当前节展开到条目级并高亮。"""
    rows = []
    for s in SECTIONS:
        cls = "sb-sec cur" if s["no"] == cur["no"] else "sb-sec"
        rows.append(
            f'<a class="{cls}" href="{s["no"]:02d}.html"><b>{s["no"]}</b>{html.escape(s["title"])}</a>'
        )
        if s["no"] == cur["no"]:
            rows.append('<div class="sb-entries">')
            rows.extend(
                f'<a class="sb-e" href="#e-{s["no"]}-{e["no"]}">{e["no"]}. {html.escape(e["title"])}</a>'
                for e in s["entries"]
            )
            rows.append("</div>")
    return "\n".join(rows)


def render_section_page(sec, prev_sec, next_sec):
    n = sec["no"]
    counts = {"A": 0, "B": 0, "C": 0}
    for e in sec["entries"]:
        counts[e["ev"]] += 1
    title = f"{n}. {sec['title']} · 高性价比养猫指南"
    desc = re.sub(r"^本节回答：", "", sec["intro"])[:150]
    prev_link = (
        f'<a class="pg" href="{prev_sec["no"]:02d}.html">'
        f'<span>上一节</span><strong>{prev_sec["no"]}. {html.escape(prev_sec["title"])}</strong></a>'
        if prev_sec
        else "<span></span>"
    )
    next_link = (
        f'<a class="pg next" href="{next_sec["no"]:02d}.html">'
        f'<span>下一节</span><strong>{next_sec["no"]}. {html.escape(next_sec["title"])}</strong></a>'
        if next_sec
        else "<span></span>"
    )
    return (
        head(title, desc, toc_btn=True)
        + f"""
<div class="layout">
<aside class="sidebar" id="sidebar" aria-label="本书目录">
<p class="sb-cap">目录</p>
<nav>
{render_sidebar(sec)}
</nav>
</aside>
<div class="scrim" aria-hidden="true"></div>
<article class="page content">
<header class="page-head wrap">
<p class="crumb"><a href="index.html">导读</a><span>/</span>第 {n} 节</p>
<h1>{n}. {html.escape(sec['title'])}</h1>
<p class="intro">{inline(sec['intro'])}</p>
<p class="meta">本节 {len(sec['entries'])} 条（A {counts['A']} / B {counts['B']} / C {counts['C']}）</p>
</header>
<div class="wrap entries">
{chr(10).join(render_entry(sec, e) for e in sec['entries'])}
</div>
<nav class="pager wrap">{prev_link}{next_link}</nav>
</article>
</div>"""
        + foot(True)
    )


def render_row(sec, e):
    f = e["fields"]
    search = html.escape(
        f'{e["title"]} {f.get("说人话", "")} {sec["title"]}'.lower(), quote=True
    )
    return (
        f'<li class="row" data-ev="{e["ev"]}"'
        f' data-scope="{e["tags"].get("口径", "")}"'
        f' data-gain="{e["tags"].get("收益", "")}"'
        f' data-money="{e["tags"].get("钱", "")}"'
        f' data-time="{e["tags"].get("时间", "")}"'
        f' data-will="{e["tags"].get("毅力", "")}"'
        f' data-search="{search}">'
        f'<p class="row-head"><span class="row-loc">{sec["no"]:02d} {html.escape(sec["title"])}</span>'
        f'<a class="row-title" href="{sec["no"]:02d}.html#e-{sec["no"]}-{e["no"]}">'
        f'{e["no"]}. {html.escape(e["title"])}</a></p>'
        f'<p class="plain">{inline(f.get("说人话", ""))}</p>'
        f'<div class="chips">{chips(e)}</div>'
        f"</li>"
    )


FILTER_GROUPS = [
    ("口径", [("猫健康",), ("金钱",), ("时间",)]),
    ("收益", [("大",), ("中",), ("小",)]),
    ("钱", [("0",), ("少",), ("多",)]),
    ("时间", [("少",), ("中",), ("多",)]),
    ("毅力", [("否",), ("些",), ("是",)]),
    ("证据", [("A",), ("B",), ("C",)]),
]


def render_all_page(total):
    rows = []
    for sec in SECTIONS:
        rows.extend(render_row(sec, e) for e in sec["entries"])
    groups = []
    for label, values in FILTER_GROUPS:
        fchips = "".join(
            f'<button type="button" class="fchip" aria-pressed="false" data-group="{label}" data-value="{v[0]}">{v[0]}</button>'
            for v in values
        )
        groups.append(
            f'<div class="fgroup" role="group" aria-label="{label}">'
            f'<span class="flabel">{label}</span>{fchips}</div>'
        )
    return (
        head(
            "全部条目 · 高性价比养猫指南",
            f"全部 {total} 条建议，按钱、时间、毅力、收益、口径和证据等级筛选。",
        )
        + f"""
<section class="toolbar">
<div class="wrap">
<div class="searchline">
<input id="q" type="search" placeholder="搜标题或说人话" aria-label="搜索条目">
<span id="count">显示 {total} 条</span>
<button type="button" id="clear" class="linklike">清空筛选</button>
</div>
<div class="fgroups">{''.join(groups)}</div>
</div>
</section>
<div class="wrap">
<ul class="rows" id="rows">
{chr(10).join(rows)}
</ul>
<div id="empty" class="empty" hidden>
<p>没有符合条件的条目。清掉几个筛选项再试。</p>
</div>
<details class="legend">
<summary>标签和证据等级是什么意思</summary>
<dl>
<dt>证据 A / B / C</dt><dd>A 有可量化证据，来自荟萃分析、大型队列或随机对照试验；B 有研究支撑但难以量化，或来自小样本、单一研究；C 兽医共识或权威指南的定性建议。</dd>
<dt>钱 0 / 少 / 多</dt><dd>0 不花钱或省钱；少 几十到几百元或每月几十元内；多 上千元或长期显著支出。</dd>
<dt>时间 少 / 中 / 多</dt><dd>少 一次几分钟内或顺手；中 一次性数小时或每周小时级；多 每天持续占用。</dd>
<dt>毅力 否 / 些 / 是</dt><dd>否 做一次就完；些 改一个习惯或忍一点不适；是 长期对抗惯性。</dd>
<dt>口径</dt><dd>这条建议主要换回什么：猫健康、金钱（主人的钱）、时间（主人的时间精力）。三种账分开算，不互相换算。</dd>
</dl>
</details>
</div>
<script src="app.js"></script>"""
        + foot()
    )


# ---------- 构建 ----------

def build_data(total):
    """结构化数据包：给未来的 AI Agent / RAG / EPUB 复用。字段与书完全一致。"""
    return {
        "total": total,
        "sections": [
            {
                "no": s["no"],
                "title": s["title"],
                "intro": s["intro"],
                "url": f"{s['no']:02d}.html",
                "entries": [
                    {
                        "no": e["no"],
                        "title": e["title"],
                        "anchor": f"e-{s['no']}-{e['no']}",
                        "url": f"{s['no']:02d}.html#e-{s['no']}-{e['no']}",
                        "ev": e["ev"],
                        "tags": e["tags"],
                        "fields": e["fields"],
                    }
                    for e in s["entries"]
                ],
            }
            for s in SECTIONS
        ],
    }


def main():
    for path in sorted(BOOK_DIR.glob("*.md")):
        SECTIONS.append(parse_section(path))
    SECTIONS.sort(key=lambda s: s["no"])
    if not SECTIONS:
        die("book/ 下没找到任何 md 文件")

    readme = parse_readme()
    total = validate(readme)

    OUT_DIR.mkdir(exist_ok=True)
    pages = {"index.html": render_index(readme)}
    for i, sec in enumerate(SECTIONS):
        prev_sec = SECTIONS[i - 1] if i > 0 else None
        next_sec = SECTIONS[i + 1] if i + 1 < len(SECTIONS) else None
        pages[f"{sec['no']:02d}.html"] = render_section_page(sec, prev_sec, next_sec)
    pages["all.html"] = render_all_page(total)
    for name, content in pages.items():
        (OUT_DIR / name).write_text(content, encoding="utf-8")

    if ASSETS_DIR.is_dir():
        for f in sorted(ASSETS_DIR.iterdir()):
            if f.is_file():
                shutil.copy2(f, OUT_DIR / f.name)
    else:
        die(f"缺资源目录 {ASSETS_DIR}")

    # 结构化数据包：给未来的 AI Agent / RAG / EPUB 复用。字段与书完全一致。
    data = build_data(total)
    data_dir = OUT_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    (data_dir / "entries.json").write_text(payload, encoding="utf-8")

    print(f"完成：{len(SECTIONS)} 节 {total} 条，{len(pages)} 个页面 → {OUT_DIR}/")
    print(f"  数据包：data/entries.json（{len(payload)} 字符）")
    for sec in SECTIONS:
        print(f"  {sec['no']:02d} {sec['title']}：{len(sec['entries'])} 条")


if __name__ == "__main__":
    main()
