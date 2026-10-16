"""build_site.py 的回归测试：只解析和渲染，不写 site/。

跑法：python3 -I tools/test_build_site.py
"""
import json
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site as bs


def build_all():
    """按 main() 的顺序解析 + 校验 + 渲染，返回 (readme, total, pages)。不写盘。"""
    bs.SECTIONS.clear()
    bs.ENTRY_INDEX.clear()
    bs.UNRESOLVED.clear()
    for path in sorted(bs.BOOK_DIR.glob("*.md")):
        bs.SECTIONS.append(bs.parse_section(path))
    bs.SECTIONS.sort(key=lambda s: s["no"])
    readme = bs.parse_readme()
    total = bs.validate(readme)
    pages = {"index.html": bs.render_index(readme)}
    for i, sec in enumerate(bs.SECTIONS):
        prev_sec = bs.SECTIONS[i - 1] if i > 0 else None
        next_sec = bs.SECTIONS[i + 1] if i + 1 < len(bs.SECTIONS) else None
        pages[f"{sec['no']:02d}.html"] = bs.render_section_page(sec, prev_sec, next_sec)
    pages["all.html"] = bs.render_all_page(total)
    return readme, total, pages


class WellformedChecker(HTMLParser):
    VOID = {"meta", "link", "br", "hr", "img", "input", "wbr", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.problems = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.problems.append(f"未闭合 <{self.stack.pop()}>")
            self.stack.pop()
        else:
            self.problems.append(f"错配 </{tag}>")


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme, cls.total, cls.pages = build_all()

    def test_counts_match_readme(self):
        per_book = sum(len(s["entries"]) for s in bs.SECTIONS)
        self.assertEqual(self.total, self.readme["total"])
        self.assertEqual(self.total, per_book)

    def test_pages_complete(self):
        self.assertEqual(set(self.pages), {"index.html", "all.html"} | {f"{n:02d}.html" for n in range(1, len(bs.SECTIONS) + 1)})

    def test_html_wellformed(self):
        for name, text in self.pages.items():
            c = WellformedChecker()
            c.feed(text)
            leftovers = [t for t in c.stack if t not in ("html", "body")]
            self.assertEqual(c.problems + leftovers, [], f"{name} 标签配对有问题")

    def test_every_entry_anchor_and_title(self):
        for sec in bs.SECTIONS:
            text = self.pages[f"{sec['no']:02d}.html"]
            for e in sec["entries"]:
                anchor = f'e-{sec["no"]}-{e["no"]}'
                self.assertIn(f'id="{anchor}"', text, f"缺锚点 {anchor}")
                self.assertIn(f"<h3>{e['title']}</h3>", text)

    def test_internal_links_resolve(self):
        for name, text in self.pages.items():
            ids = set(re.findall(r'id="(e-\d+-\d+)"', text))
            for href in re.findall(r'href="#([\w-]+)"', text):
                self.assertIn(href, ids, f"{name} 内链 #{href} 无目标")
            for page in re.findall(r'href="((?:\d\d|all|index)\.html)', text):
                self.assertIn(page, self.pages, f"{name} 跨页链接 {page} 不存在")

    def test_sidebar_only_on_section_pages(self):
        for sec in bs.SECTIONS:
            text = self.pages[f'{sec["no"]:02d}.html']
            self.assertEqual(text.count('class="sb-sec"'), len(bs.SECTIONS) - 1)
            self.assertEqual(text.count('class="sb-sec cur"'), 1)
            self.assertEqual(
                text.count('class="sb-e"'), len(sec["entries"]), "侧栏条目链接数不符"
            )
            self.assertIn('id="toc-toggle"', text)
        self.assertNotIn('id="sidebar"', self.pages["index.html"])
        self.assertNotIn('id="sidebar"', self.pages["all.html"])
        self.assertNotIn('id="toc-toggle"', self.pages["index.html"])

    def test_no_unresolved_xref(self):
        self.assertEqual(bs.UNRESOLVED, [])

    def test_filter_rows_match_total(self):
        rows = self.pages["all.html"].count('class="row"')
        self.assertEqual(rows, self.total)


class PayloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 复用 BuildTest 已构建的 SECTIONS；单独跑本类时重新构建
        if not bs.SECTIONS or not bs.ENTRY_INDEX:
            build_all()
        cls.total = sum(len(s["entries"]) for s in bs.SECTIONS)
        cls.data = bs.build_data(cls.total)

    def test_round_trip(self):
        text = json.dumps(self.data, ensure_ascii=False)
        back = json.loads(text)
        self.assertEqual(back["total"], self.total)
        self.assertEqual(len(back["sections"]), len(bs.SECTIONS))

    def test_entry_fields_complete(self):
        anchors = set()
        for s in self.data["sections"]:
            self.assertTrue(s["entries"], f"第 {s['no']} 节在数据包里是空的")
            for e in s["entries"]:
                self.assertIn(e["ev"], ("A", "B", "C"))
                self.assertIn("证据等级", e["fields"])
                self.assertIn("说人话", e["fields"])
                self.assertRegex(e["url"], rf"^{s['no']:02d}\.html#e-{s['no']}-{e['no']}$")
                anchors.add(e["anchor"])
        self.assertEqual(len(anchors), self.total, "数据包锚点有重复")


if __name__ == "__main__":
    unittest.main()
