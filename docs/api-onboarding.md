# 国内电商价格 API：免费申请及验证

## 首选：什么值得买「海纳」商品检索（2026-11-20 联机验证）

官方开放平台：[海纳开发者工作台](https://ai.zhidemai.com/haina-platform)。
优先使用 [商品检索 Pro](https://ai.zhidemai.com/haina-platform/product_search_pro)
获取页面标价、平台、店铺和商品链接，用[商品 SKU 信息](https://ai.zhidemai.com/haina-platform/product_sku_info)
辅助型号消歧；[好价检索 Pro](https://ai.zhidemai.com/haina-platform/discount_search_pro)
只用于独立的优惠信息，不与普通页面标价混合计算历史曲线。

- GitHub Actions Secret 名称：`HAINA_API_KEY`。不得复制 Key 到源码、Issue、聊天或日志。
- 离线集成使用 `MARKET_PROVIDER=haina` 或自动选择优先级（有 Haina Key 时优先）。
  同一目标至多一次搜索，不追逐空结果无限重试；CPU 等目标可用经过验证的简短 `hainaQuery`。
- **两轮已成功的 API 冒烟测试：** [首轮](https://github.com/royluobox/tubatools-pc-price-data/actions/runs/44710975219)：
  RTX 5070 商品搜索返回 20 条，17 条精确型号与页面价格字段匹配；
  独立好价搜索 5/5 条命中；9800X3D 商品搜索在较长英文查询下为 0；
  SKU 归一接口返回 3 个相关实体，其 `sku_count` 合计 57（不代表 57 个可购买独立 SKU）。
- [第二轮查询词复核](https://github.com/royluobox/tubatools-pc-price-data/actions/runs/44711196906)：
  9800X3D 简短词 7/7 条精确匹配且有页面价格；中文词 9/10；
  RTX 5060 Ti 16GB 为 7/10；iPhone 16 Plus 对照组 4/4。
  这些是标题/价格字段计数，真正进入插件前还必须通过官方链接、安全 URL、价格范围与重复项校验。
- **历史价格限制：** 官方接口示例列有 `price_info_180_days`，但以上实时返回的 CPU、显卡及对照手机
  均没有该字段。因此不能声称已经取得 180 天历史，也不能人工回填；
  未来若允许保存，`history` 只能从授权启用之日按日采样真实观测点累积，允许空缺日期。
- **公开再分发权尚未确认：** 测试 Key 免费不自动代表长期免费、不代表可以在公开 GitHub Pages
  或图吧工具箱 CE 插件中缓存、再发布历史行情。咨询平台确认长期额度、调用频率、
  具体字段的存储/展示/保留时长与署名要求之前，**保持 `MARKET_PUBLISH_ENABLED` 关闭**。
  独立冒烟工作流只在隔离测试分支使用，绝不保存原始响应或产品价格。

## 首选：蚂蚁星球（原好京客）京东/拼多多搜索

不是京东或拼多多的官方直接 API，而是**第三方导购商品数据接口**。服务方公开标注免费，并提供京东、拼多多关键词搜索和商品详情；不代表任意商品都有覆盖，也不保证免费额度永久不变。

- [京东 API 说明](https://www.haojingke.com/open-api/jd)
- [拼多多 API 说明](https://www.haojingke.com/open-api/pdd)

1. 在服务方网站注册，找到「开放 API」/「申请 API Key」。**不要**将 Key 复制进插件 DLL、仓库源码、聊天、Issue 或 PR。
2. 在**本数据仓库** Settings → Secrets and variables → Actions → New repository secret 创建 `HJK_API_KEY`。
3. 手动运行 Actions → **Smoke test HaoJingKe API (no publication)**。从下拉菜单选择一个已审阅的 CPU/GPU 型号，以及京东、拼多多或两者；**最多发起 2 次查询**，仅显示返回行数和精确匹配数，**不会公开价格、写入 market.json 或消耗 VRAMGlass 额度**。工作流没有定时或代码推送触发器，避免意外消耗免费额度。
4. 检查服务是否支持 HTTPS；服务方文档例子是 HTTP，代码故意只接受 HTTPS。**如 HTTPS 不可用，暂停接入，不要让 API Key 经明文网络传输。**
5. 在正式使用前，向服务方确认：允许把 SKU 标价和对应时间**长期保存、通过 GitHub Pages 公开展示、向第三方图吧工具箱 CE 用户再分发**；明确免费额度、地域和调用频率限制。免费调用 API 不自动授予二次发布商品数据的权利。
6. 只有确认权利后，才将 Actions **Repository variable** `MARKET_PUBLISH_ENABLED` 设为 `true`，再手动运行 Update price feed。未设置时定时任务完全跳过电商 API。

初始每日预算：4 个型号 × 2 平台 × 每 8 小时一次 = **最多 24 次请求/天**，实际成功数可能更低。服务配额未核实，必要时在 workflow 中降低 `HJK_MAX_TARGETS`。

### 字段解释（重要）

| 平台 | 第三方接口字段 | 我们的处理 |
| --- | --- | --- |
| 京东 | `data.data[]`: `goods_id`, `goods_name`, `materiaurl`, `price` | 校验 SKU 和 `item.jd.com` 链接；`price` 标记为原价参考 |
| 京东 | `price_after` | 单独记录条件性券后参考值，不作为历史走势价格 |
| 拼多多 | `goods_id`, `goods_name`, `materiaurl`, `price` | 校验 `goods_id` 在官方链接内一致；`price` 标记为原价参考 |
| 拼多多 | `price_after` | 单独记录条件性券后参考值 |

**原价参考不等于实际支付金额，更不是已成交价。** 不填充没有采集到的历史日期；不把独立平台、二手挂牌和 ZOL 参考价混成一条曲线。

### 2026-11-20 带真实 API Key 的联机验证

- **凭据**：`HJK_API_KEY` 已由 GitHub Actions 成功读取；仅传 HTTPS POST 请求体，没有记录密钥、完整返回值或价格。
- **京东**：校正好京客自己的分页参数 `pageindex/pagesize` 和 `data.data[]` 字段格式后，仍返回 `status_code=1`、字符串型 `data`。尚不能判断是账户京东联盟设置、服务端限制还是接口参数问题；**未获得可信价格**。
- **拼多多**：一次真实查询返回 `status_code=200` 与 5 条商品行，但 0 条通过 RTX 5070 严格商品/SKU 校验；说明接口可访问，**不代表该型号有可用报价**。
- **可用性**：另一次 HTTPS 复测两平台均出现连接超时，不能证明目前具备稳定自动采集条件。
- **安全**：以上冒烟工作流未写入 `market.json`，不曾部署公开数据，`MARKET_PUBLISH_ENABLED` 保持未启用。

公开展示前还需解决：获得真实可命中的硬件 SKU、验证多种硬件型号的有效覆盖率、确认稳定性/免费额度及数据存储和再分发许可。不要因为能返回 200 就认为价格数据可直接公开。

### 2026-11-20 京东商品 API 覆盖复核

在不记录凭据及商品响应原文的隔离 GitHub Actions 测试中，京东商品列表接口返回成功状态，但未检索到测试型号。

| 京东 `goodslist` 请求方式 | 接口状态 | `total` | 商品行数 |
| --- | --- | ---: | ---: |
| 关键词 RTX5070 | 200 | 0 | 0 |
| 关键词 9800X3D | 200 | 0 | 0 |
| 关键词 DDR5 | 200 | 0 | 0 |
| `goods_ids` 指定两个公开报道过的京东商品 ID | 200 | 0 | 0 |

[列表测试 GitHub Actions #7](https://github.com/royluobox/tubatools-pc-price-data/actions/runs/44699627726) 的执行结果为成功，但**API 调用成功不意味着查到了硬件商品**。

根据[服务方京东 API 文档](https://www.haojingke.com/open-api/jd)还独立测试了 `jd/goodsdetail` 的两个 SKU。均返回非成功状态及字符串类型的 `data`，没有商品详情对象或可用价格字段；未公开任何原始商品响应或价格。[详情接口诊断 GitHub Actions #9](https://github.com/royluobox/tubatools-pc-price-data/actions/runs/44700186960)。

样本量有限，**不能推断整个京东商品库没有硬件**；只能确认目前这组 API 调用不具备可信的插件价格覆盖。具体原因（商品池、接口权限、SKU 是否参与推广等）未得到服务方确认。先前测试的 `status_code=1` 不再反映本次 `goodslist` 的观察。

**工程决定：** 保持 `MARKET_PUBLISH_ENABLED` 关闭；不将无商品编码为 0 元、不生成虚构的 `market.json`、不把 ZOL 参考价当作电商成交价、不做频繁无效轮询。现有 VRAMGlass（闲鱼挂牌口径）与 ZOL（参考价口径）继续独立展示。待取得可命中的硬件商品样本、验证定价口径及再分发许可之后，再决定是否正式采集。

#### 京东商品覆盖不足的进一步核对

- 在[蚂蚁星球会员中心](https://www.haojingke.com/center/index.html#/personal/dashboard)查找「京东联盟设置」或「我的京盟」，确认京东联盟账号关联状态；必要时先了解[京东联盟](https://union.jd.com)注册与推广位管理。
- [好京客京东 API 文档](https://www.haojingke.com/open-api/jd)说明部分**转链、订单**接口需要京东联盟设置；这不能直接证明**商品搜索**接口的状态码 1 也是同一原因。需向服务方核实 `goodslist` 返回错误含义。
- 不要把联盟 App Secret、会员登录密码或完整错误响应发到聊天或提交仓库。后续用上面的限量手动测试分别检查显卡与 CPU 的命中率。

## 备用：淘宝联盟官方 TOP API

官方文档：[淘宝客-推广者-物料搜索](https://developer.alibaba.com/docs/api.htm?apiId=35896)。接口标记免费且无需额外的用户授权，但创建应用、媒体备案、推广位和业务权限仍可能需要额外材料。PC 客户端备案要求上传软件 X.509 数字签名证书，不适合为了一个插件随意使用宿主程序的证书。

如将来合法获得权限，可在 Secrets 中放入 `TBK_APP_KEY`、`TBK_APP_SECRET`、`TBK_ADZONE_ID`，将 `MARKET_PROVIDER` 设置为 `taobao`，并在确认展示/缓存条款后开启发布变量。

## 关于真实性与安全

- 无 API Key 或未取得再分发许可时，公开的 `market.json` **不会被生成**；插件仍可独立查看 VRAMGlass/ZOL。
- 不能把第三方 API 返回值当成京东商城实时结算价，价格类型标记 `original-reference`。
- 只发布 `jd.com` / `yangkeduo.com` 的匹配 SKU 及其参考价；不发布第三方原始响应。
- API 密钥仅供 Actions 采集任务使用。生产查询会拒绝 HTTP 或重定向，日志只打印异常类型、数字状态码、数据结构及固定错误类别，不打印 Key 或响应体。
- 已完成低频真实 API 测试，但京东目标硬件覆盖尚不可用，服务稳定性、配额和再分发许可仍未验证通过；单元测试继续使用不含真实凭据的模拟数据。
