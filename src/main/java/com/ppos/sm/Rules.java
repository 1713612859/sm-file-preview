package com.ppos.sm;

import java.util.List;
import java.util.regex.Pattern;

/**
 * 审查规则表 —— 与 {@code js/rules.mjs} 逐条镜像。
 *
 * <p>硬性约定（AGENTS.md 规则 1）：改任何一条规则/口径，必须 JS/Java 双侧同步，
 * 并跑 {@code node js/verify-parity.mjs} 回归（fixture 基准 PIN + 双实现 JSON 逐项对账）。
 *
 * <p>匹配语义（两侧必须一致）：
 * <ul>
 *   <li>{@code rawLine=true}：对原始行匹配（GEN-TODO 需要——计划标记本来就在注释里，
 *       字符串里的 TODO 也会报，属已知可接受的误报面）；</li>
 *   <li>{@code rawLine=false}：对「抹掉注释内容」的行匹配；抹除保持行长不变，列号不失真。
 *       字符串字面量内容保留（凭据/URL 规则要查的就是字符串）；</li>
 *   <li>{@code patterns} 多条 = 全部命中才算（all 语义，当前仅 JS-EXEC-DYN），
 *       列号取第 1 条的首个命中位置。</li>
 * </ul>
 */
public final class Rules {

    public enum Sev { ERROR, WARN, INFO }

    /** 规则适用的目标语言。BOTH = js 行与 java 行都适用。 */
    public enum Target { JS, JAVA, BOTH }

    public static final class Rule {
        public final String id;
        public final Sev sev;
        public final Target target;
        public final boolean rawLine;
        /** null = GEN-LONGLINE 特殊形态（行宽检查，无正则）。 */
        public final List<Pattern> patterns;
        public final String message;

        Rule(String id, Sev sev, Target target, boolean rawLine, List<Pattern> patterns, String message) {
            this.id = id;
            this.sev = sev;
            this.target = target;
            this.rawLine = rawLine;
            this.patterns = patterns;
            this.message = message;
        }
    }

    /** 忽略目录（任意一层命中即整棵子树跳过），双侧同表。 */
    public static final List<String> IGNORE_DIRS = List.of(
            "node_modules", "target", "out", "dist", "build",
            ".git", ".idea", ".zcode", ".vscode", "coverage", ".settings");

    /** 超过该字节数的文件跳过（防误扫构建产物/大型生成文件），双侧同值。 */
    public static final long MAX_FILE_BYTES = 2_000_000;

    /** 行宽阈值（GEN-LONGLINE），双侧同值。 */
    public static final int LONG_LINE = 160;

    public static final List<Rule> RULES = List.of(
            rule("GEN-TODO", Sev.WARN, Target.BOTH, true,
                    "\\b(TODO|FIXME|XXX|HACK)\\b:?",
                    "遗留计划标记（TODO/FIXME/XXX/HACK）"),
            rule("GEN-SECRET", Sev.ERROR, Target.BOTH, false, true,
                    "(?:\\b|_)(password|passwd|secret|api[_-]?key|access[_-]?key|token)(?:\\b|_)\\s*[:=]\\s*[\"'][^\"'\\s]{8,}[\"']",
                    "疑似硬编码凭据（关键词+引号字面量）"),
            rule("GEN-HTTP", Sev.WARN, Target.BOTH, false,
                    "\\bhttp://(?!localhost|127\\.0\\.0\\.1|www\\.w3\\.org)[^\\s\"']*",
                    "非 HTTPS 外链（localhost/w3.org 豁免）"),
            rule("GEN-LONGLINE", Sev.INFO, Target.BOTH, true, null,
                    "行宽超过 160"),
            rule("JS-EVAL", Sev.ERROR, Target.JS, false,
                    "\\beval\\s*\\(|\\bnew\\s+Function\\s*\\(",
                    "使用 eval/new Function，存在代码注入风险"),
            rule("JS-DEBUGGER", Sev.ERROR, Target.JS, false,
                    "\\bdebugger\\b",
                    "遗留 debugger 语句"),
            rule("JS-CONSOLE", Sev.INFO, Target.JS, false,
                    "\\bconsole\\.(log|debug|info|warn|error|trace)\\s*\\(",
                    "遗留 console 调试输出"),
            ruleAll("JS-EXEC-DYN", Sev.WARN, Target.JS, false,
                    List.of("\\b(exec|execSync)\\s*\\(\\s*[`\"']", "\\$\\{|[\"']\\s*\\+"),
                    "exec/execSync 拼接动态命令，疑似命令注入"),
            rule("JS-LOOSEEQ", Sev.INFO, Target.JS, false,
                    "(?<![=!<>])==(?!=)|(?<!!)!=(?!=)",
                    "宽松相等 ==/!=（建议 ===/!==）"),
            rule("JAVA-SYSOUT", Sev.INFO, Target.JAVA, false,
                    "\\bSystem\\.(out|err)\\.print\\w*\\s*\\(",
                    "使用 System.out/err 打印，建议改日志"),
            rule("JAVA-STACKTRACE", Sev.WARN, Target.JAVA, false,
                    "\\bprintStackTrace\\s*\\(",
                    "printStackTrace 直接打印，建议改日志"),
            rule("JAVA-EMPTY-CATCH", Sev.WARN, Target.JAVA, false,
                    "\\bcatch\\s*\\([^)]*\\)\\s*\\{\\s*\\}",
                    "空 catch 块吞异常（仅识别单行形态）"),
            rule("JAVA-SQL-CONCAT", Sev.WARN, Target.JAVA, false, true,
                    "[\"'](select|insert|update|delete)\\b[^\"']*[\"']\\s*\\+",
                    "SQL 字符串拼接，疑似注入（建议 PreparedStatement）"));

    private Rules() {
    }

    private static Rule rule(String id, Sev sev, Target t, boolean rawLine, String regex, String msg) {
        return new Rule(id, sev, t, rawLine, regex == null ? null : List.of(Pattern.compile(regex)), msg);
    }

    /** ci=true 时大小写不敏感（关键词均为纯 ASCII，Java/JS 折叠行为一致）。 */
    private static Rule rule(String id, Sev sev, Target t, boolean rawLine, boolean ci, String regex, String msg) {
        return new Rule(id, sev, t, rawLine,
                regex == null ? null : List.of(Pattern.compile(regex, ci ? Pattern.CASE_INSENSITIVE : 0)), msg);
    }

    private static Rule ruleAll(String id, Sev sev, Target t, boolean rawLine, List<String> regexes, String msg) {
        return new Rule(id, sev, t, rawLine, regexes.stream().map(Pattern::compile).toList(), msg);
    }
}
