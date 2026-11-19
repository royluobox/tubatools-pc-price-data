using System.Globalization;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;
using PcPriceTrend;

var pages = int.TryParse(Environment.GetEnvironmentVariable("ZOL_PAGES"), out var pageCount)
    ? Math.Clamp(pageCount, 1, 10)
    : 4;
var trendModels = int.TryParse(Environment.GetEnvironmentVariable("TREND_MODELS"), out var modelCount)
    ? Math.Clamp(modelCount, 4, 40)
    : 20;

var root = Directory.GetCurrentDirectory();
var output = Path.Combine(root, "site", "data", "catalog.json");
var today = DateOnly.FromDateTime(DateTimeOffset.UtcNow.ToLocalTime().DateTime);
var client = new ZolClient();
var products = new Dictionary<string, ProductDto>(StringComparer.Ordinal);
var errors = new List<string>();

foreach (var slug in Catalog.Slugs)
{
    Console.WriteLine($"fetch {slug}");
    var (items, _, errs) = await client.FetchCategoryAsync(slug, pages, CancellationToken.None);
    foreach (var item in items)
    {
        products[item.Id] = item;
    }

    errors.AddRange(errs);
}

if (products.Count == 0)
{
    Console.Error.WriteLine("ZOL 没有返回任何产品，保留上一次 catalog.json");
    return 1;
}

var groups = new Dictionary<string, List<ProductDto>>(StringComparer.Ordinal);
foreach (var product in products.Values)
{
    var (key, name) = ModelKeyExtractor.Extract(product.Name, product.Slug);
    product.ModelKey = key;
    product.ModelName = name;
    var groupKey = product.Slug + "|" + key;
    if (!groups.TryGetValue(groupKey, out var list))
    {
        list = [];
        groups[groupKey] = list;
    }

    list.Add(product);
}

var models = new List<BuildModel>(groups.Count);
foreach (var pair in groups)
{
    var list = pair.Value;
    var prices = new List<int>();
    foreach (var product in list)
    {
        prices.AddRange(CollectSamplePrices(product));
    }

    var summary = ModelMath.Summarize(prices);
    if (summary.Median <= 0)
    {
        continue;
    }

    models.Add(new BuildModel
    {
        Key = pair.Key,
        Name = list[0].ModelName,
        Slug = list[0].Slug,
        Category = string.IsNullOrEmpty(list[0].Category) ? Catalog.NameOfSlug(list[0].Slug) : list[0].Category,
        Price = summary.Median,
        Low = summary.Low,
        High = summary.High,
        SkuCount = list.Count,
        Products = list,
    });
}

Console.WriteLine($"models={models.Count}, errors={errors.Count}");

foreach (var group in models.GroupBy(m => m.Slug))
{
    var top = group
        .OrderByDescending(m => m.SkuCount)
        .ThenByDescending(m => m.Price)
        .Take(trendModels)
        .ToList();

    var rank = 0;
    foreach (var model in top)
    {
        rank++;
        var skus = model.Products
            .Where(p => CollectSamplePrices(p).Any(price =>
                price >= model.Price * 0.7 && price <= model.Price * 1.3))
            .OrderBy(p => p.Price)
            .ToList();
        if (skus.Count == 0)
        {
            continue;
        }

        // 前 20 个型号多取一个 SKU，其余取一个，尽量扩大历史覆盖率。
        var pickCount = rank <= 20 ? 2 : 1;
        var picks = skus.Count <= pickCount ? skus : PickRepresentativeSkus(skus, pickCount);
        var daily = new SortedDictionary<DateOnly, List<int>>();
        var popularity = 0;
        foreach (var sku in picks)
        {
            var trend = await client.FetchTrendAsync(sku.Id, CancellationToken.None);
            foreach (var pair in trend.Prices)
            {
                if (pair.Key >= today || !Catalog.IsPlausiblePrice(sku.Slug, pair.Value))
                {
                    continue;
                }

                if (!daily.TryGetValue(pair.Key, out var dayPrices))
                {
                    dayPrices = [];
                    daily[pair.Key] = dayPrices;
                }

                dayPrices.Add(pair.Value);
            }

            var weekHits = trend.Hits
                .Where(pair => pair.Key >= today.AddDays(-7))
                .Sum(pair => pair.Value);
            popularity = Math.Max(popularity, weekHits);
            await Task.Delay(250, CancellationToken.None);
        }

        var history = new List<HistoryPoint>();
        foreach (var pair in daily)
        {
            var summary = ModelMath.Summarize(pair.Value);
            if (summary.Median <= 0 ||
                summary.Median < model.Price * 0.4 ||
                summary.Median > model.Price * 2.5)
            {
                continue;
            }

            history.Add(new HistoryPoint(pair.Key.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
                summary.Median));
        }

        model.Popularity = popularity;
        model.History = history;
        if (history.Count > 1 &&
            DateOnly.TryParseExact(history[0].D, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                DateTimeStyles.None, out var first) &&
            DateOnly.TryParseExact(history[^1].D, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                DateTimeStyles.None, out var last))
        {
            model.HistoryDays = Math.Max(0, last.DayNumber - first.DayNumber);
        }

        Console.WriteLine($"{model.Key} history={history.Count} hits={popularity}");
    }
}

var feed = new
{
    schema = 1,
    capturedAt = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture),
    source = "ZOL",
    sourceUrl = "https://detail.zol.com.cn/",
    attribution = "数据来源：中关村在线（detail.zol.com.cn）公开报价与产品趋势页；由 GitHub Actions 定时汇总。数据仅供参考，不构成交易建议。",
    models = models.Select(model => new
    {
        modelKey = model.Key,
        model.Name,
        model.Slug,
        model.Category,
        price = model.Price,
        low = model.Low,
        high = model.High,
        skuCount = model.SkuCount,
        popularity = model.Popularity,
        historyDays = model.HistoryDays,
        history = model.History,
    }).ToList(),
    errors = errors.Take(10).ToList(),
};

Directory.CreateDirectory(Path.GetDirectoryName(output)!);
var json = JsonSerializer.Serialize(feed, new JsonSerializerOptions
{
    WriteIndented = false,
    Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
});
File.WriteAllText(output, json);
Console.WriteLine($"wrote {output} ({new FileInfo(output).Length / 1024} KB)");
return 0;

static List<int> CollectSamplePrices(ProductDto product)
{
    var prices = new HashSet<int>();
    var hasBase = Catalog.IsPlausiblePrice(product.Slug, product.Price);
    if (hasBase)
    {
        prices.Add(product.Price);
    }

    if (product.Quotes is not null)
    {
        foreach (var quote in product.Quotes)
        {
            if (quote.Price <= 0 || !Catalog.IsPlausiblePrice(product.Slug, quote.Price))
            {
                continue;
            }

            if (hasBase)
            {
                var (lowRatio, highRatio) = product.Slug switch
                {
                    "solid_state_drive" or "hard_drives" => (0.7, 1.4),
                    "memory" => (0.6, 1.8),
                    _ => (0.5, 2.0),
                };
                if (quote.Price < product.Price * lowRatio || quote.Price > product.Price * highRatio)
                {
                    continue;
                }
            }

            prices.Add(quote.Price);
        }
    }

    return prices.ToList();
}

static List<ProductDto> PickRepresentativeSkus(List<ProductDto> skus, int max)
{
    if (skus.Count <= max)
    {
        return skus;
    }

    var picks = new List<ProductDto>(max);
    foreach (var index in new[] { 0, skus.Count / 2, skus.Count - 1 })
    {
        if (picks.Count >= max)
        {
            break;
        }

        var product = skus[Math.Clamp(index, 0, skus.Count - 1)];
        if (!picks.Contains(product))
        {
            picks.Add(product);
        }
    }

    return picks;
}

internal sealed class BuildModel
{
    public required string Key { get; init; }
    public required string Name { get; init; }
    public required string Slug { get; init; }
    public required string Category { get; init; }
    public required List<ProductDto> Products { get; init; }
    public int Price { get; init; }
    public int Low { get; init; }
    public int High { get; init; }
    public int SkuCount { get; init; }
    public int Popularity { get; set; }
    public int HistoryDays { get; set; }
    public List<HistoryPoint> History { get; set; } = [];
}

internal readonly record struct HistoryPoint(
    [property: JsonPropertyName("d")] string D,
    [property: JsonPropertyName("median")] int Median);
