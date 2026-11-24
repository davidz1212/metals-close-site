"""从免费公开源生成指定报告日的真实快照 + 配套数据集。

数据源（全部为公开免费来源）：
  - Yahoo Finance（GC=F / SI=F / GDX / SIL / CNY=X / INR=X）：主行情、涨跌、金银比、矿股、汇率（日线）
  - 上海黄金交易所 SGE 官网：每日行情（Au99.99 / Ag(T+D) 收盘价）与行情周报 PDF（白银指定仓库库存，周度）
  - 印度金银珠宝协会 IBJA 官网（ibjarates.com）：PM 午盘黄金 999 / 白银 999 基准价（不含 GST，日度）
  - 上海期货交易所 SHFE 官网：白银期货仓单日报 / 库存周报（总计库存与变动，日度/周度）
  - MetalCharts.org 免费 CSV（署名许可）：COMEX 金/银注册与合格仓单库存（周度）、上海白银溢价（周度均值）
  - CFTC 官方公开数据 API（publicreporting.cftc.gov）：COT 分类持仓报告 COMEX 白银总持仓量（周度）
  - LBMA London Vault Holdings（随 curves.json）：伦敦金库白银库存（月度）

口径说明：GC=F / SI=F 为 COMEX 连续期货日线，非 TradingView TVC 现货口径；
本脚本生成的快照 mode=REAL，与 P0 样例（mode=MOCK，转录自参考图）不可混用。
凡是免费源无法提供的字段（如 CME 交割通知 PDF，官网启用反爬拦截）一律标 unavailable，绝不填占位数字。

用法：
    python tools/build_daily_snapshot.py --date 2026-11-20
产出（写入 data/seed，带日期前缀，由 ingest.py 入库）：
    YYYY-MM-DD.json
    YYYY-MM-DD.ratio-percentile.json
    YYYY-MM-DD.ratio-history.json
    YYYY-MM-DD.curves.json
    YYYY-MM-DD.close-verification.json
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import certifi  # type: ignore
except ImportError:  # pragma: no cover
    certifi = None

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    pymupdf = None

try:
    from pypdf import PdfReader  # type: ignore
except ImportError:  # pragma: no cover
    PdfReader = None

SSL_CTX = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "seed"
CACHE = ROOT / "data" / "cache"
CME_DIR = ROOT / "data" / "cme"
TZ8 = dt.timezone(dt.timedelta(hours=8))
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
GRAMS_PER_OZ = 31.1034768
KG_PER_MOZ = 31103.4768  # 1,000,000 troy oz in kg

# metalcharts.org 免费 CSV（许可：可用于网站，须在页面放可见署名链接）
FREE_CSVS = {
    "comex": "https://metalcharts.org/data/comex-gold-silver-registered-eligible-weekly.csv",
    "shanghai": "https://metalcharts.org/data/shanghai-silver-premium-weekly.csv",
}
CREDIT = "MetalCharts.org"


def http_get(url: str, headers: dict | None = None, timeout: int = 25) -> bytes:
    h = dict(UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read()


def http_post(url: str, data: dict, headers: dict | None = None, timeout: int = 25) -> bytes:
    h = dict(UA)
    if headers:
        h.update(headers)
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read()


def load_csv(name: str, refresh: bool = False) -> list[dict]:
    """优先使用新鲜缓存（12 小时内）；过期或缺失时重新下载并写入 data/cache，离线时回退旧缓存。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.csv"
    stale = True
    if path.exists() and path.stat().st_size > 100:
        age = time.time() - path.stat().st_mtime
        stale = refresh or age > 12 * 3600
    text = None
    if stale:
        try:
            text = http_get(FREE_CSVS[name], timeout=35).decode("utf-8-sig")
            path.write_text(text, encoding="utf-8")
        except Exception as exc:
            print(f"WARN: refresh {name} CSV failed ({exc}); falling back to cache")
    if text is None:
        if path.exists() and path.stat().st_size > 100:
            text = path.read_text(encoding="utf-8-sig")
        else:
            return []
    return list(csv.DictReader(io.StringIO(text)))


def csv_on_or_before(rows: list[dict], key: str, date: str) -> dict | None:
    """按日期列取不晚于 date 的最后一行（CSV 须按日期升序）。"""
    hit = None
    for r in rows:
        if r.get(key, "") and r[key] <= date:
            hit = r
        else:
            break
    return hit


def fetch_chart(symbol: str, rng: str = "10y") -> list[dict]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
        f"?range={rng}&interval=1d"
    )
    data = json.loads(http_get(url, timeout=35).decode("utf-8"))["chart"]["result"][0]
    ts = data["timestamp"]
    q = data["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        day = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")
        out.append({
            "date": day,
            "close": float(c),
            "high": float(q["high"][i]) if q.get("high") and q["high"][i] else float(c),
            "low": float(q["low"][i]) if q.get("low") and q["low"][i] else float(c),
        })
    return out


def fetch_sge_daily(report_date: str) -> dict | None:
    """从上海黄金交易所官网抓取指定日期（若遇节假日向前回溯最多 5 天）的 Au99.99 与 Ag(T+D) 收盘价。"""
    base = dt.date.fromisoformat(report_date)
    hdrs = {"Referer": "https://www.sge.com.cn/sjzx/mrhq", "X-Requested-With": "XMLHttpRequest"}
    for offset in range(6):
        d = (base - dt.timedelta(days=offset)).isoformat()
        try:
            html = http_post("https://www.sge.com.cn/sjzx/mrhq_data", {"date": d}, headers=hdrs, timeout=20).decode("utf-8", errors="ignore")
        except Exception as exc:
            print(f"WARN: SGE daily fetch failed for {d}: {exc}")
            return None
        au_close = ag_close = None
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            cells = [
                re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            ]
            if len(cells) < 3:
                continue
            code = cells[0]
            try:
                close_val = float(cells[2].replace(",", ""))
            except ValueError:
                continue
            if code == "Au99.99":
                au_close = close_val  # CNY / g
            elif code == "Ag(T+D)":
                ag_close = close_val  # CNY / kg
        if au_close is not None or ag_close is not None:
            return {"as_of": d, "au_cny_g": au_close, "ag_cny_kg": ag_close}
    return None


def fetch_ibja_pm(report_date: str) -> dict | None:
    """从 IBJA 官网首页解析 PM 午盘基准价（Gold 999 INR/10g，Silver 999 INR/kg，不含 GST）。"""
    try:
        html = http_get("https://ibjarates.com/", timeout=25).decode("utf-8", errors="ignore")
    except Exception as exc:
        print(f"WARN: IBJA fetch failed: {exc}")
        return None
    tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.S)
    # 首页两张历史表：第一张 AM，第二张 PM；匹配含 Silver 999 的表格，优先取最后一张（PM）
    candidates = []
    for tb in tables:
        rows = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S):
            cells = [
                re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            ]
            if cells:
                rows.append(cells)
        if any("Silver 999" in " ".join(r) for r in rows):
            candidates.append(rows)
    if not candidates:
        return None
    pm_rows = candidates[-1]
    parsed = []
    for r in pm_rows:
        if len(r) >= 7 and re.match(r"^\d{2}/\d{2}/\d{4}$", r[0]):
            dd, mm, yyyy = r[0].split("/")
            iso = f"{yyyy}-{mm}-{dd}"
            try:
                gold_999_10g = float(r[1].replace(",", ""))
                silver_999_kg = float(r[6].replace(",", ""))
                parsed.append({"as_of": iso, "gold_inr_10g": gold_999_10g, "silver_inr_kg": silver_999_kg})
            except ValueError:
                continue
    parsed.sort(key=lambda x: x["as_of"])
    # 仅使用不晚于 report_date 且间隔 <= 5 天的记录，避免把未来日期误配到旧报告日
    target = dt.date.fromisoformat(report_date)
    hit = None
    for item in parsed:
        if item["as_of"] <= report_date:
            gap = (target - dt.date.fromisoformat(item["as_of"])).days
            if gap <= 5:
                hit = item
    return hit


def fetch_shfe_silver_stock(report_date: str) -> dict | None:
    """从上期所官网抓取白银仓单日报/周报总计（含保税，单位 kg -> 折算 Moz）。"""
    base = dt.date.fromisoformat(report_date)
    hdrs = {"Referer": "https://www.shfe.com.cn/reports/tradedata/dailyandweeklydata/"}

    def _parse_total(html: str, is_weekly: bool) -> tuple[float, float] | None:
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            cells = [
                re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            ]
            if cells and cells[0] == "总计":
                try:
                    if is_weekly and len(cells) >= 4:
                        # ['总计', 上周期货, 本周期货, 增减, ...]
                        return float(cells[2].replace(",", "")), float(cells[3].replace(",", ""))
                    if not is_weekly and len(cells) >= 3:
                        # ['总计', 期货, 增减]
                        return float(cells[1].replace(",", "")), float(cells[2].replace(",", ""))
                except ValueError:
                    return None
        return None

    for offset in range(6):
        d_obj = base - dt.timedelta(days=offset)
        ymd = d_obj.strftime("%Y%m%d")
        iso = d_obj.isoformat()
        # 优先尝试周五周报（与原表 "-1.16w" 周变动口径一致），否则取仓单日报
        if d_obj.weekday() == 4:
            try:
                whtml = http_get(
                    f"https://www.shfe.com.cn/data/tradedata/future/stockdata/weeklystock_{ymd}/ZH/shfe/ag.html",
                    headers=hdrs,
                    timeout=15,
                ).decode("utf-8", errors="ignore")
                res = _parse_total(whtml, is_weekly=True)
                if res:
                    total_kg, chg_kg = res
                    return {
                        "as_of": iso,
                        "total_moz": total_kg / KG_PER_MOZ,
                        "chg_moz": chg_kg / KG_PER_MOZ,
                        "freq": "w",
                    }
            except Exception:
                pass
        try:
            dhtml = http_get(
                f"https://www.shfe.com.cn/data/tradedata/future/stockdata/dailystock_{ymd}/ZH/shfe/ag.html",
                headers=hdrs,
                timeout=15,
            ).decode("utf-8", errors="ignore")
            res = _parse_total(dhtml, is_weekly=False)
            if res:
                total_kg, chg_kg = res
                return {
                    "as_of": iso,
                    "total_moz": total_kg / KG_PER_MOZ,
                    "chg_moz": chg_kg / KG_PER_MOZ,
                    "freq": "d",
                }
        except Exception:
            continue
    return None


def fetch_sge_silver_vault(report_date: str) -> dict | None:
    """从上金所官网《行情周报》PDF 解析指定仓库白银库存（千克 -> Moz）。"""
    if pymupdf is None and PdfReader is None:
        return None
    try:
        idx_html = http_get("https://www.sge.com.cn/sjzx/hqzb", timeout=20).decode("utf-8", errors="ignore")
    except Exception as exc:
        print(f"WARN: SGE hqzb index failed: {exc}")
        return None
    items = re.findall(
        r'href="(/sjzx/hqzb/\d+)"[^>]*>.*?<span[^>]*>([^<]+)</span>.*?<span[^>]*>(\d{4}-\d{2}-\d{2})</span>',
        idx_html,
        re.S,
    )
    # 选取发布日期 <= report_date 的最新一期周报
    chosen = None
    for href, title, pub_date in items:
        if pub_date <= report_date:
            chosen = (href, title.strip(), pub_date)
            break
    if not chosen:
        return None
    href, title, pub_date = chosen
    try:
        detail_html = http_get("https://www.sge.com.cn" + href, timeout=20).decode("utf-8", errors="ignore")
        pdfs = re.findall(r'["\'](https?://[^"\']+\.pdf|/upload/[^"\']+\.pdf)["\']', detail_html, re.I)
        if not pdfs:
            return None
        pdf_url = pdfs[0] if pdfs[0].startswith("http") else "https://www.sge.com.cn" + pdfs[0]
        pdf_bytes = http_get(pdf_url, timeout=25)
        if pymupdf is not None:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            full_text = "\n".join(page.get_text() for page in doc)
        else:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            full_text = "\n".join((page.extract_text() or "") for page in reader.pages)
        # 兼容 pymupdf（换行分隔）与 pypdf（空格分隔）
        m = re.search(
            r"本周库存\s+白银\s+([\d,]+\.\d+)\s+([-\d,]+\.\d+)\s+([\d,]+\.\d+)",
            full_text,
        )
        if not m:
            return None
        prev_kg = float(m.group(1).replace(",", ""))
        chg_kg = float(m.group(2).replace(",", ""))
        cur_kg = float(m.group(3).replace(",", ""))
        return {
            "as_of": pub_date,
            "title": title,
            "url": pdf_url,
            "total_moz": cur_kg / KG_PER_MOZ,
            "prev_moz": prev_kg / KG_PER_MOZ,
            "chg_moz": chg_kg / KG_PER_MOZ,
        }
    except Exception as exc:
        print(f"WARN: SGE weekly PDF parse failed: {exc}")
        return None


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    if pymupdf is not None:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    if PdfReader is not None:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    return ""


def _fmt_oz(oz: float) -> str:
    if oz >= 1_000_000:
        return f"{oz / 1e6:.2f}M oz"
    if oz >= 1_000:
        return f"{oz / 1e3:.0f}K oz"
    return f"{oz:.0f} oz"


def load_local_cme_notices(report_date: str) -> dict | None:
    """从 data/cme/*.pdf 自动解析浏览器手动下载的 CME 交割通知报表。
    同时兼容：
      - DLV635-T（MetalsIssuesAndStopsMTDReport.pdf）：按日列出当月每日 DAILY TOTAL 与 CUMULATIVE，一份文件可覆盖整月各交易日；
      - DLV615-T（MetalsIssuesAndStopsReport.pdf）：单日交割明细，含 TOTAL 与 MONTH TO DATE。
    """
    if not CME_DIR.is_dir() or (pymupdf is None and PdfReader is None):
        return None
    target = dt.date.fromisoformat(report_date)
    best: dict | None = None
    for pdf_path in sorted(CME_DIR.glob("*.pdf")):
        try:
            text = _extract_pdf_text(pdf_path.read_bytes())
        except Exception as exc:
            print(f"WARN: failed to read CME PDF {pdf_path.name}: {exc}")
            continue
        if not text or "COMEX 5000 SILVER" not in text.upper():
            continue
        sec_m = re.search(
            r"COMEX\s+5000\s+SILVER\s+FUTURES(.*?)(?=EXCHANGE:|CONTRACT:|COMEX\s+\d+|NYMEX\s+|MICRO\s+SILVER|\Z)",
            text,
            re.I | re.S,
        )
        if not sec_m:
            continue
        sec = sec_m.group(1)

        # 1) 优先匹配 DLV635-T（MTD 按日表：MM/DD/YYYY   DAILY   CUMULATIVE）
        mtd_rows = re.findall(r"(\d{2}/\d{2}/\d{4})\s+([\d,]+)\s+([\d,]+)", sec)
        if mtd_rows:
            for d_str, daily_s, cum_s in mtd_rows:
                mm, dd, yyyy = d_str.split("/")
                iso = f"{yyyy}-{mm}-{dd}"
                gap = (target - dt.date.fromisoformat(iso)).days
                if gap < 0 or gap > 14:
                    continue
                daily_c = int(daily_s.replace(",", ""))
                cum_c = int(cum_s.replace(",", ""))
                cand = {
                    "as_of": iso,
                    "file": pdf_path.name,
                    "daily_oz": daily_c * 5000,
                    "mtd_oz": cum_c * 5000,
                    "daily_contracts": daily_c,
                    "mtd_contracts": cum_c,
                }
                if best is None or cand["as_of"] > best["as_of"]:
                    best = cand
            continue

        # 2) 回退匹配 DLV615-T（单日明细：TOTAL + MONTH TO DATE）
        date_iso = None
        for pat in (r"INTENT\s+DATE:\s*(\d{2}/\d{2}/\d{4})", r"BUSINESS\s+DATE:\s*(\d{2}/\d{2}/\d{4})"):
            dm = re.search(pat, sec, re.I) or re.search(pat, text, re.I)
            if dm:
                mm, dd, yyyy = dm.group(1).split("/")
                date_iso = f"{yyyy}-{mm}-{dd}"
                break
        if not date_iso:
            continue
        gap = (target - dt.date.fromisoformat(date_iso)).days
        if gap < 0 or gap > 14:
            continue
        daily_m = re.search(r"TOTAL:\s*([\d,]+)", sec, re.I)
        mtd_m = re.search(r"MONTH\s+TO\s+DATE:\s*([\d,]+)", sec, re.I)
        daily_c = int(daily_m.group(1).replace(",", "")) if daily_m else None
        mtd_c = int(mtd_m.group(1).replace(",", "")) if mtd_m else None
        if daily_c is None and mtd_c is None:
            continue
        cand = {
            "as_of": date_iso,
            "file": pdf_path.name,
            "daily_oz": daily_c * 5000 if daily_c is not None else None,
            "mtd_oz": mtd_c * 5000 if mtd_c is not None else None,
            "daily_contracts": daily_c,
            "mtd_contracts": mtd_c,
        }
        if best is None or cand["as_of"] > best["as_of"]:
            best = cand
    return best


def fetch_cftc_silver_oi(report_date: str) -> dict | None:
    """从 CFTC 官方公开数据 API（Socrata）抓取 COMEX 白银总持仓量（张 × 5,000 oz -> Moz）。"""
    q = urllib.parse.quote("market_and_exchange_names='SILVER - COMMODITY EXCHANGE INC.'")
    url = (
        f"https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
        f"?$where={q}&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=60"
    )
    try:
        rows = json.loads(http_get(url, timeout=25).decode("utf-8"))
    except Exception as exc:
        print(f"WARN: CFTC API fetch failed: {exc}")
        return None
    pts = []
    for r in rows:
        d = (r.get("report_date_as_yyyy_mm_dd") or "")[:10]
        oi_raw = r.get("open_interest_all")
        if not d or oi_raw is None or d > report_date:
            continue
        oi_contracts = float(oi_raw)
        pts.append({"label": d, "value": round(oi_contracts * 5000.0 / 1e6, 2), "contracts": int(oi_contracts)})
    if not pts:
        return None
    pts.sort(key=lambda x: x["label"])
    return {"latest": pts[-1], "points": pts[-52:]}


def idx_on_or_before(rows: list[dict], date: str) -> int | None:
    idx = None
    for i, r in enumerate(rows):
        if r["date"] <= date:
            idx = i
        else:
            break
    return idx


def nearest_on_or_before(rows: list[dict], date: str) -> dict | None:
    i = idx_on_or_before(rows, date)
    return rows[i] if i is not None else None


def years_before(date: str, n: int) -> str:
    d = dt.date.fromisoformat(date)
    try:
        return d.replace(year=d.year - n).isoformat()
    except ValueError:  # 2/29
        return d.replace(year=d.year - n, day=28).isoformat()


def pct(new: float, old: float) -> float:
    return (new / old - 1) * 100.0


def fmt_pct(v: float, with_sign=True) -> str:
    sign = "+" if v >= 0 else ""
    return (sign if with_sign else "") + f"{v:.2f}%"


def fmt_usd(v: float, dec=3, sign=False) -> str:
    s = ("+" if v >= 0 else "") if sign else ("-" if v < 0 else "")
    return s + "$" + f"{abs(v):,.{dec}f}"


def direction(v: float) -> str:
    return "up" if v >= 0 else "down"


def percentile_rank(values: list[float], current: float) -> float:
    below = sum(1 for v in values if v < current)
    ties = sum(1 for v in values if v == current)
    return round(100.0 * (below + 0.5 * ties) / len(values), 1)


def q(vals: list[float], p: float) -> float:
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="auto", help="报告日 YYYY-MM-DD，或 auto 自动取最新已收盘交易日")
    ap.add_argument("--source-dir", default=str(SEED))
    ap.add_argument("--refresh-cache", action="store_true", help="强制刷新本地 CSV 缓存")
    ap.add_argument("--ingest", action="store_true", help="生成快照后立即写入 SQLite 数据库")
    args = ap.parse_args()
    seed = Path(args.source_dir)
    seed.mkdir(parents=True, exist_ok=True)

    # ---- 1. Yahoo Finance：主行情、矿股（2y 确保 1 年比值可算）、汇率 ----
    gc = fetch_chart("GC=F", "10y")
    si = fetch_chart("SI=F", "10y")
    gdx = fetch_chart("GDX", "2y")
    sil = fetch_chart("SIL", "2y")
    usdcny_rows = fetch_chart("CNY=X", "2y")
    usdinr_rows = fetch_chart("INR=X", "2y")

    if args.date.strip().lower() == "auto":
        common_dates = sorted(
            {r["date"] for r in gc}
            & {r["date"] for r in si}
            & {r["date"] for r in gdx}
            & {r["date"] for r in sil}
        )
        if not common_dates:
            print("ERROR: 无法从 Yahoo Finance 确定最新公共交易日")
            return 1
        report_date = common_dates[-1]
    else:
        report_date = args.date.strip()

    ig, isi = idx_on_or_before(gc, report_date), idx_on_or_before(si, report_date)
    igx, isx = idx_on_or_before(gdx, report_date), idx_on_or_before(sil, report_date)
    if None in (ig, isi, igx, isx) or gc[ig]["date"] != report_date or si[isi]["date"] != report_date:
        print(
            f"ERROR: {report_date} 不是有效收盘交易日（GC={gc[ig]['date'] if ig is not None else None} "
            f"SI={si[isi]['date'] if isi is not None else None}）"
        )
        return 1

    G, S = gc[ig], si[isi]
    Gp, Sp = gc[ig - 1], si[isi - 1]
    cny_row = nearest_on_or_before(usdcny_rows, report_date)
    inr_row = nearest_on_or_before(usdinr_rows, report_date)
    usdcny = cny_row["close"] if cny_row else None
    usdinr = inr_row["close"] if inr_row else None

    # ---- 2. MetalCharts.org 免费 CSV：COMEX 仓单 + 上海白银溢价周度均值 ----
    comex_rows = load_csv("comex", refresh=args.refresh_cache)
    sh_rows = load_csv("shanghai", refresh=args.refresh_cache)
    comex_ag = [r for r in comex_rows if r.get("metal") == "silver"]
    d = dt.date.fromisoformat(report_date)
    ago7, ago30 = (d - dt.timedelta(days=7)).isoformat(), (d - dt.timedelta(days=30)).isoformat()
    cag_now = csv_on_or_before(comex_ag, "report_date", report_date)
    cag_wk = csv_on_or_before(comex_ag, "report_date", ago7)
    cag_d30 = csv_on_or_before(comex_ag, "report_date", ago30)
    sh_now = csv_on_or_before(sh_rows, "week_start", report_date)
    sh_prev4 = [r for r in sh_rows if r["week_start"] <= report_date][-4:]

    def _moz(row, col):
        return float(row[col]) / 1e6 if row else None

    reg = _moz(cag_now, "registered_oz")
    reg_wk = _moz(cag_wk, "registered_oz")
    reg_d30 = _moz(cag_d30, "registered_oz")
    elig = _moz(cag_now, "eligible_oz")
    elig_wk = _moz(cag_wk, "eligible_oz")
    elig_d30 = _moz(cag_d30, "eligible_oz")
    mc_sh_usd = float(sh_now["shanghai_avg_usd_per_oz"]) if sh_now else None
    mc_sh_prem = float(sh_now["premium_avg_pct"]) if sh_now else None
    mc_sh_asof = sh_now["week_start"] if sh_now else None
    prem4 = (sum(float(r["premium_avg_pct"]) for r in sh_prev4) / len(sh_prev4)) if sh_prev4 else None

    # ---- 3. 官方免费源：SGE 日行情、IBJA 印度午盘、SHFE 仓单、SGE 库存周报、CFTC COT、本地 CME PDF ----
    sge_daily = fetch_sge_daily(report_date)
    ibja_pm = fetch_ibja_pm(report_date)
    shfe_stock = fetch_shfe_silver_stock(report_date)
    sge_vault = fetch_sge_silver_vault(report_date)
    cftc_oi = fetch_cftc_silver_oi(report_date)
    cme_notices = load_local_cme_notices(report_date)

    # 上海黄金/白银本地价（优先用 SGE 官网日收盘 + USD/CNY；白银缺失时回退 MetalCharts 周度）
    sh_au_usd = sh_au_prem = sh_au_asof = None
    sh_ag_usd = sh_ag_prem = sh_ag_asof = sh_ag_src = None
    if sge_daily and usdcny:
        if sge_daily.get("au_cny_g"):
            sh_au_usd = sge_daily["au_cny_g"] * GRAMS_PER_OZ / usdcny
            sh_au_prem = pct(sh_au_usd, G["close"])
            sh_au_asof = sge_daily["as_of"]
        if sge_daily.get("ag_cny_kg"):
            sh_ag_usd = (sge_daily["ag_cny_kg"] / 1000.0) * GRAMS_PER_OZ / usdcny
            sh_ag_prem = pct(sh_ag_usd, S["close"])
            sh_ag_asof = sge_daily["as_of"]
            sh_ag_src = "上海黄金交易所 Ag(T+D) 收盘价 + Yahoo CNY=X"
    if sh_ag_usd is None and mc_sh_usd is not None:
        sh_ag_usd, sh_ag_prem, sh_ag_asof = mc_sh_usd, mc_sh_prem, f"{mc_sh_asof} week avg"
        sh_ag_src = f"SGE-linked 现货 / {CREDIT}（周度 CSV）"

    # 印度黄金/白银本地价（IBJA 官网 PM 基准价不含 GST + USD/INR）
    in_au_usd = in_au_prem = in_ag_usd = in_ag_prem = in_asof = None
    if ibja_pm and usdinr:
        in_asof = ibja_pm["as_of"]
        in_au_usd = (ibja_pm["gold_inr_10g"] / 10.0) * GRAMS_PER_OZ / usdinr
        in_au_prem = pct(in_au_usd, G["close"])
        in_ag_usd = (ibja_pm["silver_inr_kg"] / 1000.0) * GRAMS_PER_OZ / usdinr
        in_ag_prem = pct(in_ag_usd, S["close"])

    # COMEX 持仓量 / 注册库存比（CFTC COT 周度总持仓 ÷ COMEX 注册库存）
    oi_moz = cftc_oi["latest"]["value"] if cftc_oi else None
    oi_asof = cftc_oi["latest"]["label"] if cftc_oi else None
    oi_to_reg = (oi_moz / reg) if (oi_moz and reg) else None
    reg_to_oi = (reg / oi_moz * 100.0) if (oi_moz and reg) else None

    # ---- 4. LBMA 金库库存（从共享 curves.json 读取，并同步刷新 delivery 曲线）----
    curves_src = seed / "curves.json"
    curves = json.loads(curves_src.read_text(encoding="utf-8")) if curves_src.exists() else None
    lbma_cur = lbma_prev = lbma_asof = lbma_prev_label = None
    fetched = dt.datetime.now(TZ8).isoformat(timespec="seconds")
    if curves:
        curves = dict(curves)
        curves["retrieved_at"] = fetched
        _vpts = curves.get("vault", {}).get("points", [])
        if len(_vpts) >= 2:
            lbma_cur = _vpts[-1]["value"]
            lbma_prev = _vpts[-2]["value"]
            lbma_asof = _vpts[-1]["label"]
            lbma_prev_label = _vpts[-2]["label"]
        if cftc_oi and len(cftc_oi["points"]) >= 10:
            dpts = [{"label": p["label"], "value": p["value"]} for p in cftc_oi["points"]]
            vals = [p["value"] for p in dpts]
            min_p = min(dpts, key=lambda x: x["value"])
            max_p = max(dpts, key=lambda x: x["value"])
            chg_v = round(dpts[-1]["value"] - dpts[0]["value"], 2)
            chg_p = round(pct(dpts[-1]["value"], dpts[0]["value"]), 2)
            curves["delivery"] = {
                "title": "COMEX 白银期货总持仓量 · 周度变化",
                "unit": "Moz",
                "source": "CFTC COT / Disaggregated, SILVER - COMMODITY EXCHANGE INC.",
                "source_url": "https://publicreporting.cftc.gov/resource/72hh-3qpy.json",
                "as_of": dpts[-1]["label"],
                "retrieved_at": fetched,
                "caliber": "Open_Interest_All（合约张数）× 5,000 盎司/张折算为百万盎司；CFTC 周二快照",
                "stats": {
                    "window": f"近 {len(dpts)} 周",
                    "period": f"{len(dpts)} 周",
                    "count": len(dpts),
                    "first_label": dpts[0]["label"],
                    "last_label": dpts[-1]["label"],
                    "first": dpts[0]["value"],
                    "current": dpts[-1]["value"],
                    "change": chg_v,
                    "change_pct": chg_p,
                    "min": min_p["value"],
                    "max": max_p["value"],
                    "min_label": min_p["label"],
                    "max_label": max_p["label"],
                },
                "points": dpts,
            }

    # ---- 5. 涨跌、金银比、矿股比价 ----
    ago90 = (d - dt.timedelta(days=90)).isoformat()
    ago180 = (d - dt.timedelta(days=180)).isoformat()
    Gw = nearest_on_or_before(gc, ago7)
    Gm = nearest_on_or_before(gc, ago30)
    Gq = nearest_on_or_before(gc, ago90)
    Gh = nearest_on_or_before(gc, ago180)
    Sw = nearest_on_or_before(si, ago7)
    Sm = nearest_on_or_before(si, ago30)
    Sq = nearest_on_or_before(si, ago90)
    Sh = nearest_on_or_before(si, ago180)
    Gy = nearest_on_or_before(gc, years_before(report_date, 1))
    Sy = nearest_on_or_before(si, years_before(report_date, 1))

    g_day, s_day = pct(G["close"], Gp["close"]), pct(S["close"], Sp["close"])
    g_week, s_week = pct(G["close"], Gw["close"]), pct(S["close"], Sw["close"])
    g_month, s_month = pct(G["close"], Gm["close"]), pct(S["close"], Sm["close"])
    ratio = G["close"] / S["close"]
    ratio_prev = Gp["close"] / Sp["close"]
    ratio_day = pct(ratio, ratio_prev)
    ratio_month_ago = Gm["close"] / Sm["close"]
    ratio_quarter_ago = (Gq["close"] / Sq["close"]) if (Gq and Sq) else None
    ratio_half_year_ago = (Gh["close"] / Sh["close"]) if (Gh and Sh) else None
    ratio_year_ago = Gy["close"] / Sy["close"]

    gdx_now, sil_now = gdx[igx]["close"], sil[isx]["close"]
    gdx_prev, sil_prev = gdx[igx - 1]["close"], sil[isx - 1]["close"]
    gdx_day, sil_day = pct(gdx_now, gdx_prev), pct(sil_now, sil_prev)
    gdx_y = nearest_on_or_before(gdx, years_before(report_date, 1))
    sil_y = nearest_on_or_before(sil, years_before(report_date, 1))
    gdx_ratio_1y = pct(gdx_now / G["close"], gdx_y["close"] / Gy["close"]) if gdx_y and Gy else None
    sil_ratio_1y = pct(sil_now / S["close"], sil_y["close"] / Sy["close"]) if sil_y and Sy else None

    na = ("公开源暂缺", None, "unavailable")
    SRCC = "Yahoo Finance GC=F（COMEX 连续期货日收盘）"
    SRCS = "Yahoo Finance SI=F（COMEX 连续期货日收盘）"
    SRC_CME = f"CME 每日仓单报告 / {CREDIT}（周度 CSV）"
    SRC_IBJA = "IBJA 官网 PM 午盘基准价（不含 GST）+ Yahoo INR=X"
    SRC_SGE_AU = "上海黄金交易所 Au99.99 收盘价 + Yahoo CNY=X"
    SRC_SHFE = "上海期货交易所（SHFE）官网白银仓单"
    SRC_SGE_V = "上海黄金交易所（SGE）指定仓库库存周报"
    SRC_CFTC = "CFTC COT 公开数据 API（周二持仓快照）"

    # 汇总溢价说明 & 交割压力观察
    prem_parts = []
    if sh_ag_prem is not None and sh_au_prem is not None:
        prem_parts.append(f"上海本地收盘（{sh_au_asof}）：白银 {fmt_pct(sh_ag_prem)}、黄金 {fmt_pct(sh_au_prem)}")
    if in_ag_prem is not None and in_au_prem is not None:
        prem_parts.append(f"印度 IBJA 午盘不含 GST（{in_asof}）：白银 {fmt_pct(in_ag_prem)}、黄金 {fmt_pct(in_au_prem)}")
    elif in_ag_prem is None:
        prem_parts.append("印度 IBJA 仅公布近期交易日，历史日暂缺")
    if prem4 is not None:
        prem_parts.append(f"上海白银近 4 周均值 {prem4:+.2f}%（{CREDIT}）")
    prem_summary = "；".join(prem_parts) + "。" if prem_parts else "本地溢价暂缺。"

    if oi_to_reg is not None:
        if cme_notices and cme_notices.get("mtd_oz") is not None:
            stress_summary = (
                f"CFTC 总持仓 {oi_moz:.2f} Moz（{oi_asof}）÷ COMEX 注册库存 {reg:.2f} Moz（{cag_now['report_date']}）= {oi_to_reg:.1f}x；"
                f"CME 交割通知截至 {cme_notices['as_of']}（当月累计 {_fmt_oz(cme_notices['mtd_oz'])}）。"
            )
        else:
            stress_summary = (
                f"CFTC 总持仓 {oi_moz:.2f} Moz（{oi_asof}）÷ COMEX 注册库存 {reg:.2f} Moz（{cag_now['report_date']}）= {oi_to_reg:.1f}x。"
                "将 CME 交割通知 PDF 放入 data/cme/ 目录即可自动解析。"
            )
    else:
        stress_summary = "持仓量或注册库存暂缺，收盘压力观察待补。"

    fields = {
        "meta.headline": {"display": "", "unit": "text", "source": "DERIVED / app.js 规则引擎", "quality": "rule-generated"},
        "gold.tvc_close": {"value": round(G["close"], 3), "display": fmt_usd(G["close"], 3), "unit": "USD/oz", "source": SRCC, "as_of": report_date + " close", "quality": "real"},
        "gold.change_abs": {"display": fmt_usd(G["close"] - Gp["close"], 3, True), "unit": "USD/oz", "source": SRCC, "direction": direction(G["close"] - Gp["close"]), "quality": "real-derived"},
        "gold.day": {"display": fmt_pct(g_day), "unit": "%", "source": SRCC, "direction": direction(g_day), "quality": "real-derived"},
        "gold.week": {"display": fmt_pct(g_week), "unit": "%", "source": SRCC, "direction": direction(g_week), "quality": "real-derived"},
        "gold.month": {"display": fmt_pct(g_month), "unit": "%", "source": SRCC, "direction": direction(g_month), "quality": "real-derived"},
        "gold.range_low": {"value": round(G["low"], 2), "display": fmt_usd(G["low"], 2), "unit": "USD/oz", "source": SRCC, "quality": "real"},
        "gold.range_high": {"value": round(G["high"], 2), "display": fmt_usd(G["high"], 2), "unit": "USD/oz", "source": SRCC, "quality": "real"},
        "gold.prior_close": {"value": round(Gp["close"], 3), "display": fmt_usd(Gp["close"], 3), "unit": "USD/oz", "source": SRCC, "quality": "real"},
        "silver.tvc_close": {"value": round(S["close"], 4), "display": fmt_usd(S["close"], 4), "unit": "USD/oz", "source": SRCS, "as_of": report_date + " close", "quality": "real"},
        "silver.change_abs": {"display": fmt_usd(S["close"] - Sp["close"], 4, True), "unit": "USD/oz", "source": SRCS, "direction": direction(S["close"] - Sp["close"]), "quality": "real-derived"},
        "silver.day": {"display": fmt_pct(s_day), "unit": "%", "source": SRCS, "direction": direction(s_day), "quality": "real-derived"},
        "silver.week": {"display": fmt_pct(s_week), "unit": "%", "source": SRCS, "direction": direction(s_week), "quality": "real-derived"},
        "silver.month": {"display": fmt_pct(s_month), "unit": "%", "source": SRCS, "direction": direction(s_month), "quality": "real-derived"},
        "silver.range_low": {"value": round(S["low"], 3), "display": fmt_usd(S["low"], 3), "unit": "USD/oz", "source": SRCS, "quality": "real"},
        "silver.range_high": {"value": round(S["high"], 3), "display": fmt_usd(S["high"], 3), "unit": "USD/oz", "source": SRCS, "quality": "real"},
        "silver.prior_close": {"value": round(Sp["close"], 4), "display": fmt_usd(Sp["close"], 4), "unit": "USD/oz", "source": SRCS, "quality": "real"},
        "ratio.value": {"value": round(ratio, 2), "display": f"{ratio:.2f}", "unit": "oz Ag / oz Au", "source": "DERIVED", "formula": "gold.tvc_close / silver.tvc_close", "quality": "real-derived"},
        "ratio.day": {"display": fmt_pct(ratio_day) + " 当日", "unit": "%", "source": "DERIVED", "formula": "(1+gold.day)/(1+silver.day)-1", "direction": direction(ratio_day), "quality": "real-derived"},
        "ratio.month_ago": {"display": f"{ratio_month_ago:.2f}", "unit": "ratio", "source": "DERIVED", "as_of": Gm["date"], "quality": "real-derived"},
        "ratio.quarter_ago": (
            {"display": f"{ratio_quarter_ago:.2f}", "unit": "ratio", "source": "DERIVED", "as_of": Gq["date"], "quality": "real-derived"}
            if ratio_quarter_ago is not None else {"display": "—", "unit": "ratio", "source": "DERIVED", "quality": "unavailable"}
        ),
        "ratio.half_year_ago": (
            {"display": f"{ratio_half_year_ago:.2f}", "unit": "ratio", "source": "DERIVED", "as_of": Gh["date"], "quality": "real-derived"}
            if ratio_half_year_ago is not None else {"display": "—", "unit": "ratio", "source": "DERIVED", "quality": "unavailable"}
        ),
        "ratio.year_ago": {"display": f"{ratio_year_ago:.2f}", "unit": "ratio", "source": "DERIVED", "as_of": Gy["date"], "quality": "real-derived"},
        "bench.silver_india": (
            {"value": round(in_ag_usd, 2), "display": fmt_usd(in_ag_usd, 2), "unit": "USD/oz", "source": SRC_IBJA, "as_of": in_asof + " PM", "quality": "real"}
            if in_ag_usd is not None else {"display": "暂缺（IBJA 仅保留近期）", "unit": "USD/oz", "source": na[0], "quality": na[2]}
        ),
        "bench.silver_india_premium": (
            {"display": fmt_pct(in_ag_prem), "unit": "%", "source": SRC_IBJA, "as_of": in_asof + " PM", "direction": direction(in_ag_prem), "quality": "real-derived"}
            if in_ag_prem is not None else {"display": "—", "unit": "%", "source": na[0], "quality": na[2]}
        ),
        "bench.silver_shanghai": (
            {"value": round(sh_ag_usd, 2), "display": fmt_usd(sh_ag_usd, 2), "unit": "USD/oz", "source": sh_ag_src, "as_of": sh_ag_asof, "quality": "real"}
            if sh_ag_usd is not None else {"display": "暂缺", "unit": "USD/oz", "source": na[0], "quality": na[2]}
        ),
        "bench.silver_shanghai_premium": (
            {"display": fmt_pct(sh_ag_prem), "unit": "%", "source": sh_ag_src, "as_of": sh_ag_asof, "direction": direction(sh_ag_prem), "quality": "real-derived"}
            if sh_ag_prem is not None else {"display": "—", "unit": "%", "source": na[0], "quality": na[2]}
        ),
        "bench.gold_india": (
            {"value": round(in_au_usd, 2), "display": fmt_usd(in_au_usd, 2), "unit": "USD/oz", "source": SRC_IBJA, "as_of": in_asof + " PM", "quality": "real"}
            if in_au_usd is not None else {"display": "暂缺（IBJA 仅保留近期）", "unit": "USD/oz", "source": na[0], "quality": na[2]}
        ),
        "bench.gold_india_premium": (
            {"display": fmt_pct(in_au_prem), "unit": "%", "source": SRC_IBJA, "as_of": in_asof + " PM", "direction": direction(in_au_prem), "quality": "real-derived"}
            if in_au_prem is not None else {"display": "—", "unit": "%", "source": na[0], "quality": na[2]}
        ),
        "bench.gold_shanghai": (
            {"value": round(sh_au_usd, 2), "display": fmt_usd(sh_au_usd, 2), "unit": "USD/oz", "source": SRC_SGE_AU, "as_of": sh_au_asof, "quality": "real"}
            if sh_au_usd is not None else {"display": "暂缺", "unit": "USD/oz", "source": na[0], "quality": na[2]}
        ),
        "bench.gold_shanghai_premium": (
            {"display": fmt_pct(sh_au_prem), "unit": "%", "source": SRC_SGE_AU, "as_of": sh_au_asof, "direction": direction(sh_au_prem), "quality": "real-derived"}
            if sh_au_prem is not None else {"display": "—", "unit": "%", "source": na[0], "quality": na[2]}
        ),
        "vault.comex_registered": (
            {"value": round(reg, 2), "display": f"{reg:.2f}", "unit": "Moz", "source": SRC_CME, "as_of": cag_now["report_date"], "quality": "real"}
            if reg is not None else {"display": "暂缺", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "vault.comex_registered_chg": (
            {"display": f"{reg - reg_wk:+.2f}", "unit": "Moz", "source": SRC_CME, "as_of": f"{cag_wk['report_date']} → {cag_now['report_date']}", "direction": direction(reg - reg_wk), "quality": "real-derived"}
            if reg is not None and reg_wk is not None else {"display": "—", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "vault.comex_registered_d30": (
            {"display": f"{reg - reg_d30:+.2f}", "unit": "Moz", "source": SRC_CME, "as_of": f"{cag_d30['report_date']} → {cag_now['report_date']}", "direction": direction(reg - reg_d30), "quality": "real-derived"}
            if reg is not None and reg_d30 is not None else {"display": "—", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "vault.comex_eligible": (
            {"value": round(elig, 2), "display": f"{elig:.2f}", "unit": "Moz", "source": SRC_CME, "as_of": cag_now["report_date"], "quality": "real"}
            if elig is not None else {"display": "暂缺", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "vault.comex_eligible_chg": (
            {"display": f"{elig - elig_wk:+.2f}", "unit": "Moz", "source": SRC_CME, "as_of": f"{cag_wk['report_date']} → {cag_now['report_date']}", "direction": direction(elig - elig_wk), "quality": "real-derived"}
            if elig is not None and elig_wk is not None else {"display": "—", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "vault.comex_eligible_d30": (
            {"display": f"{elig - elig_d30:+.2f}", "unit": "Moz", "source": SRC_CME, "as_of": f"{cag_d30['report_date']} → {cag_now['report_date']}", "direction": direction(elig - elig_d30), "quality": "real-derived"}
            if elig is not None and elig_d30 is not None else {"display": "—", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "vault.shfe": (
            {"value": round(shfe_stock["total_moz"], 2), "display": f"{shfe_stock['total_moz']:.2f}", "unit": "Moz", "source": SRC_SHFE, "as_of": shfe_stock["as_of"], "quality": "real"}
            if shfe_stock else {"display": "暂缺", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "vault.shfe_chg": (
            {"display": f"{shfe_stock['chg_moz']:+.2f}{shfe_stock['freq']}", "unit": "Moz", "source": SRC_SHFE, "as_of": shfe_stock["as_of"], "direction": direction(shfe_stock["chg_moz"]), "quality": "real-derived"}
            if shfe_stock else {"display": "—", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "vault.sge": (
            {"value": round(sge_vault["total_moz"], 2), "display": f"{sge_vault['total_moz']:.2f}", "unit": "Moz", "source": SRC_SGE_V, "as_of": sge_vault["as_of"], "quality": "real"}
            if sge_vault else {"display": "暂缺", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "vault.lbma": (
            {"value": lbma_cur, "display": f"{lbma_cur:.2f}", "unit": "Moz", "source": "LBMA London Vault Holdings（月度）", "as_of": lbma_asof, "quality": "real"}
            if lbma_cur is not None else {"display": "暂缺", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "vault.lbma_d30": (
            {"display": f"{lbma_cur - lbma_prev:+.2f}m", "unit": "Moz", "source": "LBMA London Vault Holdings（月度）", "as_of": f"{lbma_prev_label} → {lbma_asof}", "direction": direction(lbma_cur - lbma_prev), "quality": "real-derived"}
            if lbma_cur is not None and lbma_prev is not None else {"display": "—", "unit": "Moz", "source": na[0], "quality": na[2]}
        ),
        "comex.oi_to_registered": (
            {"value": round(oi_to_reg, 1), "display": f"{oi_to_reg:.1f}x", "unit": "x", "source": f"{SRC_CFTC} / {SRC_CME}", "as_of": oi_asof, "formula": "CFTC Open_Interest_All (Moz) / COMEX Registered (Moz)", "quality": "real-derived"}
            if oi_to_reg is not None else {"display": "—", "unit": "x", "source": na[0], "quality": na[2]}
        ),
        "comex.registered_to_oi": (
            {"value": round(reg_to_oi, 1), "display": f"{reg_to_oi:.1f}%", "unit": "%", "source": f"{SRC_CFTC} / {SRC_CME}", "as_of": oi_asof, "formula": "COMEX Registered (Moz) / CFTC Open_Interest_All (Moz)", "quality": "real-derived"}
            if reg_to_oi is not None else {"display": "—", "unit": "%", "source": na[0], "quality": na[2]}
        ),
        "comex.notices_total": (
            {
                "value": round(cme_notices["mtd_oz"] / 1e6, 2),
                "display": _fmt_oz(cme_notices["mtd_oz"]),
                "unit": "Moz",
                "source": f"CME 交割通知报表（{cme_notices['file']}）",
                "as_of": cme_notices["as_of"],
                "quality": "real",
            }
            if cme_notices and cme_notices.get("mtd_oz") is not None
            else {"display": "待导入 CME PDF", "unit": "Moz", "source": "将 MetalsIssuesAndStopsReport.pdf 放入 data/cme/", "quality": "unavailable"}
        ),
        "comex.latest_report": (
            {
                "value": cme_notices["daily_oz"],
                "display": _fmt_oz(cme_notices["daily_oz"]),
                "unit": "oz",
                "source": f"CME 交割通知报表（{cme_notices['file']}）",
                "as_of": cme_notices["as_of"],
                "quality": "real",
            }
            if cme_notices and cme_notices.get("daily_oz") is not None
            else {"display": "待导入", "unit": "oz", "source": "将 MetalsIssuesAndStopsReport.pdf 放入 data/cme/", "quality": "unavailable"}
        ),
        "miners.gdx": {"value": round(gdx_now, 2), "display": fmt_usd(gdx_now, 2), "unit": "USD", "source": "Yahoo Finance GDX", "quality": "real"},
        "miners.gdx_day": {"display": fmt_pct(gdx_day), "unit": "%", "source": "Yahoo Finance GDX", "direction": direction(gdx_day), "quality": "real-derived"},
        "miners.gold_day": {"display": "黄金 " + fmt_pct(g_day), "unit": "%", "direction": direction(g_day), "quality": "real-derived"},
        "miners.gdx_ratio_1y": {"display": fmt_pct(gdx_ratio_1y) if gdx_ratio_1y is not None else "暂缺", "unit": "%", "direction": direction(gdx_ratio_1y) if gdx_ratio_1y is not None else "", "quality": "real-derived" if gdx_ratio_1y is not None else "unavailable"},
        "miners.sil": {"value": round(sil_now, 2), "display": fmt_usd(sil_now, 2), "unit": "USD", "source": "Yahoo Finance SIL", "quality": "real"},
        "miners.sil_day": {"display": fmt_pct(sil_day), "unit": "%", "source": "Yahoo Finance SIL", "direction": direction(sil_day), "quality": "real-derived"},
        "miners.silver_day": {"display": "白银 " + fmt_pct(s_day), "unit": "%", "direction": direction(s_day), "quality": "real-derived"},
        "miners.sil_ratio_1y": {"display": fmt_pct(sil_ratio_1y) if sil_ratio_1y is not None else "暂缺", "unit": "%", "direction": direction(sil_ratio_1y) if sil_ratio_1y is not None else "", "quality": "real-derived" if sil_ratio_1y is not None else "unavailable"},
        "quality.premium_avg_30d": {"value": round(prem4, 2) if prem4 is not None else None, "display": prem_summary, "source": "SGE / IBJA / MetalCharts.org", "quality": "real-derived"},
        "quality.stress_score": {"value": round(oi_to_reg, 2) if oi_to_reg is not None else None, "display": stress_summary, "source": "CFTC COT / MetalCharts.org", "quality": "real-derived" if oi_to_reg is not None else "unavailable"},
    }

    # 金银比历史序列（COMEX 期货口径，与本期快照一致）
    gmap = {r["date"]: r["close"] for r in gc}
    smap = {r["date"]: r["close"] for r in si}
    common = sorted(set(gmap) & set(smap))
    series = [{"date": day, "ratio": round(gmap[day] / smap[day], 4)} for day in common if day <= report_date]

    windows = {}
    for name, yrs in (("1y", 1), ("3y", 3), ("5y", 5), ("10y", 10)):
        start = years_before(report_date, yrs)
        vals = [p["ratio"] for p in series if p["date"] >= start]
        if not vals:
            continue
        windows[name] = {
            "percentile": percentile_rank(vals, ratio),
            "samples": len(vals),
            "min": round(min(vals), 2),
            "median": round(sorted(vals)[len(vals) // 2], 2),
            "max": round(max(vals), 2),
            "start": start,
            "end": report_date,
            "p25": q(vals, 0.25),
            "p75": q(vals, 0.75),
        }

    definition = {
        "metric": "百分位排名（Percentile Rank, PR）",
        "formula": "PR = (样本中低于当前值的个数 + 0.5 × 并列个数) ÷ 样本数 × 100",
        "not_percentile_value": f"PR {windows['10y']['percentile'] if '10y' in windows else '—'} 是相对位置，不是该比值数值本身",
        "quartiles": "Q1 = 第 25 百分位数，中位数 = Q2，Q3 = 第 75 百分位数；色带仅表示分位刻度",
    }

    snapshot = {
        "report_date": report_date,
        "weekday": dt.date.fromisoformat(report_date).strftime("%A").upper(),
        "mode": "REAL",
        "lang": "zh-CN",
        "note": (
            "真实采集快照：主行情与矿股/汇率取 Yahoo Finance（GC=F / SI=F / GDX / SIL / CNY=X / INR=X）；"
            "上海基准价与白银指定仓库库存取上海黄金交易所（SGE）官网；印度基准价取 IBJA 官网 PM 午盘价（不含 GST）；"
            "上期所白银仓单取 SHFE 官网；COMEX 注册/合格仓单与上海白银溢价周均值取 MetalCharts.org 免费周度 CSV（页面已署名）；"
            "COMEX 白银总持仓取 CFTC 官方公开 API；LBMA 伦敦金库库存取月度曲线。"
            "CME 交割通知因官网访问限制标 unavailable，未填占位数字。"
        ),
        "generated_at": fetched,
        "color_scheme": "west",
        "provenance": {
            "YF-FUT": "Yahoo Finance COMEX continuous futures daily close (GC=F / SI=F)",
            "Yahoo Equity/FX": "Yahoo Finance GDX / SIL / CNY=X / INR=X daily close",
            "SGE": "Shanghai Gold Exchange (sge.com.cn) daily Au99.99 & Ag(T+D) close and weekly silver vault PDF",
            "IBJA": "India Bullion and Jewellers Association (ibjarates.com) PM 999 gold & silver rates ex-GST",
            "SHFE": "Shanghai Futures Exchange (shfe.com.cn) silver warrant daily/weekly report",
            "CFTC": "CFTC Disaggregated COT Open Data API (publicreporting.cftc.gov)",
            "LBMA": "LBMA London Vault Holdings monthly",
            "MetalCharts": "MetalCharts.org free weekly CSV — COMEX registered/eligible stocks & Shanghai silver premium; reuse with visible credit link",
            "DERIVED": "computed by calculation engine",
        },
        "fields": fields,
        "headline_rule": {
            "engine": "web/app.js headlineFor()",
            "inputs": ["gold.tvc_close", "silver.tvc_close", "gold.day", "silver.day"],
            "order": "按当日涨跌绝对值降序，波动大的品种置于句首",
            "note": "数字由代码读取计算，不交给大模型",
        },
        "removed_sections": ["后续日程", "实物银鹰币", "右上角徽章"],
    }

    heatmap = {
        "source": "Yahoo Finance GC=F / SI=F 日收盘价比值（COMEX 期货口径，与本期快照一致）",
        "retrieved_at": fetched,
        "as_of": report_date,
        "current": round(ratio, 2),
        "total_observations": len(series),
        "caliber": "COMEX 连续期货日收盘价比值；与 P0 样例的 TVC 现货口径不可互换",
        "definition": definition,
        "windows": windows,
    }
    ratio_history = {"as_of": report_date, "source": "Yahoo Finance GC=F / SI=F 日线", "series": series}

    verification = {
        "as_of": report_date,
        "retrieved_at": fetched,
        "source": "Yahoo Finance / SGE / IBJA / SHFE / CFTC / LBMA / MetalCharts.org",
        "method": "本期为真实采集快照：各字段均来自公开免费官方或署名数据源，衍生指标由代码确定性计算",
        "checks": {
            "gold_close": {"value": round(G["close"], 3), "source": SRCC, "quality": "real"},
            "silver_close": {"value": round(S["close"], 4), "source": SRCS, "quality": "real"},
            "gold_prior": {"value": round(Gp["close"], 3), "as_of": Gp["date"]},
            "silver_prior": {"value": round(Sp["close"], 4), "as_of": Sp["date"]},
        },
        "verdict": (
            f"{report_date} 为真实交易日收盘数据：主行情与矿股取 Yahoo Finance；"
            "上海/印度本地基准价取 SGE 与 IBJA 官网；库存取 SHFE、SGE 周报、LBMA 月报及 MetalCharts.org 免费周度 CSV；"
            "COMEX 持仓比取 CFTC 官方 API。仅 CME 交割通知因官网访问限制标暂缺。"
        ),
    }

    dated = lambda n: seed / f"{report_date}.{n}.json"
    (seed / f"{report_date}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dated("ratio-percentile")).write_text(json.dumps(heatmap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dated("ratio-history")).write_text(json.dumps(ratio_history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if curves:
        (dated("curves")).write_text(json.dumps(curves, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dated("close-verification")).write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"OK report_date={report_date} mode=REAL fields={len(fields)} ratio_series={len(series)}")
    print(f"  gold={G['close']:.3f} ({fmt_pct(g_day)}) silver={S['close']:.4f} ({fmt_pct(s_day)}) ratio={ratio:.2f}")
    print(f"  GDX={gdx_now:.2f} ({fmt_pct(gdx_day)}, 1Y={fmt_pct(gdx_ratio_1y) if gdx_ratio_1y is not None else 'N/A'}) "
          f"SIL={sil_now:.2f} ({fmt_pct(sil_day)}, 1Y={fmt_pct(sil_ratio_1y) if sil_ratio_1y is not None else 'N/A'})")
    print(f"  Shanghai Au={fmt_usd(sh_au_usd, 2) if sh_au_usd else 'N/A'} ({fmt_pct(sh_au_prem) if sh_au_prem is not None else 'N/A'}) | "
          f"Ag={fmt_usd(sh_ag_usd, 2) if sh_ag_usd else 'N/A'} ({fmt_pct(sh_ag_prem) if sh_ag_prem is not None else 'N/A'})")
    print(f"  India    Au={fmt_usd(in_au_usd, 2) if in_au_usd else 'N/A'} ({fmt_pct(in_au_prem) if in_au_prem is not None else 'N/A'}) | "
          f"Ag={fmt_usd(in_ag_usd, 2) if in_ag_usd else 'N/A'} ({fmt_pct(in_ag_prem) if in_ag_prem is not None else 'N/A'})")
    print(f"  Vaults: COMEX reg={reg:.2f}/elig={elig:.2f} | SHFE={shfe_stock['total_moz']:.2f} ({shfe_stock['chg_moz']:+.2f}{shfe_stock['freq']}) | "
          f"SGE={sge_vault['total_moz']:.2f} | LBMA={lbma_cur}" if (reg and shfe_stock and sge_vault) else "  Vaults: partial")
    print(f"  CFTC OI={oi_moz} Moz (as_of {oi_asof}) -> OI/Reg={oi_to_reg:.1f}x Reg/OI={reg_to_oi:.1f}%" if oi_to_reg else "  CFTC OI: N/A")
    print(f"  unavailable fields={sum(1 for v in fields.values() if v.get('quality') == 'unavailable')}")

    if args.ingest:
        import sys
        sys.path.insert(0, str(ROOT))
        from backend import db  # noqa: E402
        db.init_db()
        existed = db.upsert_report(
            report_date,
            snapshot,
            heatmap=heatmap,
            ratio_history=ratio_history,
            curves=curves,
            verification=verification,
        )
        print(f"INGEST {'UPDATE' if existed else 'INSERT'} {report_date} -> {db.counts()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
