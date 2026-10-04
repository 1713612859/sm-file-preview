#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SM SIA 逐笔重算对拍 —— 按定案口径公式重算每笔交易,与已认证样例逐字段比对。

与 sia_generator.py 的区别:generator 是"样例值平移重排"(值不重算);
本脚本是**计算引擎对拍**——输入只取 样例的商品构成(明细原价/数量)、场景类型、
支付拆分(类型+金额),其余 63 列金额与明细成交价全部由公式重算,再逐字段与
已认证样例比对。研发的 SMFileGenerator 达到什么水平,跑本脚本就知道差在哪。
共享常量与函数见 sia_common.py(改动需三条工具全量回归)。

口径(全部源自 02 金样例实测归纳 + 2026-10-04 EJ 定案):
  plain    : Net=应税/1.12, Tax=Net×12%
  S2/S3/S14: 免税品 D(原价即净额)不计 VAT,TaxExempt=D 原价
  scpwd    : LessTax=原价−净额;折扣=净额×20%;Net=净额−折扣;Tax=0;TaxExempt=Net;客数列=1
  mov      : 折扣=净额×20%;Net=净额−折扣;Tax=净额(折前)×12%;应付=Gross−折扣
  pct      : 折扣=含税×率;Net=(含税−折扣)/1.12;Tax=Net×12%
  voucher  : 券额按原价比例摊到每行;Net=(合计−券)/1.12
  itempct  : 逐商品 ×率
  ltax     : 地方税=Net×5%(样例口径并入 TotalTax)
  svc      : 服务费=Net×5% 计入 Gross、摊入明细成交价(免税品净额=原价)
  明细折扣口径 B:disc=原价−成交价(含免税部分)
注意:svc 场景的样例明细 Menu 价已含服务费(模式⑤),作输入前先逆还原
  (应税品 ÷(1+rate/1.12),免税品 D ÷(1+rate))。

用法:
  python sia_recompute.py [--source <金样例目录>] [--order 64] [--out-dir out]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sia_common import R, classify_tender, load_csv, money

GOLDEN_DEFAULT = r"C:\Users\Administrator\Desktop\SM mall 认证\02_认证样例数据(SM提供)\SM SIA TestScenarios 2024-07-31"

# 场景表:按营业日(样例 2024-07)识别
SCEN = {
    "07-01": ("S1", "plain", {}), "07-02": ("S2", "plain", {"exemptD": True}),
    "07-03": ("S3", "plain", {"exemptD": True}), "07-04": ("S4", "scpwd", {"col": "Senior Citizen Discount Amount"}),
    "07-05": ("S5", "pct", {"rate": 0.10, "col": "VIP Discount Amount"}),
    "07-06": ("S6", "scpwd", {"col": "PWD Discount Amount"}),
    "07-07": ("S7", "mov", {"col": "National Coach / Athlete /  Medal of Valor Discount amount"}),
    "07-08": ("S8", "pct", {"rate": 0.20, "col": "Regular / Other Discount Amount"}),
    "07-09": ("S9", "pct", {"rate": 0.20, "col": "Employee Discount Amount"}),
    "07-10": ("S10", "voucher", {"amount": 500.0, "col": "Online Deals Discount Amount"}),
    "07-11": ("S11", "itempct", {"rate": 0.05, "col": "SMAC Discount Amount"}),
    "07-12": ("S12", "ltax", {"rate": 0.05}), "07-13": ("S13", "svc", {"rate": 0.05}),
    "07-14": ("S14", "svc", {"rate": 0.05, "exemptD": True}), "07-15": ("S15", "svc_ltax", {"svc": 0.05, "ltax": 0.05}),
    "07-16": ("S16", "plain", {}), "07-19": ("S19A", "plain", {}), "07-20": ("S19R", "refund", {}),
}

DISCOUNT_COLS = ["Regular / Other Discount Amount", "Employee Discount Amount",
                 "Senior Citizen Discount Amount", "VIP Discount Amount", "PWD Discount Amount",
                 "National Coach / Athlete /  Medal of Valor Discount amount", "SMAC Discount Amount",
                 "Online Deals Discount Amount"]
TENDER_COLS = ["Total Cash Sales Amount", "Total Gift Cheque / Gift Card Sales Amount",
               "Total Debit Card Sales Amount", "Total E-wallet / Online Sales Amount",
               "Total Other Tender Sales Amount", "Total Mastercard Sales Amount",
               "Total Visa Sales Amount", "Total American Express Sales Amount",
               "Total Diners Sales Amount", "Total JCB Sales Amount", "Total Other Credit Card Sales Amount"]
MAIN_MONEY = ["Gross Sales Amount", "Net Sales Amount", "Total Tax", "Other/Local Tax",
              "Total Service Charge", "Total Discount", "Less Tax Amount", "Tax Exempt Sales"] \
             + DISCOUNT_COLS + TENDER_COLS
# 支付归类 → 主表汇总列(Other 列另按样例口径=other+信用卡重复计入)
TCOL = {"cash": "Total Cash Sales Amount", "gc": "Total Gift Cheque / Gift Card Sales Amount",
        "debit": "Total Debit Card Sales Amount", "ewallet": "Total E-wallet / Online Sales Amount",
        "mc": "Total Mastercard Sales Amount", "visa": "Total Visa Sales Amount",
        "amex": "Total American Express Sales Amount", "diners": "Total Diners Sales Amount"}
DSLOT_NAME, DSLOT_QTY, DSLOT_TX, DSLOT_MENU, DSLOT_DISC = 2, 5, 6, 7, 9


def is_exempt_d(name: str, cfg: dict) -> bool:
    """免税品判定:商品名最后一个词精确等于 D(勿用 'D' in name —— 'SM Prod' 必误中)。"""
    return bool(cfg.get("exemptD")) and name.strip().upper().split()[-1] == "D"


def recompute(items, scen_kind, cfg, neg):
    """重算主表金额字段与明细行期望值。items=[{name,qty,menu}],neg=True 为作废/退款。"""
    menu_total = R(sum(i["qty"] * i["menu"] for i in items))
    exempt_menu = R(sum(i["qty"] * i["menu"] for i in items if is_exempt_d(i["name"], cfg)))
    net_v = R(R(menu_total - exempt_menu) / 1.12)      # 应税部分净额(免税品净额=原价)
    exempt_v = exempt_menu
    sign = -1.0 if neg else 1.0

    d = {c: 0.0 for c in MAIN_MONEY}
    disc_col = cfg.get("col")
    less = exempt = disc = 0.0

    if scen_kind == "plain":
        tax, net, exempt = R(net_v * 0.12), R(net_v + exempt_v), exempt_v
        gross = R(net + tax)
    elif scen_kind == "scpwd":
        less = R(menu_total - net_v)
        disc = R(net_v * 0.20)
        net = exempt = R(net_v - disc)
        tax, gross = 0.0, menu_total
    elif scen_kind == "mov":
        disc = R(net_v * 0.20)
        net, tax = R(net_v - disc), R(net_v * 0.12)
        gross = menu_total
    elif scen_kind == "pct":
        disc = R((menu_total - exempt_menu) * cfg["rate"])
        taxed_net = R((menu_total - exempt_menu - disc) / 1.12)
        net, tax, exempt = R(taxed_net + exempt_v), R(taxed_net * 0.12), exempt_v
        gross = menu_total
    elif scen_kind == "voucher":
        disc = cfg["amount"]
        net = R((menu_total - disc) / 1.12)
        tax, gross = R(net * 0.12), menu_total
    elif scen_kind == "itempct":
        disc = R(sum(R(i["menu"] * i["qty"] * cfg["rate"]) for i in items))
        net = R((menu_total - disc) / 1.12)
        tax, gross = R(net * 0.12), menu_total
    elif scen_kind == "ltax":
        net = R(net_v + exempt_v)
        lt = R(net * cfg["rate"])
        tax = R(net_v * 0.12 + lt)
        gross = R(net + tax)
        d["Other/Local Tax"] = lt
    elif scen_kind == "svc":
        net = R(net_v + exempt_v)
        exempt = exempt_v
        sv = R(net * cfg["rate"])
        tax = R(net_v * 0.12)
        gross = R(net + tax + sv)
        d["Total Service Charge"] = sv
    elif scen_kind == "svc_ltax":
        net = R(net_v + exempt_v)
        sv, lt = R(net * cfg["svc"]), R(net * cfg["ltax"])
        tax = R(net_v * 0.12 + lt)
        gross = R(net + tax + sv)
        d["Total Service Charge"], d["Other/Local Tax"] = sv, lt
    elif scen_kind == "refund":
        tax, net = R(net_v * 0.12), R(net_v + exempt_v)
        gross = R(net + tax)
    else:
        raise ValueError(scen_kind)

    d.update({"Gross Sales Amount": R(gross * sign), "Net Sales Amount": R(net * sign),
              "Total Tax": R(tax * sign), "Less Tax Amount": R(less * sign),
              "Tax Exempt Sales": R(exempt * sign), "Total Discount": R(disc * sign)})
    if disc_col and disc:
        d[disc_col] = R(disc * sign)

    # ---- 明细行期望(tx=成交价,disc=口径B 原价−成交价) ----
    det = []
    for i in items:
        m, q = i["menu"], i["qty"]
        n_i = m if is_exempt_d(i["name"], cfg) else R(m / 1.12)
        if scen_kind == "scpwd":
            di = R(n_i * 0.20)
            tx = R(n_i - di)
        elif scen_kind == "mov":
            di = R(n_i * 0.20)
            tx = R(m - di)
        elif scen_kind == "pct":
            di = R(R(m * q * cfg["rate"]) / q) if q else 0.0
            tx = R(m - di)
        elif scen_kind == "itempct":
            di = R(m * cfg["rate"])
            tx = R(m - di)
        elif scen_kind == "voucher":
            di = R(R(m * q * (disc / menu_total)) / q) if q else 0.0
            tx = R(m - di)
        elif scen_kind in ("svc", "svc_ltax"):
            di = 0.0
            tx = R(m + R(n_i * (cfg.get("rate") or cfg.get("svc"))))
        else:
            di, tx = 0.0, m
        det.append({"name": i["name"], "qty": q, "tx": tx,
                    "disc": R(m - tx) if (di or scen_kind in ("scpwd", "mov", "voucher")) else 0.0})
    return d, det


def main():
    ap = argparse.ArgumentParser(description="SM SIA 逐笔重算对拍")
    ap.add_argument("--source", default=GOLDEN_DEFAULT)
    ap.add_argument("--order", help="只对拍指定订单号(详细输出)")
    ap.add_argument("--out-dir", default="out")
    args = ap.parse_args()

    src = Path(args.source)
    tx = load_csv(sorted(src.glob("*_transactions.csv"))[0])
    dt = load_csv(sorted(src.glob("*_transactiondetails.csv"))[0])
    ix = {n: i for i, n in enumerate(tx[0])}
    det_by_order = defaultdict(list)               # 一遍建索引:items 输入与明细比对共用
    for r in dt[1:]:
        det_by_order[r[0]].append(r)
    items_of = lambda o: [{"name": r[DSLOT_NAME], "qty": abs(money(r[DSLOT_QTY]) or 0),
                           "menu": money(r[DSLOT_MENU]) or 0} for r in det_by_order[o]]

    results = []
    for row in tx[1:]:
        o = row[ix["Order Num / Bill Num"]]
        if args.order and o != args.order:
            continue
        day = row[ix["Business Day"]]
        if day[5:] not in SCEN:
            results.append((o, day, "?SCEN-UNKNOWN",
                            [("场景未识别(营业日无场景配置,该笔未对拍)", 0, 0, "")]))
            continue
        scen, kind, cfg = SCEN[day[5:]]
        neg = row[ix["Void"]] == "1" or row[ix["Refund"]] == "1"
        items = items_of(o)
        # svc 场景的样例明细 Menu 价已含服务费,先逆还原为裸原价再作输入
        if kind in ("svc", "svc_ltax"):
            rate = cfg.get("rate") or cfg.get("svc")
            for it in items:
                div = (1 + rate) if is_exempt_d(it["name"], cfg) else (1 + rate / 1.12)
                it["menu"] = R(it["menu"] / div)
        exp, det_exp = recompute(items, kind, cfg, neg)

        # 支付拆分为输入;汇总列按归类严格重算(负单也严格取负)
        agg = defaultdict(float)
        for k in (1, 2, 3):
            if row[ix[f"Payment Type_{k}"]]:
                cat = classify_tender(row[ix[f"Payment Type_{k}"]]) or "other"
                agg[cat] += money(row[ix[f"Payment Amount_{k}"]]) or 0
        for cat, col in TCOL.items():
            exp[col] = R(agg.get(cat, 0.0))
        cc_total = sum(agg.get(c, 0.0) for c in ("mc", "visa", "amex", "diners", "jcb", "othercc"))
        exp["Total Other Tender Sales Amount"] = R(agg.get("other", 0.0) + cc_total)
        exp["Total Other Credit Card Sales Amount"] = R(agg.get("othercc", 0.0))

        # ---- 主表比对 ----
        diffs = []
        for c in MAIN_MONEY:
            act = money(row[ix[c]]) or 0
            if abs(act - exp[c]) > 0.005:
                tag = "KNOWN-QUIRK(负单汇总列样例不严格)" if neg and c in TENDER_COLS else ""
                diffs.append((c, exp[c], act, tag))
        if kind == "scpwd":  # 客数(Senior/PWD 场景)
            gcol = "Guest Count (Senior)" if "Senior" in cfg["col"] else "Guest Count (PWD)"
            if money(row[ix[gcol]]) != 1:
                diffs.append((gcol, 1, money(row[ix[gcol]]) or 0, ""))
        # ---- 明细比对 ----
        golden_det = det_by_order[o]
        if len(golden_det) == len(det_exp):
            for g, e in zip(golden_det, det_exp):
                for label, gi, ev in (("明细成交价", DSLOT_TX, e["tx"]), ("明细折扣额", DSLOT_DISC, e["disc"])):
                    if abs((money(g[gi]) or 0) - ev) > 0.005:
                        diffs.append((f"{e['name']}·{label}", ev, money(g[gi]) or 0, ""))
        else:
            diffs.append(("明细行数", len(det_exp), len(golden_det), ""))
        results.append((o, day, scen, diffs))

    total = len(results)
    clean = sum(1 for r in results if not r[3])
    print(f"对拍完成: {total} 笔 | 完全一致 {clean} | 存在差异 {total - clean}")
    for o, day, scen, diffs in results:
        if diffs:
            print(f"  订单 {o}({day} {scen}):")
            for c, e, a, tag in diffs:
                print(f"    - {c}: 期望 {e:.2f} / 实际 {a:.2f} {'[' + tag + ']' if tag else ''}")
        elif args.order:
            print(f"  订单 {o}({day} {scen}): ✓ 全部字段一致")

    # 报告落盘
    out = Path(args.out_dir) / f"sia_recompute_{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    L = ["# SM SIA 逐笔重算对拍报告", "",
         f"- 数据源(已认证样例): `{src}`",
         f"- 方法:输入=商品构成/场景/支付拆分;输出=63 列金额与明细成交价全部公式重算,逐字段比对(容差 0.005)",
         f"- 结果:**{clean}/{total} 完全一致**;差异 {total - clean} 笔(明细如下,含已知样例怪癖)", ""]
    quirk = plain = 0
    for o, day, scen, diffs in results:
        if not diffs:
            continue
        L.append(f"## 订单 {o}({day} {scen})")
        for c, e, a, tag in diffs:
            if tag:
                quirk += 1
            else:
                plain += 1
            L.append(f"- {c}: 期望 {e:.2f} / 实际 {a:.2f} {('— ' + tag) if tag else ''}")
        L.append("")
    L.append(f"差异合计 {quirk + plain} 处:已知样例怪癖(负单汇总列不严格) {quirk} 处;真实口径差异 {plain} 处")
    out.write_text("\n".join(L), encoding="utf-8", newline="")
    print(f"报告: {out}")
    sys.exit(1 if plain else 0)  # 真实口径差异 → 非零退出(CI 拦截);已知怪癖不拦截


if __name__ == "__main__":
    main()
