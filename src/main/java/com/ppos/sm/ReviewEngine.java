package com.ppos.sm;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;

/**
 * 扫描引擎：目录遍历 → 文件分类（js/java/pom.xml）→ 逐行抹注释匹配规则
 * → 项目级检查（pom.xml 良构性 / UTF-8 有效性）。
 *
 * <p>整条链路与 {@code js/review-core.mjs} 同一份规格实现（双侧同步，AGENTS 规则 1）。
 * 抹注释状态机、正则命中/列号口径、XML 检查算法、excerpt 截断，任何一处行为差异
 * 都会被 {@code js/verify-parity.mjs} 的 JSON 对账揪出来。
 */
public final class ReviewEngine {

    // ── 抹注释状态机（与 js stripLine 同规格）──────────────────────────
    // code=普通代码  block=块注释内（跨行）  sq/dq=单/双引号字符串（不跨行）
    // tq=js 模板串（跨行）。已知近似：Java text block(""")按双引号态近似、CDATA 不识别。
    private static final int S_CODE = 0, S_BLOCK = 1, S_SQ = 2, S_DQ = 3, S_TQ = 4;

    private record StripResult(String text, int state) {
    }

    private record XmlErr(int line, int col, String reason) {
    }

    public static final class ReviewResult {
        public int jsFiles, javaFiles, pomFiles, invalidUtf8;
        public boolean pomAtRoot;
        public final List<Finding> findings = new ArrayList<>();
    }

    public ReviewResult review(Path root) throws IOException {
        ReviewResult r = new ReviewResult();
        List<Path> collected = new ArrayList<>();
        if (Files.isDirectory(root)) {
            collectFiles(root, collected);
        } else {
            collected.add(root);
        }
        for (Path abs : collected) {
            String rel;
            if (Files.isDirectory(root)) {
                rel = root.relativize(abs).toString().replace('\\', '/');
            } else {
                rel = abs.getFileName().toString();
            }
            String name = abs.getFileName().toString();
            if (name.equals("pom.xml")) {
                r.pomFiles++;
                if (rel.equals("pom.xml")) {
                    r.pomAtRoot = true;
                }
                checkPom(abs, rel, r);
                continue;
            }
            String lang = classify(name);
            if (lang == null) {
                continue;
            }
            if ("js".equals(lang)) {
                r.jsFiles++;
            } else {
                r.javaFiles++;
            }
            scanFile(abs, rel, lang, r);
        }
        r.findings.sort(Finding.ORDER);
        return r;
    }

    // ── 文件收集 ─────────────────────────────────────────────────────

    private void collectFiles(Path root, List<Path> out) throws IOException {
        Files.walkFileTree(root, new SimpleFileVisitor<>() {
            @Override
            public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs) {
                if (!dir.equals(root) && Rules.IGNORE_DIRS.contains(dir.getFileName().toString())) {
                    return FileVisitResult.SKIP_SUBTREE;
                }
                return FileVisitResult.CONTINUE;
            }

            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                if (attrs.isRegularFile()) {
                    out.add(file);
                }
                return FileVisitResult.CONTINUE;
            }
        });
    }

    /** 返回 "js" / "java" / null（不审查的文件）。 */
    private String classify(String name) {
        String lower = name.toLowerCase(Locale.ROOT);
        if (lower.endsWith(".js") || lower.endsWith(".mjs") || lower.endsWith(".cjs")
                || lower.endsWith(".ts") || lower.endsWith(".jsx") || lower.endsWith(".tsx")) {
            return "js";
        }
        if (lower.endsWith(".java")) {
            return "java";
        }
        return null;
    }

    // ── 行级扫描 ─────────────────────────────────────────────────────

    private void scanFile(Path abs, String rel, String lang, ReviewResult r) throws IOException {
        if (Files.size(abs) > Rules.MAX_FILE_BYTES) {
            return;
        }
        byte[] bytes = Files.readAllBytes(abs);
        int off = bomOffset(bytes);
        String content;
        try {
            content = StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes, off, bytes.length - off))
                    .toString();
        } catch (CharacterCodingException e) {
            // 非 UTF-8：两侧口径一致——只报 PROJ-ENCODING，跳过行级规则
            //（替换字符解码在两侧引擎语义未必逐位一致，不冒险）。
            r.invalidUtf8++;
            r.findings.add(new Finding(rel, 0, 0, "PROJ-ENCODING", "WARN",
                    "文件不是有效 UTF-8（跳过行级规则）", ""));
            return;
        }
        String[] lines = content.split("\r\n|\n|\r");
        boolean js = "js".equals(lang);
        int state = S_CODE;
        for (int ln = 1; ln <= lines.length; ln++) {
            String raw = lines[ln - 1];
            StripResult sr = stripLine(raw, js, state);
            state = sr.state();
            for (Rules.Rule rule : Rules.RULES) {
                if (!applies(rule, lang)) {
                    continue;
                }
                if (rule.patterns == null) { // GEN-LONGLINE：行宽检查
                    if (raw.length() > Rules.LONG_LINE) {
                        r.findings.add(finding(rel, ln, Rules.LONG_LINE + 1, rule, raw));
                    }
                    continue;
                }
                String subject = rule.rawLine ? raw : sr.text();
                if (rule.patterns.size() == 1) {
                    Matcher m = rule.patterns.get(0).matcher(subject);
                    while (m.find()) {
                        r.findings.add(finding(rel, ln, m.start() + 1, rule, raw));
                    }
                } else {
                    // all 语义：每条 pattern 都要命中；列号取第 1 条首个命中
                    boolean all = true;
                    int col = -1;
                    for (int pi = 0; pi < rule.patterns.size(); pi++) {
                        Matcher m = rule.patterns.get(pi).matcher(subject);
                        if (!m.find()) {
                            all = false;
                            break;
                        }
                        if (pi == 0) {
                            col = m.start() + 1;
                        }
                    }
                    if (all) {
                        r.findings.add(finding(rel, ln, col, rule, raw));
                    }
                }
            }
        }
    }

    private boolean applies(Rules.Rule rule, String lang) {
        return switch (rule.target) {
            case BOTH -> true;
            case JS -> lang.equals("js");
            case JAVA -> lang.equals("java");
        };
    }

    private Finding finding(String rel, int line, int col, Rules.Rule rule, String raw) {
        return new Finding(rel, line, col, rule.id, rule.sev.name(), rule.message, excerpt(raw));
    }

    /** 摘录口径（双侧一致）：裁掉首尾空格/制表符，超 120 个 UTF-16 单元截断加省略号。 */
    private String excerpt(String raw) {
        String t = raw.replaceAll("^[ \\t]+|[ \\t]+$", "");
        if (t.length() > 120) {
            t = t.substring(0, 120) + "…";
        }
        return t;
    }

    /**
     * 抹掉一行里的注释内容，长度保持不变（列号不失真）。
     * 字符串字面量内容保留（凭据/URL 规则要查字符串）；反斜杠转义跳下一字符。
     */
    private StripResult stripLine(String line, boolean js, int stateIn) {
        char[] cs = line.toCharArray();
        int state = stateIn;
        int i = 0;
        while (i < cs.length) {
            char c = cs[i];
            char n = i + 1 < cs.length ? cs[i + 1] : '\0';
            if (state == S_CODE) {
                if (c == '/' && n == '/') {
                    for (int j = i; j < cs.length; j++) {
                        cs[j] = ' ';
                    }
                    return new StripResult(new String(cs), S_CODE);
                }
                if (c == '/' && n == '*') {
                    cs[i] = ' ';
                    cs[i + 1] = ' ';
                    state = S_BLOCK;
                    i += 2;
                    continue;
                }
                if (c == '\'') {
                    state = S_SQ;
                } else if (c == '"') {
                    state = S_DQ;
                } else if (js && c == '`') {
                    state = S_TQ;
                }
                i++;
                continue;
            }
            if (state == S_BLOCK) {
                if (c == '*' && n == '/') {
                    cs[i] = ' ';
                    cs[i + 1] = ' ';
                    state = S_CODE;
                    i += 2;
                    continue;
                }
                cs[i] = ' ';
                i++;
                continue;
            }
            // 字符串态：只跟踪闭合，内容原样保留
            if (c == '\\') {
                i += 2;
                continue;
            }
            if ((state == S_SQ && c == '\'') || (state == S_DQ && c == '"') || (state == S_TQ && c == '`')) {
                state = S_CODE;
                i++;
                continue;
            }
            i++;
        }
        // 行尾：单/双引号串不跨行（回到 code）；块注释与 js 模板串跨行保留
        if (state == S_SQ || state == S_DQ) {
            state = S_CODE;
        }
        return new StripResult(new String(cs), state);
    }

    // ── 项目级检查 ───────────────────────────────────────────────────

    private int bomOffset(byte[] b) {
        return b.length >= 3 && (b[0] & 0xFF) == 0xEF && (b[1] & 0xFF) == 0xBB && (b[2] & 0xFF) == 0xBF ? 3 : 0;
    }

    /** pom.xml 良构性（栈式标签配平；算法与 js xmlCheck 逐行同构，错误文案两侧逐字一致）。 */
    private void checkPom(Path abs, String rel, ReviewResult r) throws IOException {
        if (Files.size(abs) > Rules.MAX_FILE_BYTES) {
            return;
        }
        byte[] bytes = Files.readAllBytes(abs);
        String content = new String(bytes, bomOffset(bytes), bytes.length - bomOffset(bytes), StandardCharsets.UTF_8);
        XmlErr err = xmlCheck(content);
        if (err != null) {
            r.findings.add(new Finding(rel, err.line(), err.col(), "PROJ-XML", "ERROR",
                    "构建 XML 格式非法: " + err.reason(), ""));
        }
    }

    /**
     * 极简 XML 良构检查：跳过注释 {@code <!-- -->}、处理指令 {@code <? ?>}、
     * 声明 {@code <! ... >}（含 DOCTYPE；CDATA 内部结构不识别）；标签栈配平；
     * 属性引号内的 {@code >} 与 {@code /} 不误判。不支持命名空间前缀合法性校验。
     */
    private XmlErr xmlCheck(String s) {
        Deque<String> names = new ArrayDeque<>();
        Deque<Integer> starts = new ArrayDeque<>();
        int n = s.length();
        int i = 0;
        while (i < n) {
            if (s.charAt(i) != '<') {
                i++;
                continue;
            }
            if (s.startsWith("<!--", i)) {
                int e = s.indexOf("-->", i + 4);
                if (e < 0) {
                    return xmlErr(s, i, "注释未闭合");
                }
                i = e + 3;
                continue;
            }
            if (s.startsWith("<?", i)) {
                int e = s.indexOf("?>", i + 2);
                if (e < 0) {
                    return xmlErr(s, i, "处理指令未闭合");
                }
                i = e + 2;
                continue;
            }
            if (s.startsWith("<!", i)) {
                int e = s.indexOf('>', i + 2);
                if (e < 0) {
                    return xmlErr(s, i, "声明未闭合");
                }
                i = e + 1;
                continue;
            }
            if (s.startsWith("</", i)) {
                int gt = s.indexOf('>', i + 2);
                if (gt < 0) {
                    return xmlErr(s, i, "闭合标签缺少 '>'");
                }
                String name = s.substring(i + 2, gt).trim();
                if (names.isEmpty()) {
                    return xmlErr(s, i, "出现意外闭合标签 </" + name + ">");
                }
                String top = names.pop();
                starts.pop();
                if (!top.equals(name)) {
                    return xmlErr(s, i, "开闭标签不匹配: 期望 </" + top + "> 实际 </" + name + ">");
                }
                i = gt + 1;
                continue;
            }
            // 开标签：读名字，扫描到 '>'（尊重引号），判自闭合
            int j = i + 1;
            while (j < n && isNameChar(s.charAt(j))) {
                j++;
            }
            String name = s.substring(i + 1, j);
            if (name.isEmpty()) {
                return xmlErr(s, i, "非法标签起始字符");
            }
            boolean closed = false;
            boolean sawSlash = false;
            boolean inS = false;
            boolean inD = false;
            while (j < n) {
                char t = s.charAt(j);
                if (inS) {
                    if (t == '\'') {
                        inS = false;
                    }
                } else if (inD) {
                    if (t == '"') {
                        inD = false;
                    }
                } else if (t == '\'') {
                    inS = true;
                } else if (t == '"') {
                    inD = true;
                } else if (t == '>') {
                    closed = true;
                    break;
                } else if (t == '/') {
                    sawSlash = true;
                } else if (!Character.isWhitespace(t)) {
                    sawSlash = false;
                }
                j++;
            }
            if (!closed) {
                return xmlErr(s, i, "标签未闭合(缺少 '>')");
            }
            if (!sawSlash) {
                names.push(name);
                starts.push(i);
            }
            i = j + 1;
        }
        if (!names.isEmpty()) {
            return xmlErr(s, starts.peek(), "标签未闭合(文件结束前未关闭 <" + names.peek() + ">)");
        }
        return null;
    }

    private XmlErr xmlErr(String s, int idx, String reason) {
        int line = 1;
        int lastNl = -1;
        for (int k = 0; k < idx; k++) {
            if (s.charAt(k) == '\n') {
                line++;
                lastNl = k;
            }
        }
        return new XmlErr(line, idx - lastNl, reason);
    }

    private boolean isNameChar(char c) {
        return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')
                || c == '_' || c == '.' || c == '-';
    }
}
