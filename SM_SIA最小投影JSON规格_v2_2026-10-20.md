# SM SIA — 最小投影 JSON 规格 v2

> 目标：APOS 在事件产出时只序列化 sm-user CSV/收据生成实际消费的字段，**保持原字段命名与层级**（不做缩写映射），砍掉三张中间产物表
> 实测依据：最大单 59KB，88% 是不消费的 allocation/gov_person/item_rel；1MB 单同比例

## 一、设计原则

1. **字段名与 APOS 数据库字段完全一致**（camelCase，与 ppos_sales_order 表列名对齐）——零映射成本、零歧义
2. **保持 orderTables 层级**——sm-user 解析器只做「按表取子集」，不做结构变换
3. **销售单变种全覆盖**——SALE/VOID/REFUND(FULL)/REFUND(PARTIAL) 四形态在同一结构内，通过 eventKind + 补充表区分
4. **政府折扣与常规折扣可并存**——不同折扣族互斥的假设已撤回，投影同时保留两族字段

## 二、投影 JSON 结构

### 顶层（与现有一致）

```json
{
  "osv": 2,
  "eventKind": "SALE | VOID | REFUND",
  "orderId": 146,
  "refundNo": null,
  "orderTables": { ... }   // 仅含下述三(+二)张精简表
}
```

### 1. `orderTables.ppos_sales_order`（1 行，精简到 44 个消费字段）

**金额/税（12 字段）：**
| 字段 | 类型 | 说明 |
|---|---|---|
| `grossSales` | number | 商品含税额（不含服务费） |
| `grandTotal` | number | 顾客应付 |
| `vatAmount` | number | 增值税 |
| `vatExemptSales` | number | 免税销售额 |
| `lessVatAmount` | number | 减税额 |
| `addVatAmount` | number | 加回税额 |
| `serviceCharge` | number | 服务费 |
| `variableSales` | number | 可变销售额（收据票面用） |
| `subtotalAmount` | number | 小计 |
| `zeroRatedSales` | number | 零税率销售 |
| `taxType` | string | 税率类型（"0.12"） |
| `serviceChargeRate` | number | 服务费率 |

**折扣族（12 字段）：**
| 字段 | 类型 | 说明 |
|---|---|---|
| `scDiscountAmount` | number | SC 折扣 |
| `pwdDiscountAmount` | number | PWD 折扣 |
| `naacDiscountAmount` | number | NAAC 折扣 |
| `movDiscountAmount` | number | MOV 折扣 |
| `spDiscountAmount` | number | SP 折扣 |
| `diplomatDiscountAmount` | number | 外交官折扣 |
| `manualDiscount` | number | 手动折扣金额 |
| `manualDiscountType` | string | 折扣方式（"percent"/"amount"） |
| `manualDiscountCategory` | string | 折扣类别（VIP/SMAC/EMP/ONLDEAL/REGULAR） |
| `promoDiscount` | number | 促销折扣（预留） |
| `memberDiscount` | number | 会员折扣（预留） |
| `couponDiscount` | number | 券折扣（预留） |

**客数（5 字段）：**
| 字段 | 类型 |
|---|---|
| `totalPersons` | number |
| `scCount` | number |
| `pwdCount` | number |
| `naacCount` | number |
| `movCount` | number |

**标识/时间（8 字段）：**
| 字段 | 类型 | 说明 |
|---|---|---|
| `orderNo` | string | 订单号（16 位） |
| `terminalNo` | string | 终端号 |
| `serialNumber` | string | 序列号 |
| `orderType` | number | 订单类型（1-7 枚举） |
| `orderTime` | string | 下单时间 ISO |
| `paidAt` | string | 支付时间 ISO |
| `voidOrderNo` | string\|null | 作废序号（VOID 事件） |
| `returnOrderNo` | string\|null | 退货序号（REFUND 事件） |

**收据票面（7 字段）：**
| 字段 | 类型 | 说明 |
|---|---|---|
| `cashierName` | string | 收银员 |
| `preBillNo` | string | 预付单号（Billing#） |
| `tableNo` | string\|null | 桌号 |
| `pickupNo` | string\|null | 取餐号 |
| `totalTendered` | number | 实收 |
| `changeAmount` | number | 找零 |
| `siNumber` | string | SI 号 |

**门店票头（7 字段，首次上报后可配置缓存）：**
| 字段 | 类型 |
|---|---|
| `companyLegalName` | string |
| `taxAddress` | string |
| `tinNumber` | string |
| `minNumber` | string |
| `ptuNumber` | string |
| `storeName` | string |
| `businessType` | string\|null |

### 2. `orderTables.ppos_sales_order_item`（N 行，每行精简到 9 字段）

| 字段 | 类型 | 说明 |
|---|---|---|
| `skuCode` | string | SKU 编码 |
| `productName` | string | 商品名 |
| `quantity` | number | 数量 |
| `unitPrice` | number | 成交单价 |
| `originalPrice` | number | 原价 |
| `rowNet` | number | 行净额 |
| `rowTotal` | number | 行含税合计 |
| `govDiscountType` | string\|null | 政府折扣类型（SC/PWD/MOV/DIPLOMATIC） |
| `serviceCharge` | number\|null | 行级服务费（有=加法口径，null=均匀因子） |

### 3. `orderTables.ppos_sales_order_payment`（N 行，每行 4 字段）

| 字段 | 类型 | 说明 |
|---|---|---|
| `paymentMethod` | string | 支付方式（POS 原始码） |
| `amount` | number | 金额 |
| `cardType` | string\|null | 卡类型（品牌段） |
| `ewalletType` | string\|null | 钱包类型 |

### 4. `orderTables.ppos_sales_order_refund`（仅 REFUND PARTIAL，1 行，9 字段）

| 字段 | 类型 |
|---|---|
| `refundType` | string |
| `refundMethod` | string |
| `refundAmount` | number |
| `grossSales` | number |
| `lessVatAmount` | number |
| `addVatAmount` | number |
| `govDiscountAmountNoTax` | number |
| `serviceCharge` | number |
| `vatExemptSales` | number |

### 5. `orderTables.ppos_sales_order_refund_item`（仅 REFUND PARTIAL，退货行子集，10 字段/行）

| 字段 | 类型 | 说明 |
|---|---|---|
| `skuCode` | string\|null | SKU（可能为 null，回链用 salesOrderItemId） |
| `productName` | string | 品名 |
| `quantity` | number | 退货数量 |
| `unitPrice` | number | 成交单价 |
| `originalPrice` | number | 原价 |
| `serviceCharge` | number | 行级服务费 |
| `vatAmount` | number | 行增值税 |
| `govDiscountType` | string | 政府折扣类型 |
| `govDiscountAmountNoTax` | number | 政府折扣不含税 |
| `salesOrderItemId` | number | 原单行 ID（回链取 skuCode） |

## 三、不上传的表（砍掉）

| 表 | 原因 |
|---|---|
| `ppos_sales_order_payment_allocation` | 金额走订单头残差，不需要行级分摊 |
| `ppos_sales_order_gov_person` | 折扣金额已汇总进头部各分列字段 |
| `ppos_gov_person_item_rel` | 同上 |

## 四、销售单变种覆盖

| 变种 | eventKind | 投影内容 | 特殊处理 |
|---|---|---|---|
| **正常销售** | SALE | o/i/p 三表 | — |
| **整单作废** | VOID | o(含 voidOrderNo)/i/p | 金额镜像原单取负 |
| **全额退货** | REFUND | o(含 returnOrderNo)/i/p | 金额镜像原单取负，支付腿优先取负单自身 |
| **部分退货** | REFUND + r/ri | o/i/p + refund + refund_item | T 行从 refund 头金额分解，D 行从 refund_item 子集 |
| **政府折扣单** | SALE | 同正常（o 含折扣族字段） | NAAC+MOV 累加落 #29 列 |
| **常规折扣单** | SALE | 同正常（o 含 manual 族字段） | 按 manualDiscountCategory 落列 |
| **折扣并存单** | SALE | 同正常（两族字段同时非零） | 残差分列自动处理 |
| **服务费单** | SALE | 同正常（o 含 serviceCharge/Rate，i 含行级 svc） | Gross=商品+服务费 |
| **外卖/快递** | SALE | 同正常（orderType=3-7） | Transaction Type 按枚举输出 |
| **零税率** | SALE | 同正常（o 含 zeroRatedSales） | 预留字段 |

## 五、体积估算

| 场景 | 当前 orderJson | 投影后 | 节省 |
|---|---|---|---|
| 3 件普通单 | ~7KB | **~2KB** | 71% |
| 8 件+5 人政府折扣 | 59KB | **~5KB** | 92% |
| 20 件大单（>1MB 场景） | ~1MB | **~12KB** | 99% |

## 六、sm-user 侧适配

零改动——投影格式**保持 orderTables 层级与字段名**，现有 `parseOrderDoc` 直接解析（缺失的表自然跳过）。`osv: 2` 版本号供上游标记投影格式，便于追溯。

## 七、APOS 侧改造

`BatchSyncService` 事件序列化时，`orderTables` 只查/只拼上述 3(+2) 张精简表，字段做白名单过滤（按本规格的字段清单 SELECT 而非 SELECT *）。三张中间产物表不再查询。
