#!/usr/bin/env node
// 站点回归测试：从 index.html 抽出解析库（<script id="lib">），对真书跑解析，
// 对齐 README 状态行和页面里的静态数字；app 脚本另过一遍 node --check。
// 用法：node tools/test_site.mjs
import { readFileSync, writeFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(join(ROOT, 'index.html'), 'utf8');

const libSrc = html.match(/<script id="lib">([\s\S]*?)<\/script>/);
const appSrc = html.match(/<script id="app">([\s\S]*?)<\/script>/);
assert.ok(libSrc, 'index.html 里找不到 <script id="lib">');
assert.ok(appSrc, 'index.html 里找不到 <script id="app">');
// lib 只做解析，不许碰 DOM，node 里才能直接跑
assert.ok(!/\bdocument\b|\bwindow\b/.test(libSrc[1]), 'lib 脚本必须保持无 DOM');

eval(libSrc[1]);
const { parseReadme, parseGlossary, ratioOf, XREF_RE, xrefKeysOf } = globalThis.__LIB__;

const readme = readFileSync(join(ROOT, 'README.md'), 'utf8');
const files = [...new Set([...readme.matchAll(/\]\((book\/[^)]+\.md)\)/g)].map(m => m[1]))].sort();
const parts = files.map(f => readFileSync(join(ROOT, f), 'utf8'));
const secs = parseReadme(parts.join('\n\n'));
const SECS = new Map(), ITEMS = new Map();
for (const s of secs){
  SECS.set('s' + s.n, s);
  for (const e of s.entries) ITEMS.set(e.id, e);
}

test('README 目录链到 14 个 book 文件，解析出 14 节', () => {
  assert.equal(files.length, 14);
  assert.equal(secs.length, 14);
  secs.forEach((s, i) => assert.equal(s.n, i + 1, '节号不连续'));
});

test('条目总数 245，条号连续，六栏齐全', () => {
  let total = 0;
  for (const s of secs){
    s.entries.forEach((e, i) => {
      assert.equal(e.n, i + 1, '第 ' + s.n + ' 节条号断档');
      assert.ok(e.title, e.id + ' 缺标题');
      assert.ok(e.cost && e.human && e.gain && e.src && e.note !== undefined, e.id + ' 缺字段');
      assert.ok(['A','B','C'].includes(e.grade), e.id + ' 证据等级异常：' + e.grade);
    });
    total += s.entries.length;
  }
  assert.equal(total, 245);
});

test('成本标签取值都在约定集合内', () => {
  const ok = { money:['0','少','多'], time:['少','中','多'], will:['否','些','是'], level:['大','中','小'], lens:['猫健康','金钱','时间'] };
  for (const s of secs) for (const e of s.entries){
    assert.ok(ok.money.includes(e.money), e.id + ' 钱=' + e.money);
    assert.ok(ok.time.includes(e.time), e.id + ' 时间=' + e.time);
    assert.ok(ok.will.includes(e.will), e.id + ' 毅力=' + e.will);
    assert.ok(ok.level.includes(e.level), e.id + ' 收益=' + e.level);
    assert.ok(ok.lens.includes(e.lens), e.id + ' 口径=' + e.lens);
  }
});

test('性价比合成公式和 CLAUDE.md 口径一致', () => {
  assert.equal(ratioOf(0, '大'), '极高');
  assert.equal(ratioOf(1, '大'), '高');
  assert.equal(ratioOf(2, '大'), '高');
  assert.equal(ratioOf(3, '大'), '一般');
  assert.equal(ratioOf(0, '中'), '高');
  assert.equal(ratioOf(2, '中'), '一般');
  assert.equal(ratioOf(1, '小'), '一般');
});

test('正文里全部交叉引用都能解析到条目', () => {
  let n = 0;
  for (const s of secs){
    const texts = s.entries.flatMap(e => [e.cost, e.human, e.gain, e.note]);
    if (s.intro) texts.push(s.intro);
    for (const t of texts){
      for (const m of t.matchAll(XREF_RE)){
        n++;
        assert.ok(xrefKeysOf(m, s.n, ITEMS, SECS).length,
          '第 ' + s.n + ' 节有解析不到的引用：' + m[0]);
      }
    }
  }
  assert.ok(n > 200, '交叉引用数量异常：' + n);
});

test('术语表解析出别名，含 HR/RR/OR', () => {
  const terms = parseGlossary(readme).map(g => g.term);
  for (const t of ['HR', 'RR', 'OR', '荟萃分析', '队列']){
    assert.ok(terms.includes(t), '缺术语 ' + t);
  }
});

test('index.html 静态数字和真书一致（meta 描述、noscript 节列表）', () => {
  const total = ITEMS.size;
  assert.ok(html.includes(total + ' 条建议'), 'meta 描述里的条目数过期了，应改为 ' + total);
  const nos = html.match(/<noscript>[\s\S]*?<\/noscript>/)[0];
  const links = [...nos.matchAll(/book\//g)].length;
  assert.equal(links, files.length, 'noscript 的节列表和 book/ 对不上');
});

test('README 状态行和 book/ 的节数、A/B/C 分布一致', () => {
  for (const s of secs){
    const g = { A:0, B:0, C:0 };
    for (const e of s.entries) g[e.grade]++;
    const frag = '第 ' + s.n + ' 节「' + s.title + '」' + s.entries.length + ' 条（A' + g.A + '/B' + g.B + '/C' + g.C + '）';
    assert.ok(readme.includes(frag), 'README 状态行过期，应为：' + frag);
  }
});

test('app 脚本通过 node --check', () => {
  const p = join(tmpdir(), 'cat-site-app-' + process.pid + '.js');
  writeFileSync(p, appSrc[1]);
  const r = spawnSync(process.execPath, ['--check', p]);
  assert.equal(r.status, 0, 'app 脚本语法错误：' + r.stderr);
});

test('lib 和 app 两个 script 块能共存（顶层绑定不冲突）', () => {
  // 经典 script 的顶层 const/function 共享全局词法作用域，app 里再声明一遍同名
  // 绑定会让整个 app 脚本 SyntaxError，页面永远停在「正在读取正文」。
  // 只拼在一起做编译（不执行，不需要 DOM），重复声明在这一步就会抛错。
  assert.doesNotThrow(() => new Function(libSrc[1] + '\n' + appSrc[1]));
});
