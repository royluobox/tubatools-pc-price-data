# 国内购物平台免费接口：申请与配置

## 第一优先：淘宝联盟（淘宝、天猫）

官方文档：[淘宝客-推广者-物料搜索](https://developer.alibaba.com/docs/api.htm?apiId=35896)。该接口标为「开放平台免费 API」「不需要授权」，这里不需要的通常是**额外的用户 OAuth 授权**；仍须有开发者应用 AppKey/Secret 与推广位，并确认账号可调用。

1. 到 [淘宝开放平台](https://open.taobao.com/) 和 [淘宝联盟](https://pub.alimama.com/) 注册登录，完成所要求的开发者和推广者资质流程。
2. 创建合规用途的应用，核对方法 taobao.tbk.dg.material.optional 的访问权限。
3. 取得应用 AppKey、AppSecret；创建推广位，取 adzone_id（官方文档为 mm_xxx_xxx_12345678 最后一段）。
4. 在本仓库 Settings → Secrets and variables → Actions → New repository secret 添加：
   - TBK_APP_KEY：应用 AppKey；
   - TBK_APP_SECRET：应用 AppSecret；
   - TBK_ADZONE_ID：推广位数字 ID。
5. 确认 API 配额、商品公开展示、缓存和转分发政策；确认适用后手动运行 Actions → Update price feed。
6. 查看 Actions 日志中的匹配数量和生成的 market.json；如 SKU 显示误匹配，在 config/market-targets.json 收紧规则。

**不要把密钥发送到聊天、Issue、PR 或提交记录。** API 失败仅输出异常类别，避免泄露请求签名和参数。

## 后续平台接入

| 来源 | 官方入口 | 状态 |
| --- | --- | --- |
| 京东联盟 | [union.jd.com](https://union.jd.com/) | 待账号/接口权限与响应契约确认后开发 |
| 多多进宝 | [jinbao.pinduoduo.com](https://jinbao.pinduoduo.com/) | 待确认商品搜索权限与报价展示范围 |
| 苏宁开放平台 | [open.suning.com](https://open.suning.com/) | 待申请接口与签名密钥 |

不使用来源不明的付费转发接口、不绕过反爬机制，也不保证所有平台永久免费。每家平台需独立限制配额、记录采样口径和时效，再写入统一 market.json。

## 易混淆的问题

- VRAMGlass 免费额度只覆盖二手市场统计，不等于国内购物平台 API 额度。
- 淘宝联盟的 zk_final_price 是导购物料价字段，**不保证与实际订单结算价一致**。插件会标注为公开促销标价，不称为成交价。
