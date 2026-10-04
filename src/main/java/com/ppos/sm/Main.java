package com.ppos.sm;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * SM 文件审查 —— Java 侧入口（与 {@code js/review-all.mjs} 同一套规则与输出形状）。
 *
 * <p>用法：
 * <pre>
 *   mvn -q exec:java "-Dexec.args=fixture"            # 审查 fixture/（控制台摘要 + out/ 报告）
 *   mvn -q exec:java "-Dexec.args=fixture --json"     # stdout 只出 JSON（parity 对账用）
 *   mvn -q exec:java "-Dexec.args=&lt;路径&gt; --strict"    # WARN 也计失败
 * </pre>
 *
 * <p>注意：Windows 控制台默认 GBK，本类已把 stdout/stderr 强制 UTF-8——管道/文件采集
 * 不乱码，但 GBK 控制台直接看中文可能花屏（参考 README「Windows 已知坑」）。
 */
public final class Main {

    static {
        // Windows 控制台默认 GBK；统一 UTF-8 输出，管道/文件采集才不乱码
        // （控制台直接看中文若乱码，参考 README「Windows 已知坑」）。
        // 行尾统一由 ReportWriter 显式 "\n" 拼串实现（println 在 Windows 输出 CRLF，
        // 且 setProperty("line.separator") 实测改不动，勿再走那条路）。
        System.setOut(new PrintStream(new FileOutputStream(FileDescriptor.out), true, StandardCharsets.UTF_8));
        System.setErr(new PrintStream(new FileOutputStream(FileDescriptor.err), true, StandardCharsets.UTF_8));
    }

    private Main() {
    }

    public static void main(String[] args) throws Exception {
        String target = "fixture";
        boolean json = false;
        boolean strict = false;
        for (String a : args) {
            if (a.equals("--json")) {
                json = true;
            } else if (a.equals("--strict")) {
                strict = true;
            } else {
                target = a;
            }
        }
        Path root = Path.of(target);
        if (!Files.exists(root)) {
            System.err.println("目标不存在: " + target);
            System.exit(2);
        }

        ReviewEngine.ReviewResult r = new ReviewEngine().review(root);

        // 报告永远落 out/（不入库）；--json 时 stdout 只出 JSON
        String ts = ReportWriter.stamp();
        Path outDir = Path.of("out");
        Files.createDirectories(outDir);
        Files.writeString(outDir.resolve("review-" + ts + ".json"), ReportWriter.json(target, r), StandardCharsets.UTF_8);
        Files.writeString(outDir.resolve("review-" + ts + ".md"), ReportWriter.markdown(target, r), StandardCharsets.UTF_8);

        if (json) {
            System.out.println(ReportWriter.json(target, r));
        } else {
            ReportWriter.console(target, r, strict);
        }
        int err = ReportWriter.count(r, "ERROR");
        int warn = ReportWriter.count(r, "WARN");
        System.exit(err > 0 || (strict && warn > 0) ? 1 : 0);
    }
}
