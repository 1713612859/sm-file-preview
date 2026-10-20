# SM SIA — 最小投影 JSON 规格（POS 端瘦身方案）

> 目标：POS（APOS）在事件时只上传 CSV/收据生成**实际消费**的字段，砍掉全部中间产物表
> 实测依据：最大单 59KB，其中 88% 是三张不消费的中间表（allocation/gov_person/item_rel）

## 一、体积分析（当前最大单拆解）

| 表 | 行数 | 大小 | 占比 | 消费 |
|---|---|---|---|---|
| `ppos_sales_order_payment_allocation` | 32 | 22.7KB | **38%** | ❌ |
| `ppos_gov_person_item_rel` | 40 | 27.0KB | **45%** | ❌ |
| `ppos_sales_order_gov_person` | 5 | 3.5KB | 5% | ❌ |
| `ppos_sales_order_item` | 8 | 8.5KB | 14% | ✅ |
| `ppos_sales_order` | 1 | 2.5KB | 4% | ✅ |
| `ppos_sales_order_payment` | 1 | 0.5KB | 1% | ✅ |

**砍掉三张不消费表即省 88%**（59KB → 11.5KB），1MB 大单同理（预计 → ~120KB）。

## 二、最小投影 JSON 结构

### SALE 事件（正常销售）

```json
{
  "osv": 1,
  "eventKind": "SALE",
  "orderId": 146,
  "orderNo": "0000000000000146",
  "o": {
    "t": 2,                        // orderType(1=堂食/2=打包/…7档)
    "ts": "2026-10-20T13:29:11",   // orderTime(ISO)
    "g": 1950,                     // grossSales(商品含税额,不含服务费)
    "gt": 1566.11,                 // grandTotal(顾客应付)
    "v": 88.39,                    // vatAmount
    "te": 1036.61,                 // vatExemptSales
    "lv": 176.78,                  // lessVatAmount
    "av": 88.39,                   // addVatAmount
    "sc": 0,                       // scDiscountAmount
    "pw": 59.1,                    // pwdDiscountAmount
    "na": 59.1,                    // naacDiscountAmount
    "mv": 59.1,                    // movDiscountAmount
    "sp": 0,                       // spDiscountAmount
    "dp": 0,                       // diplomatDiscountAmount
    "sv": 0,                       // serviceCharge
    "md": 0,                       // manualDiscount(金额)
    "mt": null,                    // manualDiscountType("percent"/"amount")
    "mc": null,                    // manualDiscountCategory(VIP/SMAC/EMP/ONLDEAL/REGULAR)
    "p": 6,                        // totalPersons
    "s": 2,                        // scCount
    "w": 1,                        // pwdCount
    // ── 收据票面(synthExtra 消费) ──
    "cn": "SM TEST MALL TRADING CORP.",  // companyLegalName
    "ca": "Unit 101, ...",               // taxAddress
    "ct": "123-456-789-00001",           // tinNumber
    "mn": "MIN 123456789",              // minNumber
    "pn": "PTU 123456798",              // ptuNumber
    "tn": "2",                           // terminalNo
    "sn": "SN 123465798",               // serialNumber
    "ch": "1001",                        // cashierName
    "pb": "0000000000000165",           // preBillNo(Billing#)
    "tb": "A05",                         // tableNo
    "pk": "0000000000001066",           // pickupNo
    "tt": 5000,                          // totalTendered
    "cg": 709.99                         // changeAmount
  },
  "i": [                             // items(每行 8 字段)
    { "s": "S0000001", "n": "SM Prod A", "q": 2, "u": 150, "o": 150, "rn": 267.86, "rt": 300, "g": "SC", "sv": null }
    // s=skuCode, n=productName, q=quantity, u=unitPrice, o=originalPrice,
    // rn=rowNet, rt=rowTotal, g=govDiscountType, sv=行级serviceCharge(null=无)
  ],
  "p": [                             // payments(每行 3-4 字段)
    { "m": "CASH", "a": 4290.01, "c": null, "e": null }
    // m=paymentMethod, a=amount, c=cardType, e=ewalletType
  ]
}
```

### VOID 事件（整单作废）

同 SALE 结构，额外：
```json
{
  "eventKind": "VOID",
  "o": { ..., "vn": "0000000000000001" }  // voidOrderNo(自己序号)
}
```

### REFUND 事件（全额退）

同 SALE 结构，额外：
```json
{
  "eventKind": "REFUND",
  "o": { ..., "rn": "0000000000000001" }  // returnOrderNo(自己序号)
}
```

### REFUND 事件（部分退，refundType=PARTIAL）

同上 + 追加 `r`（refund 头）和 `ri`（refund_item 行）：
```json
{
  "r": {                              // refund 头(9 字段)
    "rt": "PARTIAL",                  // refundType
    "rm": "ORIGINAL",                 // refundMethod
    "ra": 165,                        // refundAmount
    "g": 210,                         // grossSales(退货行商品含税)
    "lv": 22.5,                       // lessVatAmount
    "av": 0,                          // addVatAmount
    "gd": 37.5,                       // govDiscountAmountNoTax
    "sv": 15,                         // serviceCharge
    "te": 187.5                       // vatExemptSales
  },
  "ri": [                             // refund_item(退货行子集,每行 8 字段)
    { "s": "S0000058", "n": "Baboy Lechon", "q": 1, "u": 150, "o": 210, "sv": 15, "v": 0, "g": "SC", "gd": 37.5, "si": 1 }
    // si=salesOrderItemId(回链原单行取 skuCode 用)
  ]
}
```

## 三、体积估算

| 场景 | 当前 | 投影后 | 节省 |
|---|---|---|---|
| 3 件商品普通单 | ~7KB | ~1.5KB | 79% |
| 8 件商品+5 人政府折扣 | 59KB | ~4KB | 93% |
| 20 件大单（用户报 >1MB 的场景） | ~1MB+ | ~10KB | 99% |

## 四、sm-user 侧适配

改 `smJsonMap.parseOrderDoc` 识别投影格式（顶层有 `o`/`i`/`p` 短键即走投影路径，无则走原 orderTables 路径），两代格式并存平滑迁移：

```typescript
function parseOrderDoc(row: SmOrderEventRow): ParsedOrder | null {
  // 投影格式(2026-10-20 瘦身批):顶层 o/i/p/r/ri 短键
  const root = asRecord(JSON.parse(row.orderJson))
  if (root?.o && root?.i !== undefined) return parseProjection(root, row)
  // 原始 orderTables 格式(兼容存量)
  return parseOrderTables(root, row)
}
```

## 五、APOS 侧改造点

`SmOrderRowBuilder` / `BatchSyncService` 在事件产出时只序列化上述字段（~50 个），跳过 allocation/gov_person/item_rel 的查询与序列化——既省上行带宽，也省云端存储与 sm-user 拉取量。
