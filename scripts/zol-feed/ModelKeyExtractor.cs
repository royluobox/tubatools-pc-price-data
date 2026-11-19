using System.Text;
using System.Text.RegularExpressions;

namespace PcPriceTrend;

/// <summary>
/// 从厂商 SKU 名称里提取「型号」：显卡取芯片型号（RTX 5060）、CPU 取具体型号、
/// 主板取芯片组、内存取容量与频率；其余配件取去掉营销后缀的产品系列名。
/// 这样同一型号下所有品牌/散热器版本会聚合到一条走势。
/// </summary>
public static partial class ModelKeyExtractor
{
    public static (string Key, string Name) Extract(string rawName, string slug)
    {
        var name = CleanDisplay(rawName);
        if (name.Length == 0)
        {
            return ("UNKNOWN", "未知型号");
        }

        return slug switch
        {
            "vga" => ExtractGpu(name),
            "cpu" => ExtractCpu(name),
            "motherboard" => ExtractChipset(name),
            "memory" => ExtractMemory(name),
            "solid_state_drive" => ExtractSsd(name),
            "hard_drives" => ExtractHdd(name),
            "power" => ExtractPsu(name),
            "case" => ExtractCase(name),
            "cooling_product" => ExtractCooler(name),
            "lcd" => ExtractMonitor(name),
            "keyboard" => ExtractKeyboard(name),
            "mice" => ExtractMouse(name),
            _ => Fallback(name),
        };
    }

    /// <summary>把任意文本压成只含字母/数字的稳定键，用于搜索和去重。</summary>
    public static string NormalizeKey(string value)
    {
        var sb = new StringBuilder(value.Length);
        foreach (var ch in value.ToUpperInvariant())
        {
            if (char.IsLetterOrDigit(ch))
            {
                sb.Append(ch);
            }
        }

        return sb.Length == 0 ? "UNKNOWN" : sb.ToString();
    }

    private static (string Key, string Name) ExtractGpu(string name)
    {
        var upper = name.ToUpperInvariant();

        var match = RtxRegex().Match(upper);
        if (match.Success)
        {
            var number = match.Groups["num"].Value;
            var suffix = match.Groups["suffix"].Value;
            var isPro = match.Groups["pro"].Success;
            if (!isPro && suffix.Length == 0 && number == "6000" && upper.Contains("ADA", StringComparison.Ordinal))
            {
                suffix = "ADA";
            }

            var display = isPro ? $"RTX PRO {number}" : $"RTX {number}";
            if (suffix.Length > 0)
            {
                display += " " + TitleSuffix(suffix);
            }

            return (NormalizeKey(display), display);
        }

        match = RtxARegex().Match(upper);
        if (match.Success)
        {
            var display = "RTX " + match.Groups["model"].Value;
            return (NormalizeKey(display), display);
        }

        match = RxRegex().Match(upper);
        if (match.Success)
        {
            var display = "RX " + match.Groups["num"].Value;
            var suffix = match.Groups["suffix"].Value;
            if (suffix.Length > 0)
            {
                display += " " + TitleSuffix(suffix);
            }

            return (NormalizeKey(display), display);
        }

        match = RxVegaRegex().Match(upper);
        if (match.Success)
        {
            var display = "RX Vega " + match.Groups["num"].Value;
            return (NormalizeKey(display), display);
        }

        match = GtxRegex().Match(upper);
        if (match.Success)
        {
            var display = "GTX " + match.Groups["num"].Value;
            var suffix = match.Groups["suffix"].Value;
            if (suffix.Length > 0)
            {
                display += " " + TitleSuffix(suffix);
            }

            return (NormalizeKey(display), display);
        }

        match = GtRegex().Match(upper);
        if (match.Success)
        {
            var display = "GT " + match.Groups["num"].Value;
            return (NormalizeKey(display), display);
        }

        match = ArcRegex().Match(upper);
        if (match.Success)
        {
            var display = "Arc " + match.Groups["model"].Value;
            return (NormalizeKey(display), display);
        }

        match = TeslaRegex().Match(upper);
        if (match.Success)
        {
            var display = "Tesla " + match.Groups["model"].Value;
            return (NormalizeKey(display), display);
        }

        return Fallback(name);
    }

    private static (string Key, string Name) ExtractCpu(string name)
    {
        var upper = name.ToUpperInvariant();

        var match = IntelCoreRegex().Match(upper);
        if (match.Success)
        {
            var display = $"i{match.Groups["tier"].Value}-{match.Groups["num"].Value}{match.Groups["suffix"].Value}";
            return (NormalizeKey(display), display);
        }

        match = IntelUltraRegex().Match(upper);
        if (match.Success)
        {
            var display = $"Ultra {match.Groups["tier"].Value} {match.Groups["num"].Value}{match.Groups["suffix"].Value}";
            return (NormalizeKey(display), display);
        }

        match = RyzenRegex().Match(upper);
        if (match.Success)
        {
            var display = $"Ryzen {match.Groups["tier"].Value} {match.Groups["num"].Value}{match.Groups["suffix"].Value}";
            return (NormalizeKey(display), display);
        }

        match = ThreadripperRegex().Match(upper);
        if (match.Success)
        {
            var display = "Threadripper " + match.Groups["num"].Value;
            return (NormalizeKey(display), display);
        }

        return Fallback(name);
    }

    private static (string Key, string Name) ExtractChipset(string name)
    {
        var match = ChipsetRegex().Match(name.ToUpperInvariant());
        if (match.Success)
        {
            var display = match.Groups["chip"].Value;
            return (NormalizeKey(display), display);
        }

        return Fallback(name);
    }

    private static (string Key, string Name) ExtractMemory(string name)
    {
        var upper = name.ToUpperInvariant();
        var ddr = DdrRegex().Match(upper);
        if (!ddr.Success)
        {
            return Fallback(name);
        }

        var generation = "DDR" + ddr.Groups["gen"].Value;
        var capacity = 0;
        foreach (Match m in CapacityRegex().Matches(upper))
        {
            if (int.TryParse(m.Groups["v"].Value, out var value) && value > capacity && value <= 512)
            {
                capacity = value;
            }
        }

        foreach (Match m in KitForwardRegex().Matches(upper))
        {
            if (int.TryParse(m.Groups["a"].Value, out var a) &&
                int.TryParse(m.Groups["b"].Value, out var b) &&
                a > 0 && b > 0 && a * b > capacity && a * b <= 512)
            {
                capacity = a * b;
            }
        }

        foreach (Match m in KitReverseRegex().Matches(upper))
        {
            if (int.TryParse(m.Groups["a"].Value, out var a) &&
                int.TryParse(m.Groups["b"].Value, out var b) &&
                a > 0 && b > 0 && a * b > capacity && a * b <= 512)
            {
                capacity = a * b;
            }
        }

        var frequency = 0;
        var freqMatch = FrequencyRegex().Match(upper);
        if (freqMatch.Success && int.TryParse(freqMatch.Groups["v"].Value, out var mhz))
        {
            frequency = mhz;
        }

        var laptop = upper.Contains("笔记本", StringComparison.Ordinal) ||
                     upper.Contains("SO-DIMM", StringComparison.Ordinal) ||
                     upper.Contains("SODIMM", StringComparison.Ordinal);

        var display = generation;
        if (capacity > 0)
        {
            display += $" {capacity}G";
        }

        if (frequency > 0)
        {
            display += $" {frequency}";
        }

        if (laptop)
        {
            display += " 笔记本";
        }

        var key = NormalizeKey(display);
        return (key, display);
    }

    private static (string Key, string Name) ExtractSsd(string name)
    {
        var display = SsdNoiseRegex().Replace(name, " ");
        display = Collapse(display);
        return Fallback(display);
    }

    private static (string Key, string Name) ExtractHdd(string name)
    {
        var display = HddCodeRegex().Replace(name, " ");
        display = HddNoiseRegex().Replace(display, " ");
        display = Collapse(display);
        return Fallback(display);
    }

    private static (string Key, string Name) ExtractPsu(string name)
    {
        var display = Collapse(name.Replace("电源", " ", StringComparison.Ordinal));
        return Fallback(display);
    }

    private static (string Key, string Name) ExtractCase(string name)
    {
        var display = name.Replace("机箱", " ", StringComparison.Ordinal)
            .Replace("黑色", " ", StringComparison.Ordinal)
            .Replace("白色", " ", StringComparison.Ordinal);
        return Fallback(Collapse(display));
    }

    private static (string Key, string Name) ExtractCooler(string name)
    {
        var display = name.Replace("散热器", " ", StringComparison.Ordinal)
            .Replace("ARGB", " ", StringComparison.OrdinalIgnoreCase)
            .Replace("RGB", " ", StringComparison.OrdinalIgnoreCase)
            .Replace("青春版", " ", StringComparison.Ordinal)
            .Replace("纪念版", " ", StringComparison.Ordinal)
            .Replace("白色", " ", StringComparison.Ordinal)
            .Replace("黑色", " ", StringComparison.Ordinal);
        return Fallback(Collapse(display));
    }

    private static (string Key, string Name) ExtractMonitor(string name)
    {
        var display = Collapse(name.Replace("显示器", " ", StringComparison.Ordinal));
        return Fallback(display);
    }

    private static (string Key, string Name) ExtractKeyboard(string name)
    {
        var display = Collapse(name.Replace("键盘", " ", StringComparison.Ordinal));
        return Fallback(display);
    }

    private static (string Key, string Name) ExtractMouse(string name)
    {
        var display = name.Replace("游戏鼠标", "", StringComparison.Ordinal)
            .Replace("鼠标", "", StringComparison.Ordinal);
        return Fallback(Collapse(display));
    }

    /// <summary>兜底：去掉泛化的分类词，保留产品系列名。</summary>
    private static (string Key, string Name) Fallback(string name)
    {
        var display = GenericNoiseRegex().Replace(name, " ");
        display = Collapse(display);
        if (display.Length == 0)
        {
            display = "未知型号";
        }

        return (NormalizeKey(display), display);
    }

    private static string TitleSuffix(string suffix) => suffix.ToUpperInvariant() switch
    {
        "TI" => "Ti",
        "SUPER" => "Super",
        "ADA" => "Ada",
        _ => suffix.ToUpperInvariant(),
    };

    private static string CleanDisplay(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return "";
        }

        var text = raw.Normalize(NormalizationForm.FormKC)
            .Replace('\u00A0', ' ')
            .Replace("\u200B", "", StringComparison.Ordinal);
        text = Collapse(text);
        return text.Length > 80 ? text[..80].TrimEnd() : text;
    }

    private static string Collapse(string value)
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

        return sb.ToString().Trim(' ', '-', '—', '/', '·', '|');
    }

    [GeneratedRegex(@"RTX\s?(?<pro>PRO\s?)?(?<num>\d{4})(?:\s?(?<suffix>TI|SUPER))?", RegexOptions.IgnoreCase)]
    private static partial Regex RtxRegex();

    [GeneratedRegex(@"RTX\s?(?<model>A\d{4})", RegexOptions.IgnoreCase)]
    private static partial Regex RtxARegex();

    [GeneratedRegex(@"RX\s?(?<num>\d{3,4})(?:\s?(?<suffix>XTX|XT|GRE))?", RegexOptions.IgnoreCase)]
    private static partial Regex RxRegex();

    [GeneratedRegex(@"RX\s?VEGA\s?(?<num>\d{2})", RegexOptions.IgnoreCase)]
    private static partial Regex RxVegaRegex();

    [GeneratedRegex(@"GTX\s?(?<num>\d{3,4})(?:\s?(?<suffix>TI|SUPER))?", RegexOptions.IgnoreCase)]
    private static partial Regex GtxRegex();

    [GeneratedRegex(@"GT\s?(?<num>\d{3,4})", RegexOptions.IgnoreCase)]
    private static partial Regex GtRegex();

    [GeneratedRegex(@"(?:ARC|锐炫)\s?(?<model>[AB]\d{3})", RegexOptions.IgnoreCase)]
    private static partial Regex ArcRegex();

    [GeneratedRegex(@"TESLA\s?(?<model>[A-Z]\d{2,4})", RegexOptions.IgnoreCase)]
    private static partial Regex TeslaRegex();

    [GeneratedRegex(@"\bI(?<tier>[3579])[\s-]?(?<num>\d{4,5})(?<suffix>[A-Z]{0,2})\b", RegexOptions.IgnoreCase)]
    private static partial Regex IntelCoreRegex();

    [GeneratedRegex(@"ULTRA\s?(?<tier>[3579])\s?(?<num>\d{3})(?<suffix>[A-Z]{0,2})\b", RegexOptions.IgnoreCase)]
    private static partial Regex IntelUltraRegex();

    [GeneratedRegex(@"(?:RYZEN|R)\s?(?<tier>[3579])[\s-]?(?<num>\d{4})(?<suffix>[A-Z0-9]{0,4})\b", RegexOptions.IgnoreCase)]
    private static partial Regex RyzenRegex();

    [GeneratedRegex(@"THREADRIPPER\s?(?<num>\d{4}[A-Z]{0,4})\b", RegexOptions.IgnoreCase)]
    private static partial Regex ThreadripperRegex();

    [GeneratedRegex(@"(?<![A-Z0-9])(?<chip>[HBAZX]\d{2,3}[A-Z]{0,2})(?![A-Z0-9])", RegexOptions.IgnoreCase)]
    private static partial Regex ChipsetRegex();

    [GeneratedRegex(@"DDR\s?(?<gen>[345])", RegexOptions.IgnoreCase)]
    private static partial Regex DdrRegex();

    [GeneratedRegex(@"(?<v>\d{1,3})\s*GB", RegexOptions.IgnoreCase)]
    private static partial Regex CapacityRegex();

    [GeneratedRegex(@"(?<a>\d{1,2})\s*GB?\s*[×X*]\s*(?<b>\d{1,2})", RegexOptions.IgnoreCase)]
    private static partial Regex KitForwardRegex();

    [GeneratedRegex(@"(?<a>\d{1,2})\s*[×X*]\s*(?<b>\d{1,3})\s*GB?", RegexOptions.IgnoreCase)]
    private static partial Regex KitReverseRegex();

    [GeneratedRegex(@"\b(?<v>2(?:1[3-9]\d|[2-9]\d{2})|[3-8]\d{3})\b", RegexOptions.IgnoreCase)]
    private static partial Regex FrequencyRegex();

    [GeneratedRegex(@"\b(?:NVME|M\.2|SATA(?:3(?:\.0)?)?|PCIE\s?[345]\.0|SSD)\b", RegexOptions.IgnoreCase)]
    private static partial Regex SsdNoiseRegex();

    [GeneratedRegex(@"[（(][A-Z0-9][A-Z0-9\-]{3,}[）)]", RegexOptions.IgnoreCase)]
    private static partial Regex HddCodeRegex();

    [GeneratedRegex(@"(?:SATA3?|\d+转|\d+MB|机械硬盘|硬盘)", RegexOptions.IgnoreCase)]
    private static partial Regex HddNoiseRegex();

    [GeneratedRegex(@"(?:显卡|主板|内存条|固态硬盘|机械硬盘|电源|机箱|散热器|显示器|键盘|鼠标)", RegexOptions.IgnoreCase)]
    private static partial Regex GenericNoiseRegex();
}
