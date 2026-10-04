#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SM SIA 工具链公共库 —— validator / generator / recompute 共用的常量与函数。

单一事实源:表头与槽位、字段分类清单、支付归类、取整、严格 CSV 解析。
改动本文件后必须三条工具全量回归(任一不绿即回退):
  1) 金样例校准 0 ERROR   2) generator 自校验 0 ERROR 且 E05 篡改测试可抓
  3) recompute 311/313(仅 2 笔负单汇总列已知怪癖)
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# ---------------- 主表 63 列(与 V1.5/需求文档 §13.2 完全一致) ----------------
TX_HEADER = [
    "Order Num / Bill Num", "Business Day", "Check Open", "Check Close", "Sales Type",
    "Transaction Type", "Void", "Void Amount", "Refund", "Refund Amount", "Guest Count",
    "Guest Count (Senior)", "Guest Count (PWD)", "Gross Sales Amount", "Net Sales Amount",
    "Total Tax", "Other/Local Tax", "Total Service Charge", "Total Tip", "Total Discount",
    "Less Tax Amount", "Tax Exempt Sales", "Regular / Other Discount Name",
    "Regular / Other Discount Amount", "Employee Discount Amount", "Senior Citizen Discount Amount",
    "VIP Discount Amount", "PWD Discount Amount",
    "National Coach / Athlete /  Medal of Valor Discount amount", "SMAC Discount Amount",
    "Online Deals Discount Name", "Online Deals Discount Amount", "Discount Field 1 Name",
    "Discount Field 2 Name", "Discount Field 3 Name", "Discount Field 4 Name", "Discount Field 5 Name",
    "Discount Field 6 Name", "Discount Field 1 Amount", "Discount Field 2 Amount", "Discount Field 3 Amount",
    "Discount Field 4 Amount", "Discount Field 5 Amount", "Discount Field 6 Amount", "Payment Type_1",
    "Payment Amount_1", "Payment Type_2", "Payment Amount_2", "Payment Type_3", "Payment Amount_3",
    "Total Cash Sales Amount", "Total Gift Cheque / Gift Card Sales Amount", "Total Debit Card Sales Amount",
    "Total E-wallet / Online Sales Amount", "Total Other Tender Sales Amount", "Total Mastercard Sales Amount",
    "Total Visa Sales Amount", "Total American Express Sales Amount", "Total Diners Sales Amount",
    "Total JCB Sales Amount", "Total Other Credit Card Sales Amount", "Terminal Number", "Serial Number",
]

# ---------------- 明细表两种布局 ----------------
DET_HEADER_SPEC = [
    "Order Num / Bill Num", "Item ID", "Item Name", "Item Parent Category", "Item Category",
    "Item Sub-Category", "Item Quantity", "Transaction Item Price", "Menu Item Price",
    "Discount Code", "Discount Amount", "Modifier (1) Name", "Modifier (1) Quantity",
    "Modifier (2) Name", "Modifier (2) Quantity", "Void", "Void Amount", "Refund", "Refund Amount",
]
DET_HEADER_SAMPLE = [
    "Order Num / Bill Num", "Item ID Item Name", "Item Parent Category", "Item Category",
    "Item Sub-Category", "Item Quantity", "Transaction Item Price", "Menu Item Price",
    "Discount Code", "Discount Amount", "Modifier (1) Name", "Modifier (1) Quantity",
    "Modifier (2) Name", "Modifier (2) Quantity", "Void", "Void Amount", "Refund", "Refund Amount",
]
# sample 布局表头合并 "Item ID Item Name",数据仍是两列 → 槽位手工固定
DET_SLOTS_SAMPLE = {
    "Order Num / Bill Num": 0, "Item ID": 1, "Item Name": 2, "Item Parent Category": 3,
    "Item Category": 4, "Item Quantity": 5, "Transaction Item Price": 6, "Menu Item Price": 7,
    "Discount Code": 8, "Discount Amount": 9, "Modifier (1) Name": 10, "Modifier (1) Quantity": 11,
    "Modifier (2) Name": 12, "Modifier (2) Quantity": 13, "Void": 14, "Void Amount": 15,
    "Refund": 16, "Refund Amount": 17,
}


def detect_det_slots(header):
    """按实际表头探测明细槽位,返回 (slots, 布局名);无法识别返回 (None, None)。

    无论期望哪种布局,解析槽位都跟随实际表头,避免错位/越界;期望不符由调用方报 F03。
    """
    if header == DET_HEADER_SAMPLE:
        return DET_SLOTS_SAMPLE, "sample"
    if header == DET_HEADER_SPEC:
        return {n: i for i, n in enumerate(DET_HEADER_SPEC)}, "spec"
    return None, None


# ---------------- 字段分类清单(预计算) ----------------
TX_NULLABLE = {
    "Transaction Type", "Regular / Other Discount Name", "Online Deals Discount Name",
    "Discount Field 1 Name", "Discount Field 2 Name", "Discount Field 3 Name",
    "Discount Field 4 Name", "Discount Field 5 Name", "Discount Field 6 Name",
    "Payment Type_2", "Payment Type_3",
}
TX_NUMERIC_COLS = [n for n in TX_HEADER
                   if n.endswith("Amount") or n.startswith("Payment Amount_")]
TX_TEXT_COLS = ["Order Num / Bill Num", "Terminal Number", "Serial Number",
                "Sales Type", "Transaction Type", "Payment Type_1", "Payment Type_2", "Payment Type_3",
                "Regular / Other Discount Name", "Online Deals Discount Name",
                "Discount Field 1 Name", "Discount Field 2 Name", "Discount Field 3 Name",
                "Discount Field 4 Name", "Discount Field 5 Name", "Discount Field 6 Name"]
TX_STRICT_ALNUM = {"Order Num / Bill Num", "Terminal Number", "Serial Number"}
AMOUNT_KEYS = (
    "Gross Sales Amount", "Net Sales Amount", "Total Tax", "Other/Local Tax",
    "Total Service Charge", "Total Tip", "Total Discount", "Less Tax Amount",
    "Tax Exempt Sales", "Employee Discount Amount", "Senior Citizen Discount Amount",
    "VIP Discount Amount", "PWD Discount Amount",
    "National Coach / Athlete /  Medal of Valor Discount amount", "SMAC Discount Amount",
    "Online Deals Discount Amount", "Void Amount", "Refund Amount",
)

# ---------------- 正则 ----------------
ALNUM = re.compile(r"^[A-Za-z0-9]*$")
DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DT_RX = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
NUM2_RX = re.compile(r"^-?\d+\.\d{2}$")
QUOTED_FIELD = re.compile(r'"(?:[^"]|"")*"')
QUOTED_LINE = re.compile(r'^"(?:[^"]|"")*"(?:,"(?:[^"]|"")*")*$')


# ---------------- 基础函数 ----------------
def money(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def R(x) -> float:
    """四舍五入到分(ROUND_HALF_UP,避免 Python 银行家舍入)。"""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def q(v: str) -> str:
    """CSV 字段引号包裹(内嵌引号转义为两个)。"""
    return '"' + v.replace('"', '""') + '"'


def load_csv(path: Path):
    """普通 CSV 读取(generator/recompute 读结构良好的样例用)。"""
    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))


# ---------------- 支付归类(兼容样例代码与新命名两套体系) ----------------
def classify_tender(raw: str):
    n = raw.upper()
    if n in ("CSH", "CASH"):
        return "cash"
    if n in ("GIFTCHEQUE", "GIFT_CHECK", "GIFTCARD", "GIFT_CARD", "GC"):
        return "gc"
    if n.startswith("DEBIT_CARD:") or n.startswith("DC"):
        return "debit"
    if n.startswith("CREDIT_CARD:") or n.startswith("CC"):
        brand = n.split(":")[-1]
        if "MASTER" in brand:
            return "mc"
        if "VISA" in brand:
            return "visa"
        if "AMEX" in brand or "AMERICAN" in brand:
            return "amex"
        if "DINER" in brand:
            return "diners"
        if "JCB" in brand:
            return "jcb"
        return "othercc"
    if n in ("GCASH", "PAYMAYA", "MAYA", "GRABPAY"):
        return "ewallet"
    if n.startswith("MALLPAY") or n in ("SMAC",):
        return "other"
    return None


TENDER_COL = {
    "cash": "Total Cash Sales Amount",
    "gc": "Total Gift Cheque / Gift Card Sales Amount",
    "debit": "Total Debit Card Sales Amount",
    "ewallet": "Total E-wallet / Online Sales Amount",
    "other": "Total Other Tender Sales Amount",
    "mc": "Total Mastercard Sales Amount",
    "visa": "Total Visa Sales Amount",
    "amex": "Total American Express Sales Amount",
    "diners": "Total Diners Sales Amount",
    "jcb": "Total JCB Sales Amount",
    "othercc": "Total Other Credit Card Sales Amount",
}


# ---------------- 严格 CSV 解析(validator 用) ----------------
def parse_csv_strict(path: Path, findings, header_quoted: bool):
    """严格解析:数据行每个字段必须双引号包裹;表头按 header_quoted 决定。

    findings 只需提供 add(rule, file, line, detail=...) 鸭子接口。
    返回 (header, [(行号, 字段列表)])。
    """
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        findings.add("F02", path.name, detail="文件含 UTF-8 BOM(已认证样例无 BOM)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        findings.add("F02", path.name, detail=f"非 UTF-8 编码: {e}")
        text = raw.decode("utf-8", errors="replace")

    n_crlf = raw.count(b"\r\n")
    n_lf = raw.count(b"\n")
    if n_crlf != 0 and n_crlf != n_lf:
        findings.add("F07", path.name, detail=f"CRLF/LF 混用(CRLF={n_crlf}, LF={n_lf - n_crlf})")

    def unquote(field: str) -> str:
        return field[1:-1].replace('""', '"')

    header, rows = [], []
    for idx, line in enumerate(text.splitlines(), start=1):
        if line.strip() == "":
            if idx > 1:
                findings.add("F05", path.name, line=idx, detail="空行")
            continue
        if header and QUOTED_LINE.match(line):
            fields = [unquote(m.group(0)) for m in QUOTED_FIELD.finditer(line)]
        elif header:
            findings.add("F04", path.name, line=idx, detail="数据行存在未用双引号包裹的字段")
            fields = next(csv.reader(io.StringIO(line)))
        elif QUOTED_LINE.match(line):                # 表头带引号
            if not header_quoted:                    # sample 基线明细表头不应带引号
                findings.add("F04", path.name, line=idx, detail="该基线明细表头不应带引号")
            fields = [unquote(m.group(0)) for m in QUOTED_FIELD.finditer(line)]
        else:                                        # 表头不带引号
            fields = line.split(",")
        if not header:
            header = fields
        else:
            rows.append((idx, fields))
    return header, rows
