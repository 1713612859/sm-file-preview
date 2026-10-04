package com.ppos.sm;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;

/**
 * 控制台摘要 + out/ 下的 Markdown/JSON 报告。
 * 输出形状与 {@code js/review-all.mjs} 保持一致（parity 用 --json 对账，控制台口径也尽量同形）。
 */
public final class ReportWriter {

    private static final String SEP = "=".repeat(62);
    private static final String SUB = "-".repeat(62);
    /** 控制台明细最多列出的条数，超出提示看报告文件（防刷屏）。 */
    private static final int CONSOLE_CAP = 40;

    private ReportWriter() {
    }

    public static String generatedAt() {
        return LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
    }

    public static String stamp() {
        return LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"));
    }

    public static int count(ReviewEngine.ReviewResult r, String sev) {
        return (int) r.findings.stream().filter(f -> f.severity.equals(sev)).count();
    }

    public static void console(String target, ReviewEngine.ReviewResult r, boolean strict) {
        // 行尾显式 "\n"（println 的分隔符在 Windows 是 \r\n，且 setProperty 改不动——
        // JDK17 实测 PrintStream 构造前 setProperty("line.separator") 仍输出 CRLF）。
        // 拼整串一次 print，保证与 Node console.log 逐字节一致（diff/CI 友好）。
        List<String> out = new ArrayList<>();
        int err = count(r, "ERROR");
        int warn = count(r, "WARN");
        int info = count(r, "INFO");
        out.add(SEP);
        out.add(" SM 文件审查 — " + target);
        out.add(SEP);
        out.add("  ❌ ERROR  " + err);
        out.add("  ⚠  WARN  " + warn);
        out.add("  ℹ  INFO  " + info);
        out.add(SUB);
        List<Finding> fs = r.findings;
        int cap = Math.min(fs.size(), CONSOLE_CAP);
        for (int i = 0; i < cap; i++) {
            Finding f = fs.get(i);
            out.add("  " + icon(f.severity) + " " + f.file + ":" + f.line + ":" + f.col
                    + "  " + f.rule + "  " + f.message);
        }
        if (fs.size() > cap) {
            out.add("  …其余 " + (fs.size() - cap) + " 项见 out/ 报告文件");
        }
        out.add(SUB);
        out.add(" 扫描: js " + r.jsFiles + " / java " + r.javaFiles
                + "（另检 XML " + r.pomFiles + " 个，非 UTF-8 跳过 " + r.invalidUtf8 + "）");
        boolean fail = err > 0 || (strict && warn > 0);
        String verdict;
        if (fs.isEmpty()) {
            verdict = "未发现问题 ✅";
        } else if (fail) {
            verdict = "存在失败级问题 ❌（退出码 1）";
        } else if (warn > 0) {
            verdict = "无 ERROR，仅警告/提示 ⚠（退出码 0）";
        } else {
            verdict = "仅 INFO 提示 ℹ（退出码 0）";
        }
        out.add(" 结论: " + verdict);
        out.add(SEP);
        System.out.print(String.join("\n", out) + "\n");
    }

    private static String icon(String sev) {
        return switch (sev) {
            case "ERROR" -> "❌";
            case "WARN" -> "⚠";
            default -> "ℹ";
        };
    }

    /** JSON 手写序列化（零依赖）；控制字符转义口径与 JSON.stringify 一致（小写 \\u00xx）。 */
    public static String json(String target, ReviewEngine.ReviewResult r) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append("  \"tool\": \"sm-file-review\",\n");
        sb.append("  \"version\": \"1.0\",\n");
        sb.append("  \"target\": ").append(jstr(target)).append(",\n");
        sb.append("  \"generatedAt\": ").append(jstr(generatedAt())).append(",\n");
        sb.append("  \"files\": {\"scanned\": ").append(r.jsFiles + r.javaFiles)
                .append(", \"js\": ").append(r.jsFiles)
                .append(", \"java\": ").append(r.javaFiles)
                .append(", \"pom\": ").append(r.pomFiles)
                .append(", \"pomAtRoot\": ").append(r.pomAtRoot)
                .append(", \"invalidUtf8\": ").append(r.invalidUtf8).append("},\n");
        sb.append("  \"summary\": {\"ERROR\": ").append(count(r, "ERROR"))
                .append(", \"WARN\": ").append(count(r, "WARN"))
                .append(", \"INFO\": ").append(count(r, "INFO")).append("},\n");
        sb.append("  \"findings\": [");
        for (int i = 0; i < r.findings.size(); i++) {
            Finding f = r.findings.get(i);
            sb.append(i == 0 ? "\n" : ",\n");
            sb.append("    {\"file\": ").append(jstr(f.file))
                    .append(", \"line\": ").append(f.line)
                    .append(", \"col\": ").append(f.col)
                    .append(", \"rule\": ").append(jstr(f.rule))
                    .append(", \"severity\": ").append(jstr(f.severity))
                    .append(", \"message\": ").append(jstr(f.message))
                    .append(", \"excerpt\": ").append(jstr(f.excerpt)).append("}");
        }
        sb.append(r.findings.isEmpty() ? "]" : "\n  ]");
        sb.append("\n}");
        return sb.toString();
    }

    private static String jstr(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> b.append("\\\"");
                case '\\' -> b.append("\\\\");
                case '\n' -> b.append("\\n");
                case '\r' -> b.append("\\r");
                case '\t' -> b.append("\\t");
                case '\b' -> b.append("\\b");
                case '\f' -> b.append("\\f");
                default -> {
                    if (c < 0x20) {
                        b.append(String.format("\\u%04x", (int) c));
                    } else {
                        b.append(c);
                    }
                }
            }
        }
        return b.append('"').toString();
    }

    public static String markdown(String target, ReviewEngine.ReviewResult r) {
        StringBuilder sb = new StringBuilder();
        sb.append("# SM 文件审查报告\n\n");
        sb.append("- 目标: ").append(target).append('\n');
        sb.append("- 时间: ").append(generatedAt()).append('\n');
        sb.append("- 扫描: js ").append(r.jsFiles).append(" / java ").append(r.javaFiles)
                .append("（另检 XML ").append(r.pomFiles).append(" 个，非 UTF-8 跳过 ")
                .append(r.invalidUtf8).append("）\n");
        sb.append("- 结论: ERROR ").append(count(r, "ERROR"))
                .append(" / WARN ").append(count(r, "WARN"))
                .append(" / INFO ").append(count(r, "INFO")).append('\n');
        sb.append("\n| # | 级别 | 文件 | 行:列 | 规则 | 说明 | 摘录 |\n");
        sb.append("|---|---|---|---|---|---|---|\n");
        for (int i = 0; i < r.findings.size(); i++) {
            Finding f = r.findings.get(i);
            sb.append("| ").append(i + 1)
                    .append(" | ").append(f.severity)
                    .append(" | `").append(f.file).append("`")
                    .append(" | ").append(f.line).append(":").append(f.col)
                    .append(" | ").append(f.rule)
                    .append(" | ").append(mdCell(f.message))
                    .append(" | `").append(mdCell(f.excerpt)).append("` |")
                    .append('\n');
        }
        if (r.findings.isEmpty()) {
            sb.append("| - | - | - | - | - | 未发现问题 | - |\n");
        }
        return sb.toString();
    }

    /** Markdown 表格单元里的竖线转义。 */
    private static String mdCell(String s) {
        return s.replace("|", "\\|");
    }
}
