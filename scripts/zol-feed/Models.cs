namespace PcPriceTrend;

/// <summary>列表筛选条件：类别键、显示名、对应 ZOL 分类与搜索提示。</summary>
public sealed class FilterDef
{
    public required string Key { get; init; }
    public required string Name { get; init; }
    public string? Slug { get; init; }
    public string Hint { get; init; } = "搜索型号";
}

public static class Catalog
{
    // 采集的产品库分类（ZOL 分类 slug）
    public static readonly string[] Slugs =
    [
        "vga", "cpu", "motherboard", "memory", "solid_state_drive", "hard_drives",
        "power", "case", "cooling_product", "lcd", "keyboard", "mice",
    ];

    public static readonly FilterDef[] Filters =
    [
        new() { Key = "all", Name = "全部配件", Hint = "搜索型号或分类，例如：RTX 5060、i5-14600KF" },
        new() { Key = "vga", Name = "显卡", Slug = "vga", Hint = "搜索显卡，例如：RTX 5060、9070 XT" },
        new() { Key = "cpu", Name = "CPU", Slug = "cpu", Hint = "搜索 CPU，例如：i5-14600KF、9800X3D" },
        new() { Key = "mb", Name = "主板", Slug = "motherboard", Hint = "搜索主板，例如：B760M、B650M" },
        new() { Key = "mem", Name = "内存", Slug = "memory", Hint = "搜索内存，例如：DDR5 32G 6000" },
        new() { Key = "ssd", Name = "固态硬盘", Slug = "solid_state_drive", Hint = "搜索固态，例如：990 PRO、TiPlus7100" },
        new() { Key = "hdd", Name = "机械硬盘", Slug = "hard_drives", Hint = "搜索机械硬盘，例如：4TB、监控盘" },
        new() { Key = "psu", Name = "电源", Slug = "power", Hint = "搜索电源，例如：850W、GX-850" },
        new() { Key = "case", Name = "机箱", Slug = "case", Hint = "搜索机箱，例如：海景房、MATX" },
        new() { Key = "cooler", Name = "散热器", Slug = "cooling_product", Hint = "搜索散热器，例如：AX120R、360 水冷" },
        new() { Key = "monitor", Name = "显示器", Slug = "lcd", Hint = "搜索显示器，例如：27 英寸 2K" },
        new() { Key = "kb", Name = "键盘", Slug = "keyboard", Hint = "搜索键盘，例如：机械键盘、87 键" },
        new() { Key = "mouse", Name = "鼠标", Slug = "mice", Hint = "搜索鼠标，例如：GPW、无线" },
    ];

    /// <summary>首页默认展示的主流型号（约 16 款），按装机关注度挑选。</summary>
    public static readonly string[] MainstreamKeys =
    [
        "vga|RTX5090",
        "vga|RTX5080",
        "vga|RTX5070TI",
        "vga|RTX5070",
        "vga|RTX5060TI",
        "vga|RTX5060",
        "vga|RX9070XT",
        "vga|RX9070",
        "vga|RX9060XT",
        "vga|RTX4060",
        "cpu|I514600KF",
        "cpu|RYZEN59600X",
        "cpu|RYZEN79800X3D",
        "memory|DDR532G6000",
        "memory|DDR416G3200",
        "solid_state_drive|三星990PRO",
    ];

    public static readonly HashSet<string> MainstreamKeySet = new(MainstreamKeys, StringComparer.Ordinal);

    /// <summary>VRAMGlass 的显卡 id 映射；只用于有公开历史价和挂单数的型号。</summary>
    public static readonly Dictionary<string, string> VramGlassIds = new(StringComparer.Ordinal)
    {
        ["vga|RTX5090"] = "rtx-5090",
        ["vga|RTX5080"] = "rtx-5080",
        ["vga|RTX5070TI"] = "rtx-5070-ti",
        ["vga|RTX5070"] = "rtx-5070",
        ["vga|RTX5060TI"] = "rtx-5060-ti-16gb",
        ["vga|RTX5060"] = "rtx-5060",
        ["vga|RX9070XT"] = "rx-9070-xt",
        ["vga|RX9070"] = "rx-9070",
        ["vga|RX9060XT"] = "rx-9060-xt-16gb",
        ["vga|RTX4060"] = "rtx-4060",
    };

    /// <summary>历史保留 400 天，覆盖「近 1 年」；30 天前折叠为每日一个点。</summary>
    public const int HistoryRetentionDays = 400;
    public const int HourlyRetentionDays = 30;

    public static FilterDef FilterOf(string key) =>
        Filters.FirstOrDefault(f => f.Key == key) ?? Filters[0];

    public static string SearchHintOf(string key) => FilterOf(key).Hint;

    public static string NameOfSlug(string slug) => slug switch
    {
        "vga" => "显卡",
        "cpu" => "CPU",
        "motherboard" => "主板",
        "memory" => "内存",
        "solid_state_drive" => "固态硬盘",
        "hard_drives" => "机械硬盘",
        "power" => "电源",
        "case" => "机箱",
        "cooling_product" => "散热器",
        "lcd" => "显示器",
        "keyboard" => "键盘",
        "mice" => "鼠标",
        _ => slug,
    };

    /// <summary>硬盘分类里按名称判断是固态还是机械，避免重复入库。</summary>
    public static bool LooksLikeSsd(string name)
    {
        var upper = name.ToUpperInvariant();
        return upper.Contains("固态") || upper.Contains("SSD") || upper.Contains("NVME") ||
               upper.Contains("M.2") || upper.Contains("M2 ") || upper.Contains("闪存");
    }

    /// <summary>不同类别的最低合理报价，用于过滤 25 元 H200 这类明显脏数据。</summary>
    public static int MinPriceOf(string slug) => slug switch
    {
        "vga" => 100,
        "lcd" => 100,
        "cpu" => 50,
        "motherboard" => 30,
        "memory" => 20,
        "solid_state_drive" => 20,
        "hard_drives" => 20,
        "power" => 10,
        "case" => 10,
        "cooling_product" => 10,
        _ => 5,
    };

    public static bool IsPlausiblePrice(string slug, int price) => price >= MinPriceOf(slug);
}

/// <summary>单个电商平台对某款 SKU 的报价，例如京东、天猫。</summary>
public sealed class PriceQuote
{
    public string Platform { get; set; } = "";
    public int Price { get; set; }
    public string Url { get; set; } = "";
}

/// <summary>ZOL 列表页里的单个报价（厂商 SKU），只作为型号聚合的原始样本。</summary>
public sealed class ProductDto
{
    public string Id { get; set; } = "";
    public string Slug { get; set; } = "";
    public string Category { get; set; } = "";
    public string SubType { get; set; } = "";
    public string Name { get; set; } = "";
    public string Url { get; set; } = "";
    public int Price { get; set; }
    public long Updated { get; set; }
    public long FirstSeen { get; set; }

    /// <summary>京东、天猫等平台当前报价，作为中位价的额外样本。</summary>
    public List<PriceQuote> Quotes { get; set; } = [];

    // 型号级聚合结果，旧版本目录没有这三个字段，加载后会触发一次迁移。
    public string ModelId { get; set; } = "";
    public string ModelKey { get; set; } = "";
    public string ModelName { get; set; } = "";
}

/// <summary>若干厂商 SKU 聚合出的型号，例如「RTX 5060」。Price 为样本中位价。</summary>
public sealed class ModelDto
{
    public string Id { get; set; } = "";
    public string Key { get; set; } = "";
    public string Name { get; set; } = "";
    public string Slug { get; set; } = "";
    public string Category { get; set; } = "";
    public int Price { get; set; }
    public int Low { get; set; }
    public int High { get; set; }
    public int SkuCount { get; set; }
    public long Updated { get; set; }
    public long FirstSeen { get; set; }

    /// <summary>VRAMGlass 的闲鱼挂单数，作为“购买量/热度”的排序依据。</summary>
    public int ListingCount { get; set; }

    /// <summary>ZOL 产品趋势页的关注人数，作为非显卡分类的热度依据。</summary>
    public int Popularity { get; set; }

    public string VramGlassId { get; set; } = "";
    public long VramGlassUpdated { get; set; }
    public long HistoryFetched { get; set; }
    public int HistoryDays { get; set; }
    public bool Tracked { get; set; }
}

/// <summary>VRAMGlass 配置，只需要一个免费 API 密钥。</summary>
public sealed class VramGlassOptions
{
    public const string DefaultBaseUrl = "https://api.vramglass.com/v1";

    public string ApiKey { get; set; } = "";
    public string BaseUrl { get; set; } = DefaultBaseUrl;
    public bool Enabled => !string.IsNullOrWhiteSpace(ApiKey);

    public VramGlassOptions Clone() => new() { ApiKey = ApiKey, BaseUrl = BaseUrl };
}


/// <summary>旧版单品价格点：Unix 秒 + 参考价格（元）。仅用于迁移。</summary>
public readonly record struct PricePoint(long T, int P);

/// <summary>型号价格点：中位价、区间低/高价与当次样本数。</summary>
public readonly record struct ModelPoint(long T, int Median, int Low, int High, int Count);

public sealed class StoreState
{
    public int SchemaVersion { get; set; }
    public long LastRefresh { get; set; }
    public int ProductCount { get; set; }
    public int ModelCount { get; set; }
    public string LastError { get; set; } = "";

    // GitHub Pages 在线快照的同步状态；旧版本没有这些字段，反序列化时自动为 0。
    public long FeedFetched { get; set; }
    public long FeedCaptured { get; set; }
    public string FeedAttribution { get; set; } = "";
}

public sealed class RefreshResult
{
    public int Fetched { get; set; }
    public int Total { get; set; }
    public int Models { get; set; }
    public int Requests { get; set; }
    public string Error { get; set; } = "";
    public TimeSpan Elapsed { get; set; }
}
