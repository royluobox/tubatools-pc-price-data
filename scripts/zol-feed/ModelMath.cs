namespace PcPriceTrend;

/// <summary>
/// 型号价格聚合：同一型号下多个品牌 SKU 的价格用中位数代表，
/// 区间低/高价用 MAD（中位数绝对偏差）剔除异常报价，避免“25 元 H200”这类脏数据拉偏曲线。
/// 中位数聚合与稳健离群值过滤是公开价格指数常用的做法。
/// </summary>
public static class ModelMath
{
    /// <summary>返回中位价、稳健区间低/高价与参与统计的样本数。</summary>
    public static (int Median, int Low, int High, int Count) Summarize(IReadOnlyList<int> prices)
    {
        var valid = new List<int>(prices.Count);
        foreach (var price in prices)
        {
            if (price > 0)
            {
                valid.Add(price);
            }
        }

        if (valid.Count == 0)
        {
            return (0, 0, 0, 0);
        }

        valid.Sort();
        var median = Median(valid);
        var useMad = valid.Count >= 4;

        // 样本很少时放宽相对区间，避免把真实的低配/高配版本全部裁掉；
        // 样本足够时使用更严格的 0.5~2 倍区间，再叠加 MAD。
        var relativeLow = useMad ? median * 0.5 : median * 0.1;
        var relativeHigh = useMad ? median * 2.0 : median * 10.0;

        var limit = double.MaxValue;
        if (useMad)
        {
            var deviations = new int[valid.Count];
            for (var i = 0; i < valid.Count; i++)
            {
                deviations[i] = Math.Abs(valid[i] - median);
            }

            Array.Sort(deviations);
            var mad = Median(deviations);
            limit = mad > 0 ? mad * 6.0 : Math.Max(median * 0.5, 50.0);
        }

        var low = int.MaxValue;
        var high = 0;
        foreach (var price in valid)
        {
            if (price < relativeLow || price > relativeHigh)
            {
                continue;
            }

            if (Math.Abs(price - median) > limit)
            {
                continue;
            }

            if (price < low)
            {
                low = price;
            }

            if (price > high)
            {
                high = price;
            }
        }

        if (high == 0)
        {
            return (median, valid[0], valid[^1], valid.Count);
        }

        return (median, low, high, valid.Count);
    }

    /// <summary>把多个 SKU 的历史点按小时合并成型号走势。</summary>
    public static List<ModelPoint> AggregateByHour(IEnumerable<PricePoint> points, int minPrice = 1)
    {
        var buckets = new Dictionary<long, List<int>>();
        foreach (var point in points)
        {
            if (point.T <= 0 || point.P < minPrice)
            {
                continue;
            }

            var hour = point.T / 3600;
            if (!buckets.TryGetValue(hour, out var list))
            {
                list = [];
                buckets[hour] = list;
            }

            list.Add(point.P);
        }

        var result = new List<ModelPoint>(buckets.Count);
        foreach (var pair in buckets.OrderBy(p => p.Key))
        {
            var summary = Summarize(pair.Value);
            if (summary.Median > 0)
            {
                result.Add(new ModelPoint(pair.Key * 3600, summary.Median, summary.Low, summary.High, summary.Count));
            }
        }

        return result;
    }

    /// <summary>按小时合并型号价格点；dailyOnly 时同一天只保留一个点（未关注的型号）。</summary>
    public static void AddPoint(List<ModelPoint> points, ModelPoint point, bool dailyOnly = false)
    {
        if (point.T <= 0 || point.Median <= 0)
        {
            return;
        }

        var hour = point.T / 3600;
        if (points.Count > 0)
        {
            var last = points[^1];
            if (dailyOnly)
            {
                var lastDay = DateTimeOffset.FromUnixTimeSeconds(last.T).ToLocalTime().Date;
                var pointDay = DateTimeOffset.FromUnixTimeSeconds(point.T).ToLocalTime().Date;
                if (lastDay == pointDay)
                {
                    points[^1] = point;
                    return;
                }
            }
            else if (last.T / 3600 == hour)
            {
                points[^1] = point;
                return;
            }

            if (last.T > point.T)
            {
                return;
            }
        }

        points.Add(point);
        Compact(points, point.T);
    }

    private static void Compact(List<ModelPoint> points, long nowUnix)
    {
        if (points.Count < 100)
        {
            return;
        }

        var retentionCutoff = nowUnix - Catalog.HistoryRetentionDays * 86400L;
        var dayCutoff = nowUnix - Catalog.HourlyRetentionDays * 86400L;
        var keep = new List<ModelPoint>(points.Count);
        long currentDay = -1;
        foreach (var point in points)
        {
            if (point.T < retentionCutoff)
            {
                continue;
            }

            if (point.T >= dayCutoff)
            {
                keep.Add(point);
                continue;
            }

            var day = point.T / 86400;
            if (day == currentDay && keep.Count > 0)
            {
                keep[^1] = point;
            }
            else
            {
                keep.Add(point);
                currentDay = day;
            }
        }

        points.Clear();
        points.AddRange(keep);
    }

    private static int Median(IReadOnlyList<int> sorted)
    {
        var mid = sorted.Count / 2;
        if (sorted.Count % 2 == 1)
        {
            return sorted[mid];
        }

        return (int)Math.Round((sorted[mid - 1] + (long)sorted[mid]) / 2.0, MidpointRounding.AwayFromZero);
    }
}
