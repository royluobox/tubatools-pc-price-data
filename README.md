# 图吧工具箱 CE · 价格数据仓库

本仓库为 [价格走势插件](https://github.com/royluobox/tubatools-pc-price-trend) 定时生成**可溯源**的公开快照。三条价格口径相互独立：

| 数据文件 | 内容 | 来源 | 是否真实电商 SKU 报价 |
| --- | --- | --- | --- |
| [latest.json](https://royluobox.github.io/tubatools-pc-price-data/data/latest.json) | 9 款显卡的闲鱼挂牌统计和历史 | VRAMGlass 免费 API | 否，挂单 ≠ 成交 |
| [catalog.json](https://royluobox.github.io/tubatools-pc-price-data/data/catalog.json) | 12 类电脑配件、约 1,700 个型号的参考价 | ZOL 产品/趋势页 | 否，参考价 ≠ 到手价 |
| market.json（配置与许可后生成） | 带平台、SKU、价格类型、商品页、时间的参考标价 | 什么值得买海纳 API（优先），蚂蚁星球与淘宝联盟备用 | 第三方 API 原价参考，绝非结算价 |

## 自动更新

- GitHub Actions 每 8 小时检查 VRAMGlass 和 ZOL，原有免费额度和工作流保持。
- 在有海纳或其他有效 API Key，**且确认可公开再分发**后，优先查询首批 4 个严格型号，生成 [market.json](https://royluobox.github.io/tubatools-pc-price-data/data/market.json)。后续可在验证免费配额后扩大至 12 个或更多。
- 保留 **Smoke test HaoJingKe API (no publication)** 手动诊断工作流：任选已审阅的 CPU/显卡型号，最多分别请求京东、拼多多各一次；没有自动触发，不写入真实快照，也不消耗 VRAMGlass 额度。
- **无凭据时安全跳过**新来源，不生成虚假报价、不覆盖旧 market.json。源不可用时保留上次成功结果，由插件将过期资料单独标记。
- 每个型号仅接受严格型号匹配、排除配件和错误显存版本的真实 SKU；最多保存 12 条，保留时间、类型及官方商品链接。
- 不推演成交价、优惠券或历史缺失日期，也不把 ZOL、闲鱼、淘宝报价计算成同一个中位价。

### 免费额度策略

VRAMGlass 免费额度继续用于 9 款显卡，历史最多每 20 小时请求一次。第三方电商 API 仅在**明确启用发布**后查询。海纳初始至多 **4 型号 × 3 次/日 = 12 次/日**，好京客备用模式最多 24 次/日；真实额度未知，按实际授权调整。失败时不无限重试，更不会绕过购物网站限制。原淘宝联盟官方采集器仅作合法授权的备用模式。

## 获取 API 权限

参见 [申请和配置指南](docs/api-onboarding.md)。当前首选是在什么值得买海纳开通商品检索等能力，将 `HAINA_API_KEY` 保存为 Actions Secret；蚂蚁星球 `HJK_API_KEY` 保留备用。无需先为插件申请 Windows 代码签名证书。凭据只填在**本数据仓库 GitHub Actions Secrets**，绝不要写进代码、Issue、聊天、插件包或公开 JSON。必须在明确得到再分发许可后才能启用 `MARKET_PUBLISH_ENABLED=true`。

## market.json 数据约定

```json
{
  "modelKey": "vga|RTX5070",
  "name": "RTX 5070",
  "slug": "vga",
  "price": 3999,
  "offers": [{
    "source": "HaoJingKe third-party API",
    "platform": "京东",
    "skuId": "112233",
    "title": "示例 RTX 5070 显卡",
    "url": "https://item.jd.com/112233.html",
    "price": 3999,
    "priceType": "original-reference",
    "observedAt": "2026-11-20T06:00:00Z"
  }],
  "history": []
}
```

**这只是结构样例，不是实际采集到的报价。** 这里的价格是第三方接口标注的「原价」，不是当前可购买到的到手价。型号白名单和正则规则在 [market-targets.json](config/market-targets.json)。

## 开发、测试与隐私

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts tests
```

通常的 CI 只运行离线报价契约测试与 ZOL 编译，**不会花费 API 额度**；专门标记的测试提交或手动运行冒烟工作流除外。测试价不进入生产文件。公开快照不包含 API Key、签名或用户数据。

**2026-11-20 授权后联机复核：** 京东 `goodslist` 在 RTX 5070、9800X3D、DDR5 三组关键词及两个已知商品 ID 查询中均返回 `status_code=200`，但实际 `total=0`、`rows=0`；`goodsdetail` 对两个商品 ID 也未返回可用商品对象。授权成功并不等于有硬件价格数据。拼多多先前返回过商品行，但 RTX 5070 **0 条通过精确型号/SKU 校验**。因此当前**没有可发布的京东/拼多多目标硬件报价**，市场快照发布继续关闭。参见 [验证记录](docs/api-onboarding.md)和 [隔离诊断工作流](https://github.com/royluobox/tubatools-pc-price-data/actions/runs/44699627726)。

**2026-11-20 海纳联机结果：** 独立只读测试证明 RTX 5070、RTX 5060 Ti 16GB 和 9800X3D
有匹配且带页面标价的商品：RTX 5070 为 17/20 条；RTX 5060 Ti 16GB 为 7/10 条；
9800X3D 用短词为 7/7 条、中文词为 9/10 条。实际响应**没有文档示例中的 180 天历史价格字段**。另外已用正式采集器验证 RTX 5070 的 **13 个官方商品链接/标价记录**通过 URL、金额和型号校验（[端到端测试 #3](https://github.com/royluobox/tubatools-pc-price-data/actions/runs/44711978725)），商品记录不等于原始商家 SKU。
接入代码只支持从授权启用后逐日记录真实样本，不补造过去日期。当前仍需确认 URL/商品记录的有效性、
免费额度和公开展示许可；`MARKET_PUBLISH_ENABLED` **继续关闭**。
详见 [实测与授权条件](docs/api-onboarding.md)和
[隔离测试 #1](https://github.com/royluobox/tubatools-pc-price-data/actions/runs/44710975219)、
[隔离测试 #2](https://github.com/royluobox/tubatools-pc-price-data/actions/runs/44711196906)。

本仓库与 VRAMGlass、ZOL、蚂蚁星球、淘宝、京东、拼多多无隶属关系。平台报价受地区、库存、会员、优惠券、运费和商品版本等影响，仅供研究参考。如来源要求停止展示，请提交 Issue。
