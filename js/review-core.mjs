/**
 * 扫描引擎（Node 侧）—— 与 com.ppos.sm.ReviewEngine 同一份规格实现。
 * 目录遍历 → 文件分类（js/java/pom.xml）→ 逐行抹注释匹配规则
 * → 项目级检查（pom.xml 良构性 / UTF-8 有效性）。
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { basename, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { IGNORE_DIRS, LONG_LINE, MAX_FILE_BYTES, RULES } from './rules.mjs';

// 引擎内用的全局正则副本（源正则不带 g，这里按需加 g；matchAll 不改源 lastIndex）
for (const r of RULES) {
  if (r.re) r._g = r.re.map((x) => new RegExp(x.source, x.flags.includes('i') ? 'gi' : 'g'));
}

// ── 抹注释状态机（与 Java stripLine 同规格）──────────────────────────
// code=普通代码  block=块注释内（跨行）  sq/dq=单/双引号字符串（不跨行）
// tq=js 模板串（跨行）。已知近似：Java text block(""")按双引号态近似、CDATA 不识别。
const S_CODE = 0, S_BLOCK = 1, S_SQ = 2, S_DQ = 3, S_TQ = 4;

export function stripLine(line, js, stateIn) {
  const cs = line.split('');
  let state = stateIn;
  let i = 0;
  while (i < cs.length) {
    const c = cs[i];
    const n = cs[i + 1];
    if (state === S_CODE) {
      if (c === '/' && n === '/') {
        for (let j = i; j < cs.length; j++) cs[j] = ' ';
        return { text: cs.join(''), state: S_CODE };
      }
      if (c === '/' && n === '*') {
        cs[i] = ' '; cs[i + 1] = ' ';
        state = S_BLOCK; i += 2; continue;
      }
      if (c === "'") state = S_SQ;
      else if (c === '"') state = S_DQ;
      else if (js && c === '`') state = S_TQ;
      i++; continue;
    }
    if (state === S_BLOCK) {
      if (c === '*' && n === '/') {
        cs[i] = ' '; cs[i + 1] = ' ';
        state = S_CODE; i += 2; continue;
      }
      cs[i] = ' '; i++; continue;
    }
    // 字符串态：只跟踪闭合，内容原样保留；反斜杠转义跳下一字符
    if (c === '\\') { i += 2; continue; }
    if ((state === S_SQ && c === "'") || (state === S_DQ && c === '"') || (state === S_TQ && c === '`')) {
      state = S_CODE; i++; continue;
    }
    i++;
  }
  // 行尾：单/双引号串不跨行（回到 code）；块注释与 js 模板串跨行保留
  if (state === S_SQ || state === S_DQ) state = S_CODE;
  return { text: cs.join(''), state };
}

// ── 文件收集与分类 ─────────────────────────────────────────────────

function collect(dir, out) {
  if (!statSync(dir).isDirectory()) {
    out.push(resolve(dir));
    return out;
  }
  for (const name of readdirSync(dir).sort()) {
    if (IGNORE_DIRS.includes(name)) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) collect(p, out);
    else out.push(p);
  }
  return out;
}

/** 返回 'js' / 'java' / null（不审查的文件）。 */
export function classify(name) {
  const lower = name.toLowerCase();
  if (/\.(js|mjs|cjs|ts|jsx|tsx)$/.test(lower)) return 'js';
  if (lower.endsWith('.java')) return 'java';
  return null;
}

// ── 主入口 ─────────────────────────────────────────────────────────

export function review(rootRaw) {
  const root = resolve(rootRaw);
  const isDir = statSync(root).isDirectory();
  const files = isDir ? collect(root, []) : [root];
  const res = { jsFiles: 0, javaFiles: 0, pomFiles: 0, invalidUtf8: 0, pomAtRoot: false, findings: [] };

  for (const abs of files) {
    const rel = isDir ? relative(root, abs).split(sep).join('/') : basename(abs);
    const name = basename(abs);
    if (name === 'pom.xml') {
      res.pomFiles++;
      if (rel === 'pom.xml') res.pomAtRoot = true;
      checkPom(abs, rel, res);
      continue;
    }
    const lang = classify(name);
    if (!lang) continue;
    if (lang === 'js') res.jsFiles++;
    else res.javaFiles++;
    scanFile(abs, rel, lang, res);
  }
  res.findings.sort((a, b) =>
    a.file < b.file ? -1 : a.file > b.file ? 1
      : a.line - b.line || a.col - b.col || (a.rule < b.rule ? -1 : a.rule > b.rule ? 1 : 0));
  return res;
}

// ── 行级扫描 ───────────────────────────────────────────────────────

const utf8Fatal = new TextDecoder('utf-8', { fatal: true });

function scanFile(abs, rel, lang, res) {
  const buf = readFileSync(abs);
  if (buf.length > MAX_FILE_BYTES) return;
  const off = buf.length >= 3 && buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf ? 3 : 0;
  let content;
  try {
    content = utf8Fatal.decode(buf.subarray(off));
  } catch {
    // 非 UTF-8：两侧口径一致——只报 PROJ-ENCODING，跳过行级规则
    res.invalidUtf8++;
    res.findings.push({ file: rel, line: 0, col: 0, rule: 'PROJ-ENCODING', severity: 'WARN',
      message: '文件不是有效 UTF-8（跳过行级规则）', excerpt: '' });
    return;
  }
  const lines = content.split(/\r\n|\n|\r/);
  const js = lang === 'js';
  let state = S_CODE;
  for (let ln = 1; ln <= lines.length; ln++) {
    const raw = lines[ln - 1];
    const sr = stripLine(raw, js, state);
    state = sr.state;
    for (const rule of RULES) {
      if (!applies(rule, lang)) continue;
      if (rule.id === 'GEN-LONGLINE') {
        if (raw.length > LONG_LINE) {
          res.findings.push(mk(rel, ln, LONG_LINE + 1, rule, raw));
        }
        continue;
      }
      const subject = rule.matchOn === 'raw' ? raw : sr.text;
      if (rule._g.length === 1) {
        for (const m of subject.matchAll(rule._g[0])) {
          res.findings.push(mk(rel, ln, m.index + 1, rule, raw));
        }
      } else {
        // all 语义：每条 pattern 都要命中；列号取第 1 条首个命中。
        // 注意用不带 g 的源正则做 .match()——带 g 时 match() 返回字符串数组，没有 .index。
        let all = true;
        let col = -1;
        for (let pi = 0; pi < rule.re.length; pi++) {
          const first = subject.match(rule.re[pi]);
          if (!first) { all = false; break; }
          if (pi === 0) col = first.index + 1;
        }
        if (all) res.findings.push(mk(rel, ln, col, rule, raw));
      }
    }
  }
}

function applies(rule, lang) {
  return rule.target === 'both' || rule.target === lang;
}

function mk(rel, line, col, rule, raw) {
  return { file: rel, line, col, rule: rule.id, severity: rule.sev, message: rule.msg, excerpt: excerpt(raw) };
}

/** 摘录口径（双侧一致）：裁掉首尾空格/制表符，超 120 个 UTF-16 单元截断加省略号。 */
function excerpt(raw) {
  let t = raw.replace(/^[ \t]+|[ \t]+$/g, '');
  if (t.length > 120) t = t.slice(0, 120) + '…';
  return t;
}

// ── 项目级检查 ─────────────────────────────────────────────────────

/** pom.xml 良构性（栈式标签配平；算法与 Java xmlCheck 同构，错误文案两侧逐字一致）。 */
function checkPom(abs, rel, res) {
  const buf = readFileSync(abs);
  if (buf.length > MAX_FILE_BYTES) return;
  const off = buf.length >= 3 && buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf ? 3 : 0;
  const s = buf.subarray(off).toString('utf8');
  const err = xmlCheck(s);
  if (err) {
    res.findings.push({ file: rel, line: err.line, col: err.col, rule: 'PROJ-XML', severity: 'ERROR',
      message: '构建 XML 格式非法: ' + err.reason, excerpt: '' });
  }
}

/**
 * 极简 XML 良构检查：跳过注释 <!-- -->、处理指令 <? ?>、声明 <! ... >（含 DOCTYPE；
 * CDATA 内部结构不识别）；标签栈配平；属性引号内的 > 与 / 不误判。
 * 不支持命名空间前缀合法性校验。
 */
function xmlCheck(s) {
  const names = [];
  const starts = [];
  let i = 0;
  const n = s.length;
  while (i < n) {
    if (s[i] !== '<') { i++; continue; }
    if (s.startsWith('<!--', i)) {
      const e = s.indexOf('-->', i + 4);
      if (e < 0) return errAt(s, i, '注释未闭合');
      i = e + 3; continue;
    }
    if (s.startsWith('<?', i)) {
      const e = s.indexOf('?>', i + 2);
      if (e < 0) return errAt(s, i, '处理指令未闭合');
      i = e + 2; continue;
    }
    if (s.startsWith('<!', i)) {
      const e = s.indexOf('>', i + 2);
      if (e < 0) return errAt(s, i, '声明未闭合');
      i = e + 1; continue;
    }
    if (s.startsWith('</', i)) {
      const gt = s.indexOf('>', i + 2);
      if (gt < 0) return errAt(s, i, "闭合标签缺少 '>'");
      const name = s.slice(i + 2, gt).trim();
      if (names.length === 0) return errAt(s, i, `出现意外闭合标签 </${name}>`);
      const top = names.pop();
      starts.pop();
      if (top !== name) return errAt(s, i, `开闭标签不匹配: 期望 </${top}> 实际 </${name}>`);
      i = gt + 1; continue;
    }
    // 开标签：读名字，扫描到 '>'（尊重引号），判自闭合
    let j = i + 1;
    while (j < n && isNameChar(s[j])) j++;
    const name = s.slice(i + 1, j);
    if (!name) return errAt(s, i, '非法标签起始字符');
    let closed = false;
    let sawSlash = false;
    let inS = false;
    let inD = false;
    while (j < n) {
      const t = s[j];
      if (inS) {
        if (t === "'") inS = false;
      } else if (inD) {
        if (t === '"') inD = false;
      } else if (t === "'") inS = true;
      else if (t === '"') inD = true;
      else if (t === '>') { closed = true; break; }
      else if (t === '/') sawSlash = true;
      else if (!/\s/.test(t)) sawSlash = false;
      j++;
    }
    if (!closed) return errAt(s, i, "标签未闭合(缺少 '>')");
    if (!sawSlash) { names.push(name); starts.push(i); }
    i = j + 1;
  }
  if (names.length > 0) {
    return errAt(s, starts[starts.length - 1], `标签未闭合(文件结束前未关闭 <${names[names.length - 1]}>)`);
  }
  return null;
}

function isNameChar(c) {
  return /[A-Za-z0-9_.-]/.test(c);
}

function errAt(s, idx, reason) {
  let line = 1;
  let lastNl = -1;
  for (let k = 0; k < idx; k++) {
    if (s[k] === '\n') { line++; lastNl = k; }
  }
  return { line, col: idx - lastNl, reason };
}

// ── 单文件速查（dump-file 用）──────────────────────────────────────

export function reviewFile(pathRaw) {
  const abs = resolve(pathRaw);
  const res = { jsFiles: 0, javaFiles: 0, pomFiles: 0, invalidUtf8: 0, pomAtRoot: false, findings: [] };
  const name = basename(abs);
  const lang = classify(name);
  if (name === 'pom.xml') {
    checkPom(abs, name, res);
    res.pomFiles = 1;
  } else if (lang) {
    if (lang === 'js') res.jsFiles = 1; else res.javaFiles = 1;
    scanFile(abs, name, lang, res);
  }
  res.findings.sort((a, b) => a.line - b.line || a.col - b.col || (a.rule < b.rule ? -1 : 1));
  return res;
}
