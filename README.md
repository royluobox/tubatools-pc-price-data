# 图吧工具箱 CE · 价格数据仓库

本仓库为 [价格走势插件](https://github.com/royluobox/tubatools-pc-price-trend) 定时生成**可溯源**的公开快照。三条价格口径相互独立：

| 数据文件 | 内容 | 来源 | 是否真实电商 SKU 报价 |
| --- | --- | --- | --- |
| [latest.json](https://royluobox.github.io/tubatools-pc-price-data/data/latest.json) | 9 款显卡的闲鱼挂牌统计和历史 | VRAMGlass 免费 API | 否，挂单 ≠ 成交 |
| [catalog.json](https://royluobox.github.io/tubatools-pc-price-data/data/catalog.json) | 12 类电脑配件、约 1,700 个型号的参考价 | ZOL 产品/趋势页 | 否，参考价 ≠ 到手价 |
| market.json（配置与许可后生成） | 带平台、SKU、价格类型、商品页、时间的参考标价 | 蚂蚁星球（原好京客）京东/拼多多 API；淘宝联盟可选 | 第三方 API 原价参考，绝非结算价 |

## 自动更新

- GitHub Actions 每 8 小时检查 VRAMGlass 和 ZOL，原有免费额度和工作流保持。
- 在有第三方蚂蚁星球 API Key，**且确认可公开再分发**后，查询首批 4 个严格型号、2 个平台，生成 [market.json](https://royluobox.github.io/tubatools-pc-price-data/data/market.json)。后续可在验证免费配额后扩大至 12 个或更多。
- 新增 **Smoke test HaoJingKe API (no publication)** 手动测试工作流：最多 2 次京东查询，不写入真实快照。此工作流与 VRAMGlass 用量无关。
- **无凭据时安全跳过**新来源，不生成虚假报价、不覆盖旧 market.json。源不可用时保留上次成功结果，由插件将过期资料单独标记。
- 每个型号仅接受严格型号匹配、排除配件和错误显存版本的真实 SKU；最多保存 12 条，保留时间、类型及官方商品链接。
- 不推演成交价、优惠券或历史缺失日期，也不把 ZOL、闲鱼、淘宝报价计算成同一个中位价。

### 免费额度策略

VRAMGlass 免费额度继续用于 9 款显卡，历史最多每 20 小时请求一次。第三方电商 API 仅在**明确启用发布**后查询，初始上限为 **4 个型号 × 2 平台 / 8 小时（最多 24 次/日）**；真实额度未知，按实际授权调整。失败时不无限重试，更不会绕过购物网站限制。原淘宝联盟官方采集器仅作合法授权的备用模式。

## 获取 API 权限

参见 [申请和配置指南](docs/api-onboarding.md)。当前首选是在蚂蚁星球申请单个 `HJK_API_KEY`，无需先为插件申请 Windows 代码签名证书。凭据只填在**本数据仓库 GitHub Actions Secrets**，绝不要写进代码、Issue、聊天、插件包或公开 JSON。必须在明确得到再分发许可后才能启用 `MARKET_PUBLISH_ENABLED=true`。

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

CI 只运行离线报价契约测试与 ZOL 编译，**不会花费 API 额度**。主分支定时流程才读取 Secrets 并采集；测试价不进入生产文件。公开快照不包含 API Key、签名或用户数据。

本仓库与 VRAMGlass、ZOL、蚂蚁星球、淘宝、京东、拼多多无隶属关系。平台报价受地区、库存、会员、优惠券、运费和商品版本等影响，仅供研究参考。如来源要求停止展示，请提交 Issue。
