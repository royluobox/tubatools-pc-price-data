using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PcPriceTrend;

/// <summary>
/// 中关村在线（ZOL）产品库采集：列表页给每个型号的参考价。
/// 页面为 GBK 编码，需 CodePages 提供程序。
/// </summary>
public sealed partial class ZolClient
{
    private const string Host = "https://detail.zol.com.cn";
    private const int PageSize = 48;

    private static readonly HttpClient Http = CreateHttp();
    private static readonly Encoding Gbk = CreateEncoding();
    private static int _encodingReady;

    private static HttpClient CreateHttp()
    {
        var handler = new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.All,
            UseCookies = true,
        };
        var client = new HttpClient(handler)
        {
            Timeout = TimeSpan.FromSeconds(20),
        };
        client.DefaultRequestHeaders.TryAddWithoutValidation(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0");
        client.DefaultRequestHeaders.TryAddWithoutValidation("Accept-Language", "zh-CN,zh;q=0.9");
        client.DefaultRequestHeaders.TryAddWithoutValidation("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8");
        return client;
    }

    private static Encoding CreateEncoding()
    {
        if (Interlocked.Exchange(ref _encodingReady, 1) == 0)
        {
            try { Encoding.RegisterProvider(CodePagesEncodingProvider.Instance); } catch { }
        }

        try
        {
            return Encoding.GetEncoding("GB18030");
        }
        catch
        {
            return Encoding.UTF8;
        }
    }

    /// <summary>抓取一个分类的前 pages 页，返回解析出的型号列表。</summary>
    public async Task<(List<ProductDto> Items, int Requests, List<string> Errors)> FetchCategoryAsync(
        string slug, int pages, CancellationToken ct)
    {
        var items = new List<ProductDto>();
        var errors = new List<string>();
        var requests = 0;

        var firstHtml = await GetAsync($"{Host}/{slug}/", ct, errors);
        requests++;
        if (firstHtml is null)
        {
            return (items, requests, errors);
        }

        items.AddRange(ParseList(firstHtml, slug));

        var totalPages = ParseTotalPages(firstHtml, slug);
        var last = Math.Min(Math.Max(1, pages), Math.Max(1, totalPages));
        for (var n = 2; n <= last; n++)
        {
            ct.ThrowIfCancellationRequested();
            await Task.Delay(350, ct);
            var html = await GetAsync($"{Host}/{slug}/{n}.html", ct, errors);
            requests++;
            if (html is null)
            {
                continue;
            }

            items.AddRange(ParseList(html, slug));
        }

        return (items, requests, errors);
    }

    private static async Task<string?> GetAsync(string url, CancellationToken ct, List<string> errors)
    {
        for (var attempt = 1; attempt <= 3; attempt++)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Get, url);
                req.Headers.Referrer = new Uri($"{Host}/");
                using var resp = await Http.SendAsync(req, HttpCompletionOption.ResponseContentRead, ct);
                if (!resp.IsSuccessStatusCode)
                {
                    throw new HttpRequestException($"HTTP {(int)resp.StatusCode}");
                }

                var bytes = await resp.Content.ReadAsByteArrayAsync(ct);
                if (bytes.Length < 512)
                {
                    throw new HttpRequestException("返回内容为空");
                }

                return Gbk.GetString(bytes);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                throw;
            }
            catch (Exception ex)
            {
                if (attempt >= 3)
                {
                    errors.Add($"{url.Replace(Host, "")} 抓取失败：{ex.Message}");
                    return null;
                }

                try { await Task.Delay(1500 * attempt, ct); } catch (OperationCanceledException) { throw; }
            }
        }

        return null;
    }

    /// <summary>解析分类列表页中的型号、参考价与详情链接。</summary>
    public static List<ProductDto> ParseList(string html, string slug)
    {
        var result = new List<ProductDto>();
        var category = Catalog.NameOfSlug(slug);
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var index = 0;

        while (true)
        {
            var match = LiStartRegex().Match(html, index);
            if (!match.Success)
            {
                break;
            }

            var start = match.Index;
            var end = html.IndexOf("</li>", match.Index + match.Length, StringComparison.Ordinal);
            if (end < 0)
            {
                end = Math.Min(html.Length, start + 6000);
            }

            var block = html[start..end];
            index = end + 5;

            var id = match.Groups[1].Value;
            var priceMatch = PriceRegex().Match(block);
            if (!priceMatch.Success)
            {
                continue; // 暂无报价的型号跳过
            }

            var raw = priceMatch.Groups[1].Value.Replace(",", "").Trim();
            if (!int.TryParse(raw, out var price) || price <= 0)
            {
                continue;
            }

            var name = ParseName(block);
            if (string.IsNullOrWhiteSpace(name))
            {
                continue;
            }

            var hrefMatch = HrefRegex().Match(block);
            var url = hrefMatch.Success
                ? Host + hrefMatch.Groups[1].Value
                : $"{Host}/{slug}/index{id}.shtml";

            var subType = "";
            if (slug == "hard_drives")
            {
                if (Catalog.LooksLikeSsd(name))
                {
                    continue; // 固态硬盘由独立分类采集，避免重复入库
                }

                subType = "hdd";
            }

            result.Add(new ProductDto
            {
                Id = id,
                Slug = slug,
                Category = category,
                SubType = subType,
                Name = name,
                Url = url,
                Price = price,
                Quotes = ParseB2cQuotes(block, slug),
                Updated = now,
                FirstSeen = now,
            });
        }

        return result;
    }

    /// <summary>解析列表项里的京东/天猫等平台报价，作为型号中位价的额外样本。</summary>
    public static List<PriceQuote> ParseB2cQuotes(string block, string slug)
    {
        var result = new List<PriceQuote>();
        foreach (Match match in B2cLinkRegex().Matches(block))
        {
            var inner = match.Groups["inner"].Value;
            var priceMatch = B2cPriceRegex().Match(inner);
            if (!priceMatch.Success)
            {
                continue;
            }

            var raw = priceMatch.Groups["num"].Value.Replace(",", "").Trim();
            if (!decimal.TryParse(raw, NumberStyles.Number, CultureInfo.InvariantCulture, out var value))
            {
                continue;
            }

            if (priceMatch.Groups["wan"].Success)
            {
                value *= 10000;
            }

            var price = (int)Math.Round(value, MidpointRounding.AwayFromZero);
            if (price <= 0 || !Catalog.IsPlausiblePrice(slug, price))
            {
                continue;
            }

            var icon = B2cIconRegex().Match(inner);
            var platform = icon.Success ? PlatformOf(icon.Groups["name"].Value) : "电商";
            if (result.Any(q => q.Platform == platform && q.Price == price))
            {
                continue;
            }

            var href = B2cHrefRegex().Match(match.Groups["attrs"].Value);
            result.Add(new PriceQuote
            {
                Platform = platform,
                Price = price,
                Url = href.Success ? href.Groups["url"].Value : "",
            });
            if (result.Count >= 6)
            {
                break;
            }
        }

        return result;
    }

    private static string PlatformOf(string iconName) => iconName.ToLowerInvariant() switch
    {
        "jd" => "京东",
        "tmall" => "天猫",
        "taobao" => "淘宝",
        "suning" => "苏宁",
        "vip" => "唯品会",
        "pdd" => "拼多多",
        "gome" => "国美",
        "zol" => "ZOL商城",
        _ => "电商",
    };

    /// <summary>产品趋势页里的每日关注人数与价格历史。</summary>
    public readonly record struct ZolTrend(
        SortedDictionary<DateOnly, int> Prices,
        SortedDictionary<DateOnly, int> Hits);

    /// <summary>读取 ZOL 产品趋势页的 chartArr：prices 为每日价格，hits 为关注人数。</summary>
    public async Task<ZolTrend> FetchTrendAsync(string productId, CancellationToken ct)
    {
        var prices = new SortedDictionary<DateOnly, int>();
        var hits = new SortedDictionary<DateOnly, int>();
        if (!int.TryParse(productId, out var id) || id <= 0)
        {
            return new ZolTrend(prices, hits);
        }

        var subPath = (id + 999) / 1000;
        var url = $"{Host}/{subPath}/{id}/pro_hit.shtml";
        var errors = new List<string>();
        var html = await GetAsync(url, ct, errors).ConfigureAwait(false);
        if (html is null)
        {
            return new ZolTrend(prices, hits);
        }

        var match = ChartArrRegex().Match(html);
        if (!match.Success)
        {
            return new ZolTrend(prices, hits);
        }

        try
        {
            using var document = JsonDocument.Parse(match.Groups["json"].Value);
            ReadDateValues(document.RootElement, prices, "prices", "Prices");
            ReadDateValues(document.RootElement, hits, "hits", "Hits");
        }
        catch (JsonException)
        {
            // 趋势页偶尔缺少完整数据，按无历史处理
        }

        return new ZolTrend(prices, hits);
    }

    public async Task<SortedDictionary<DateOnly, int>> FetchPriceHistoryAsync(string productId, CancellationToken ct)
    {
        var trend = await FetchTrendAsync(productId, ct).ConfigureAwait(false);
        return trend.Prices;
    }

    private static void ReadDateValues(
        JsonElement root,
        SortedDictionary<DateOnly, int> target,
        params string[] names)
    {
        var values = default(JsonElement);
        var found = false;
        foreach (var name in names)
        {
            if (root.TryGetProperty(name, out var candidate))
            {
                values = candidate;
                found = true;
                break;
            }
        }

        if (!found || values.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        foreach (var property in values.EnumerateObject())
        {
            if (!DateOnly.TryParseExact(property.Name, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                    DateTimeStyles.None, out var date))
            {
                continue;
            }

            if (property.Value.TryGetInt32(out var value) && value > 0)
            {
                target[date] = value;
            }
        }
    }

    private static string ParseName(string block)
    {
        var h3 = block.IndexOf("<h3", StringComparison.Ordinal);
        if (h3 < 0)
        {
            return "";
        }

        var open = block.IndexOf('>', h3);
        var close = block.IndexOf("</h3>", h3, StringComparison.Ordinal);
        if (open < 0 || close < 0 || close <= open)
        {
            return "";
        }

        var inner = block[(open + 1)..close];
        inner = SpanRegex().Replace(inner, "");
        inner = TagRegex().Replace(inner, "");
        inner = WebUtility.HtmlDecode(inner);
        return NormalizeWhitespace(inner);
    }

    private static string NormalizeWhitespace(string value)
    {
        var sb = new StringBuilder(value.Length);
        var space = false;
        foreach (var ch in value)
        {
            if (char.IsWhiteSpace(ch))
            {
                if (!space && sb.Length > 0)
                {
                    sb.Append(' ');
                }

                space = true;
                continue;
            }

            space = false;
            sb.Append(ch);
        }

        return sb.ToString().Trim();
    }

    private static int ParseTotalPages(string html, string slug)
    {
        var m = TotalRegex().Match(html);
        if (m.Success && int.TryParse(m.Groups[1].Value, out var total) && total > 0)
        {
            return (int)Math.Ceiling(total / (double)PageSize);
        }

        var max = 1;
        foreach (Match pm in PageLinkRegex().Matches(html))
        {
            if (int.TryParse(pm.Groups[1].Value, out var page) && page > max && page < 500)
            {
                max = page;
            }
        }

        return max;
    }

    [GeneratedRegex("<li[^>]*data-follow-id=\"p(\\d+)\"[^>]*>")]
    private static partial Regex LiStartRegex();

    [GeneratedRegex("class=\"price-type\">\\s*([\\d,]+)")]
    private static partial Regex PriceRegex();

    [GeneratedRegex("href=\"(/[a-z_0-9]+/index\\d+\\.shtml)\"")]
    private static partial Regex HrefRegex();

    [GeneratedRegex("<span[^>]*>.*?</span>", RegexOptions.Singleline)]
    private static partial Regex SpanRegex();

    [GeneratedRegex("<[^>]+>")]
    private static partial Regex TagRegex();

    [GeneratedRegex("class=\"total\">共\\s*<b>(\\d+)</b>")]
    private static partial Regex TotalRegex();

    [GeneratedRegex("/[a-z_0-9]+/(\\d+)\\.html")]
    private static partial Regex PageLinkRegex();

    [GeneratedRegex(@"<a(?<attrs>[^>]*class=""itemsub-b2c[^""]*""[^>]*)>(?<inner>.*?)</a>", RegexOptions.Singleline)]
    private static partial Regex B2cLinkRegex();

    [GeneratedRegex(@"href=""(?<url>[^""]+)""", RegexOptions.IgnoreCase)]
    private static partial Regex B2cHrefRegex();

    [GeneratedRegex(@"b2c-icon/(?<name>[a-z]+)\d*\.png", RegexOptions.IgnoreCase)]
    private static partial Regex B2cIconRegex();

    [GeneratedRegex(@"(?:&yen;|￥)\s*(?<num>\d+(?:\.\d+)?)\s*(?<wan>万)?", RegexOptions.IgnoreCase)]
    private static partial Regex B2cPriceRegex();

    [GeneratedRegex(@"var\s+chartArr\s*=\s*(?<json>\{.*?\})\s*;", RegexOptions.Singleline)]
    private static partial Regex ChartArrRegex();
}
