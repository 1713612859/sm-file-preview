# SM SIA — 最小投影 JSON 规格 v3

> 设计原则：**CSV + 收据（ORs/ZReads）双消费面完整覆盖**，不只是 CSV
> 字段名与 APOS 数据库列名完全一致，保持 orderTables 层级，sm-user 零改动

## 一、保留表清单（6 张精简，2 张砍掉）

| 表 | 保留/砍 | 消费方 | 说明 |
|---|---|---|---|
| `ppos_sales_order` | ✅ 精简 50 字段 | CSV + 收据 | 订单头 |
| `ppos_sales_order_item` | ✅ 精简 9 字段/行 | CSV + 收据 | 商品行 |
| `ppos_sales_order_payment` | ✅ 精简 4 字段/行 | CSV + 收据 | 支付腿 |
| **`ppos_sales_order_gov_person`** | ✅ 精简 12 字段/行 | **收据票面** | 政府折扣人（签名区/折扣分组） |
| `ppos_sales_order_refund` | ✅ 精简 15 字段 | CSV + 收据 | 退货头（部分退金额分解 + 票面 Memo） |
| `ppos_sales_order_refund_item` | ✅ 精简 12 字段/行 | CSV + 收据 | 退货行 |
| ~~`ppos_sales_order_payment_allocation`~~ | ❌ 砍 | 无 | 金额走头部残差 |
| ~~`ppos_gov_person_item_rel`~~ | ❌ 砍 | 收据分组可从 gov_person 推导 | 按 rate 分组在 sm-user 侧聚合 |

## 二、各表字段清单

### 1. `ppos_sales_order`（1 行，50 字段）

**金额/税（14 字段）：**

| 字段 | 类型 | CSV 列 | 收据区域 |
|---|---|---|---|
| `grossSales` | number | #14 组成 | 商品区 |
| `grandTotal` | number | #20 残差 | Amount Due |
| `vatAmount` | number | #16 | VAT Amount |
| `vatExemptSales` | number | #22 | VAT Exempt Sales |
| `lessVatAmount` | number | #21 组成 | LESS 12% VAT |
| `addVatAmount` | number | #21 组成 | Add 12% VAT |
| `serviceCharge` | number | #18 | Service Charge |
| `serviceChargeRate` | number | — | 服务费标签 |
| `variableSales` | number | — | VATable Sales（票面） |
| `subtotalAmount` | number | — | — |
| `zeroRatedSales` | number | — | Zero Rated Sales |
| `taxType` | string | — | 票头 |
| `vatableSales` | number | — | 预留 |
| `govDiscountAmount` | number | — | 折扣分组参考 |

**折扣族 — 政府（7 字段）：**

| 字段 | 类型 | CSV 列 |
|---|---|---|
| `scDiscountAmount` | number | #26 Senior |
| `pwdDiscountAmount` | number | #28 PWD |
| `naacDiscountAmount` | number | #29 组成 |
| `movDiscountAmount` | number | #29 组成 |
| `spDiscountAmount` | number | #39 Field1 |
| `diplomatDiscountAmount` | number | #40 Field2 |
| `govDiscountAmountNoTax` | number | — （残差对拍用） |

**折扣族 — 常规（5 字段）：**

| 字段 | 类型 | CSV 列 |
|---|---|---|
| `manualDiscount` | number | 残差落列 |
| `manualDiscountType` | string | #23 名称 |
| `manualDiscountCategory` | string | 落列位置 |
| `promoDiscount` | number | 预留 |
| `memberDiscount` | number | 预留 |

**客数（5 字段）：** `totalPersons` `scCount` `pwdCount` `naacCount` `movCount`

**标识/时间（10 字段）：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `orderNo` | string | 订单号 |
| `terminalNo` | string | 终端号 |
| `serialNumber` | string | 序列号 |
| `orderType` | number | 1-7 枚举 |
| `orderTime` | string | 下单 ISO |
| `paidAt` | string | 支付 ISO |
| `voidOrderNo` | string\|null | 作废序号 |
| `returnOrderNo` | string\|null | 退货序号 |
| `siNumber` | string | SI 号（收据 SI# 行） |
| `discountMode` | string | 折扣模式（WHOLE_ORDER_GOV 等，票面分组） |

**收据票面 — 人员/门店（9 字段）：**

| 字段 | 类型 | 收据区域 |
|---|---|---|
| `cashierName` | string | Cashier 行 |
| `preBillNo` | string | Billing# 行 |
| `tableNo` | string\|null | Table# 行 |
| `pickupNo` | string\|null | 取餐号（票尾 2-NNNN） |
| `totalTendered` | number | CASH 行（实收） |
| `changeAmount` | number | CHANGE 行（找零） |
| `companyLegalName` | string | 票头店名 |
| `taxAddress` + `tinNumber` + `minNumber` + `ptuNumber` | string | 票头地址/TIN/MIN/PTU |

**收据票面 — 作废/退货原因（4 字段，v2 漏掉）：**

| 字段 | 类型 | 收据区域 |
|---|---|---|
| `voidReason` | string\|null | VOID 票尾 `Memo: {原因}` |
| `voidedBy` | number\|null | 作废操作员 |
| `notes` | string | 整单 Memo（票面模块 12.5） |
| `customerName` + `customerTin` + `customerAddress` | string\|null | 非政府单顾客块 |

### 2. `ppos_sales_order_item`（N 行，每行 9 字段）

| 字段 | 类型 | CSV | 收据 |
|---|---|---|---|
| `skuCode` | string | #2 Item ID | 商品名行 |
| `productName` | string | #2 Item Name | 商品名行 |
| `quantity` | number | #6 | Qty 列 |
| `unitPrice` | number | #7 组成 | U.Price 列 |
| `originalPrice` | number | #8 | — |
| `rowNet` | number | #7 组成 | Amount 列 |
| `rowTotal` | number | — | — |
| `govDiscountType` | string\|null | #9 | — |
| `serviceCharge` | number\|null | 行级 svc | — |

### 3. `ppos_sales_order_payment`（N 行，每行 4 字段）

| 字段 | 类型 | CSV | 收据 |
|---|---|---|---|
| `paymentMethod` | string | #45-49 | 支付区（品牌名） |
| `amount` | number | #45-49 | 支付区金额 |
| `cardType` | string\|null | 品牌段 | — |
| `ewalletType` | string\|null | 钱包细分 | — |

### 4. `ppos_sales_order_gov_person`（N 行，每行 12 字段）**——收据票面必需**

| 字段 | 类型 | 收据区域 |
|---|---|---|
| `discountType` | string | `{TYPE} NAME:` 行前缀（SC/PWD/NAAC/MOV/DIPLOMATIC） |
| `personName` | string | `{TYPE} NAME:` 值 |
| `personIdNo` | string | `{TYPE} ID#:` 值 |
| `personAddress` | string\|null | `{TYPE} ADDRESS:` 值 |
| `personTin` | string\|null | `{TYPE} TIN:` 值（DIPLOMATIC 无此行） |
| `discountRate` | number | 折扣分组键（按率分组渲染） |
| `discountAmount` | number | 分组折扣额 |
| `lessVatAmount` | number | 分组 LESS VAT 行 |
| `addVatAmount` | number | 分组 Add VAT 行 |
| `totalDiscount` | number | 分组总折扣 |
| `itemIds` | string | 覆盖行（退款回链用） |
| `personCount` | number | 同类型人数 |

**收据票面渲染示意（订单 145 实例）：**
```
SC NAME:           3213        ← personName
SC ADDRESS:                    ← personAddress
SC TIN:            321         ← personTin
SC ID#:            2123        ← personIdNo
SC Signature：_________________← signatureLine('SC')
NAAC NAME:         321
NAAC ADDRESS:
NAAC TIN:          321
NAAC ID#:          3213
NAAC Signature：___
MOV NAME:          321312
MOV ADDRESS:
MOV TIN:           32123123
MOV ID#:           321312
MOV Signature：____
```

### 5. `ppos_sales_order_refund`（仅 REFUND，1 行，15 字段）

| 字段 | 类型 | 消费方 |
|---|---|---|
| `refundType` | string | 部分退检测（PARTIAL） |
| `refundMethod` | string | 支付腿分摊方式（ORIGINAL） |
| `refundAmount` | number | #10 Refund Amount |
| `refundReason` | string | **收据 Memo 行**（RETURN 票尾） |
| `refundTime` | string | 收据 Date&Time |
| `refundedBy` | number | — |
| `refundedByName` | string | — |
| `grossSales` | number | 部分退 #14 |
| `lessVatAmount` | number | 部分退 #21 |
| `addVatAmount` | number | 部分退 #21 |
| `govDiscountAmountNoTax` | number | 部分退 #20 |
| `serviceCharge` | number | 部分退 #18 |
| `vatExemptSales` | number | 部分退 #22 |
| `refundNo` | string | 负单号（REFUND{终端}{refundNo}） |
| `tableNo` | string\|null | 退票据号 |

### 6. `ppos_sales_order_refund_item`（仅 REFUND PARTIAL，退货行子集，12 字段/行）

| 字段 | 类型 | 说明 |
|---|---|---|
| `skuCode` | string\|null | SKU（null 时经 salesOrderItemId 回链） |
| `productName` | string | 品名 |
| `quantity` | number | 退货数量 |
| `unitPrice` | number | 成交单价 |
| `originalPrice` | number | 原价 |
| `serviceCharge` | number | 行级服务费 |
| `vatAmount` | number | 行增值税 |
| `govDiscountType` | string | 政府折扣类型 |
| `govDiscountAmountNoTax` | number | 行政府折扣 |
| `govDiscountRate` | number | 行折扣率 |
| `salesOrderItemId` | number | 原单行 ID（回链） |
| `taxFlag` | string | V/E 税标 |

## 三、砍掉 `ppos_gov_person_item_rel` 的推导逻辑

收据折扣分组（`extra.gov.g`）从 `ppos_sales_order_gov_person` **按 discountRate 聚合**推导：

```typescript
// sm-user smJsonMap 侧（从 gov_person 推导收据分组）
const groups = new Map<number, { lv: number; d: number; av: number }>()
for (const p of govPersons) {
  const rate = p.discountRate
  const g = groups.get(rate) ?? { lv: 0, d: 0, av: 0 }
  g.lv += p.lessVatAmount
  g.d  += p.govDiscountAmountNoTax ?? p.discountAmount
  g.av += p.addVatAmount
  groups.set(rate, g)
}
```

## 四、体积估算

| 场景 | 当前 | 投影后 | 节省 |
|---|---|---|---|
| 3 件普通单（无折扣人） | ~7KB | ~2KB | 71% |
| 8 件 + 5 人政府折扣 | 59KB | **~6KB** | 90% |
| 20 件大单（>1MB 场景） | ~1MB | **~15KB** | 98.5% |

（gov_person 每行约 200B，5 人 1KB，占比小）

## 五、销售单变种全覆盖

| 变种 | eventKind | 携带表 | 票面特殊 |
|---|---|---|---|
| 正常销售 | SALE | so + item + payment | — |
| 政府折扣销售 | SALE | + **gov_person** | 签名区 + 折扣分组三行 |
| 常规折扣销售 | SALE | so（manual 族） | — |
| 折扣并存 | SALE | + gov_person | 签名区 |
| 服务费 | SALE | so（svc 字段）+ item（行级 svc） | 服务费标签 |
| 外卖/快递 | SALE | so（orderType 3-7） | Trx Type 标签 |
| 整单作废 | VOID | so（voidReason）+ item + payment | **VOID 票 + Memo=voidReason** |
| 全额退货 | REFUND | so + item + payment + **refund（refundReason）** | **RETURN 票 + Memo=refundReason** |
| 部分退货 | REFUND | + **refund_item** | RETURN 票（退货行子集） |
