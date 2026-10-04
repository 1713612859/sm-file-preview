/**
 * 审查规则表 —— 与 src/main/java/com/ppos/sm/Rules.java 逐条镜像。
 * 硬性约定（AGENTS.md 规则 1）：改任何一条规则/口径，必须 JS/Java 双侧同步，
 * 并跑 node js/verify-parity.mjs 回归（fixture 基准 PIN + 双实现 JSON 逐项对账）。
 *
 * 匹配语义（两侧必须一致）：
 * - matchOn:'raw'       对原始行匹配（GEN-TODO 需要——计划标记本来就在注释里）；
 * - matchOn:'stripped'  对「抹掉注释内容」的行匹配；抹除保持行长不变，列号不失真。
 *                       字符串字面量内容保留（凭据/URL 规则要查的就是字符串）；
 * - re 数组多条 = 全部命中才算（all 语义，当前仅 JS-EXEC-DYN），列号取第 1 条首个命中。
 *
 * 正则陷阱（AGENTS「Windows/Git Bash 已知坑」）：
 * - 本表正则一律不带 g 标志；引擎侧用 new RegExp(x.source, 'g') 生成全局副本走 matchAll，
 *   避免带 g 的正则对象被 test/exec 复用时 lastIndex 残留导致漏报。
 */

export const IGNORE_DIRS = [
  'node_modules', 'target', 'out', 'dist', 'build',
  '.git', '.idea', '.zcode', '.vscode', 'coverage', '.settings',
];

export const MAX_FILE_BYTES = 2_000_000;

export const LONG_LINE = 160;

export const RULES = [
  {
    id: 'GEN-TODO', sev: 'WARN', target: 'both', matchOn: 'raw',
    re: [/\b(TODO|FIXME|XXX|HACK)\b:?/],
    msg: '遗留计划标记（TODO/FIXME/XXX/HACK）',
  },
  {
    id: 'GEN-SECRET', sev: 'ERROR', target: 'both', matchOn: 'stripped',
    re: [/(?:\b|_)(password|passwd|secret|api[_-]?key|access[_-]?key|token)(?:\b|_)\s*[:=]\s*["'][^"'\s]{8,}["']/i],
    msg: '疑似硬编码凭据（关键词+引号字面量）',
  },
  {
    id: 'GEN-HTTP', sev: 'WARN', target: 'both', matchOn: 'stripped',
    re: [/\bhttp:\/\/(?!localhost|127\.0\.0\.1|www\.w3\.org)[^\s"']*/],
    msg: '非 HTTPS 外链（localhost/w3.org 豁免）',
  },
  {
    id: 'GEN-LONGLINE', sev: 'INFO', target: 'both', matchOn: 'raw', re: null,
    msg: '行宽超过 160',
  },
  {
    id: 'JS-EVAL', sev: 'ERROR', target: 'js', matchOn: 'stripped',
    re: [/\beval\s*\(|\bnew\s+Function\s*\(/],
    msg: '使用 eval/new Function，存在代码注入风险',
  },
  {
    id: 'JS-DEBUGGER', sev: 'ERROR', target: 'js', matchOn: 'stripped',
    re: [/\bdebugger\b/],
    msg: '遗留 debugger 语句',
  },
  {
    id: 'JS-CONSOLE', sev: 'INFO', target: 'js', matchOn: 'stripped',
    re: [/\bconsole\.(log|debug|info|warn|error|trace)\s*\(/],
    msg: '遗留 console 调试输出',
  },
  {
    id: 'JS-EXEC-DYN', sev: 'WARN', target: 'js', matchOn: 'stripped',
    re: [/\b(exec|execSync)\s*\(\s*[`"']/, /\$\{|["']\s*\+/],
    msg: 'exec/execSync 拼接动态命令，疑似命令注入',
  },
  {
    id: 'JS-LOOSEEQ', sev: 'INFO', target: 'js', matchOn: 'stripped',
    re: [/(?<![=!<>])==(?!=)|(?<!!)!=(?!=)/],
    msg: '宽松相等 ==/!=（建议 ===/!==）',
  },
  {
    id: 'JAVA-SYSOUT', sev: 'INFO', target: 'java', matchOn: 'stripped',
    re: [/\bSystem\.(out|err)\.print\w*\s*\(/],
    msg: '使用 System.out/err 打印，建议改日志',
  },
  {
    id: 'JAVA-STACKTRACE', sev: 'WARN', target: 'java', matchOn: 'stripped',
    re: [/\bprintStackTrace\s*\(/],
    msg: 'printStackTrace 直接打印，建议改日志',
  },
  {
    id: 'JAVA-EMPTY-CATCH', sev: 'WARN', target: 'java', matchOn: 'stripped',
    re: [/\bcatch\s*\([^)]*\)\s*\{\s*\}/],
    msg: '空 catch 块吞异常（仅识别单行形态）',
  },
  {
    id: 'JAVA-SQL-CONCAT', sev: 'WARN', target: 'java', matchOn: 'stripped',
    re: [/["'](select|insert|update|delete)\b[^"']*["']\s*\+/i],
    msg: 'SQL 字符串拼接，疑似注入（建议 PreparedStatement）',
  },
];
