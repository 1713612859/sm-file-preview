package com.ppos.sm;

import java.util.Comparator;

/**
 * 单条审查发现。字段与 {@code js/review-core.mjs} 产出的 findings 元素一一对应
 * （parity 对账面），排序键也一致：file → line → col → rule。
 */
public final class Finding {

    public final String file;
    /** 1 起行号；项目级检查（PROJ-XML/PROJ-ENCODING）为 0。 */
    public final int line;
    /** 1 起列号；项目级检查为 0。 */
    public final int col;
    public final String rule;
    /** ERROR / WARN / INFO。 */
    public final String severity;
    public final String message;
    /** 命中行摘录（两侧空白裁剪 + 120 字符截断口径一致）。 */
    public final String excerpt;

    public Finding(String file, int line, int col, String rule, String severity, String message, String excerpt) {
        this.file = file;
        this.line = line;
        this.col = col;
        this.rule = rule;
        this.severity = severity;
        this.message = message;
        this.excerpt = excerpt;
    }

    public static final Comparator<Finding> ORDER = Comparator
            .comparing((Finding f) -> f.file)
            .thenComparingInt(f -> f.line)
            .thenComparingInt(f -> f.col)
            .thenComparing(f -> f.rule);
}
