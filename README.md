# tubatools-pc-price-data

图吧工具箱「电脑配件价格走势」插件的公开行情快照仓库。

- 数据地址：<https://royluobox.github.io/tubatools-pc-price-data/data/latest.json>
- 更新方式：GitHub Actions 每 8 小时调用 VRAMGlass 公开 API，抓取闲鱼市场 10 个主流显卡型号的现价、挂单数和最多 365 天历史。
- 插件读取这份快照后，所有下载者无需自备 API Key 即可看到显卡现价与历史走势；插件包内还会附带打包时的种子数据（seed），离线时也能显示最近行情。

## 数据来源与声明

数据来源：**VRAMGlass**（<https://vramglass.com/>）。本仓库仅为公开接口数据的定时快照，用于插件分发场景，不存储、不收集用户数据。

- 数据版权归 VRAMGlass 所有，仅供参考，不构成交易建议。
- VRAMGlass 与图吧工具箱无隶属关系。
- 如数据提供方希望停止镜像，请提交 Issue，本仓库会立即下线数据。

## 结构

```
site/data/latest.json   # 插件读取的快照
site/index.html         # 数据说明页
scripts/fetch_feed.py   # 抓取脚本（VRAMGLASS_KEY 由仓库 Secret 注入）
.github/workflows/      # 定时抓取并部署 GitHub Pages
```

`latest.json` 主要字段：

| 字段 | 含义 |
| --- | --- |
| `capturedAt` | 快照抓取时间（UTC） |
| `attribution` | 来源署名与免责声明 |
| `models[].vramglassId` | VRAMGlass 型号 ID |
| `models[].modelKey` | 插件内型号键，例如 `vga\|RTX5090` |
| `models[].price/low/high` | 中位价与 Q1/Q3 区间（元） |
| `models[].listingCount` | 闲鱼在售挂单数 |
| `models[].history[]` | `{d: 日期, median: 中位价}`，最多 365 天 |

## 部署

仓库 Settings → Pages → Source 选择 **GitHub Actions**；在 Actions 中手动运行一次 `Update price feed` 即可发布。仓库 Secret `VRAMGLASS_KEY` 保存 API Key，不会出现在代码或数据中。
