"""
OSINT Gatherer v4.1 — Bug fixes:
  - Gemini 429 fix: Flash-only by default, exponential backoff, rate limiter
  - Gemini Pro only for #1 ranked stock (not all 5 simultaneously)
  - Per-symbol 1.5s delay between Gemini calls
  - asyncio.run() nested call fix
  - Proper error messages returned to dashboard
"""

import asyncio
import json
import re
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

RSS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.thehindubusinessline.com/markets/?service=rss",
]

TELEGRAM_WHITELIST = [
    "NSEIndia", "MoneycontrolNews", "EconomicTimesMarkets",
    "BSEIndia", "TheHinduBusinessLine",
]

# Gemini free tier: 60 RPM = 1 per second. We use 1.5s delay to stay safe.
_GEMINI_CALL_DELAY = 1.5
_last_gemini_call  = 0.0


def _gemini_rate_wait():
    """Block until safe to make next Gemini call."""
    global _last_gemini_call
    elapsed = time.time() - _last_gemini_call
    if elapsed < _GEMINI_CALL_DELAY:
        time.sleep(_GEMINI_CALL_DELAY - elapsed)
    _last_gemini_call = time.time()


class OSINTGatherer:
    def __init__(self, config: Dict):
        self.config        = config
        self.newsapi_key   = config.get("newsapi_key", "")
        self.alpha_key     = config.get("alphavantage_key", "")
        self.gemini_key    = config.get("gemini_api_key", "")
        self.telegram_id   = config.get("telegram_api_id", "")
        self.telegram_hash = config.get("telegram_api_hash", "")
        self.session       = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (TradingAgent/4.1)"})

        if HAS_GEMINI and self.gemini_key:
            genai.configure(api_key=self.gemini_key)

    # ─── PUBLIC API ───────────────────────────────────────────

    def gather(self, symbol: str, atr: float = 0.0,
               use_pro_model: bool = False) -> Dict:
        """
        Full OSINT for one symbol.
        use_pro_model=True only for the #1 ranked stock (saves quota).
        """
        result = {
            "symbol":           symbol,
            "timestamp":        datetime.now().isoformat(),
            "price_at_fetch":   None,
            "news":             [],
            "sentiment":        "NEUTRAL",
            "sentiment_score":  5,
            "fundamentals":     {},
            "nse_announcements":[],
            "global_signals":   {},
            "divergence":       {},
            "summary":          "",
            "model_used":       "none",
            "errors":           [],
        }

        try:
            # Anchor LTP for divergence
            price_at_news_time          = self._get_current_ltp(symbol)
            result["price_at_fetch"]    = price_at_news_time

            # Layer 1 — collect news
            news        = self._collect_news(symbol)
            anns        = self._fetch_nse_announcements(symbol)
            global_sig  = self._fetch_global_signals()
            result["news"]              = news
            result["nse_announcements"] = anns
            result["global_signals"]    = global_sig

            # Layer 2 — AI sentiment (Gemini Flash with rate limiter)
            if HAS_GEMINI and self.gemini_key and news:
                ai = self._gemini_sentiment_safe(symbol, news, use_pro=use_pro_model)
                result.update(ai)
            else:
                s, sc = self._keyword_sentiment(news, anns)
                result["sentiment"]      = s
                result["sentiment_score"]= sc
                result["model_used"]     = "keyword"

            # ATR-normalized divergence
            if price_at_news_time and atr > 0:
                cur = self._get_current_ltp(symbol) or price_at_news_time
                result["divergence"] = self._detect_divergence_atr(
                    result["sentiment_score"], cur, price_at_news_time, atr
                )

            result["summary"] = self._build_summary(symbol, result)

        except Exception as e:
            result["errors"].append(str(e))
            result["summary"] = f"OSINT error: {e}"

        return result

    def gather_batch(self, symbols: List[str],
                     candidates: List[Dict] = None) -> Dict[str, Dict]:
        """
        Batch OSINT. Only first symbol gets Pro model.
        1.5s delay between calls prevents 429.
        """
        results = {}
        atr_map = {c["symbol"]: c.get("atr", 0.0) for c in (candidates or [])}

        for i, sym in enumerate(symbols):
            try:
                results[sym] = self.gather(
                    sym,
                    atr=atr_map.get(sym, 0.0),
                    use_pro_model=(i == 0)   # Pro only for top stock
                )
            except Exception as e:
                results[sym] = {
                    "symbol": sym, "error": str(e),
                    "sentiment": "NEUTRAL", "sentiment_score": 5,
                    "news": [], "summary": f"Error: {e}"
                }
            # Rate limit: wait between symbols
            if i < len(symbols) - 1:
                time.sleep(_GEMINI_CALL_DELAY)

        return results

    # ─── GEMINI SAFE CALL (no asyncio.run nesting) ───────────

    def _gemini_sentiment_safe(self, symbol: str, articles: List[Dict],
                                use_pro: bool = False) -> Dict:
        """
        Synchronous Gemini call with:
          - Rate limiter (1.5s between calls)
          - Retry on 429 with exponential backoff (max 3 retries)
          - Flash by default, Pro only when use_pro=True and quota allows
          - Returns keyword fallback on persistent failure
        """
        if not HAS_GEMINI or not self.gemini_key:
            s, sc = self._keyword_sentiment(articles, [])
            return {"sentiment": s, "sentiment_score": sc, "model_used": "keyword_no_gemini"}

        model_name = "gemini-1.5-pro" if use_pro else "gemini-1.5-flash"
        text       = self._build_news_text(symbol, articles)
        prompt     = self._build_sentiment_prompt(symbol, text)

        for attempt in range(3):
            try:
                _gemini_rate_wait()
                model   = genai.GenerativeModel(model_name)
                resp    = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1, max_output_tokens=400
                    )
                )
                raw  = resp.text.strip()
                # Strip markdown fences if present
                raw  = re.sub(r'^```(?:json)?\s*', '', raw)
                raw  = re.sub(r'\s*```$', '', raw)
                data = json.loads(raw.strip())

                score = max(1, min(10, int(data.get("overall_sentiment_score", 5))))
                return {
                    "sentiment":       data.get("sentiment", "NEUTRAL"),
                    "sentiment_score": score,
                    "fundamentals":    {k: v for k, v in data.items()
                                        if k not in ("sentiment", "overall_sentiment_score",
                                                     "one_line_summary", "_model")},
                    "ai_summary":      data.get("one_line_summary", ""),
                    "model_used":      model_name,
                }

            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "quota" in err_str or "rate" in err_str:
                    # 429 → downgrade to Flash, backoff
                    model_name = "gemini-1.5-flash"
                    wait       = 2 ** attempt * 2   # 2s, 4s, 8s
                    time.sleep(wait)
                    continue
                elif "json" in err_str or "parse" in err_str:
                    # Bad JSON → try keyword fallback directly
                    break
                else:
                    break

        # All retries failed → keyword fallback
        s, sc = self._keyword_sentiment(articles, [])
        return {"sentiment": s, "sentiment_score": sc, "model_used": "keyword_fallback"}

    def _build_sentiment_prompt(self, symbol: str, text: str) -> str:
        return f"""Analyze this {symbol} NSE stock news for intraday trading.
Return ONLY valid JSON, no markdown, no explanation.

{{
  "earnings_revenue": "beat/miss/in-line/N/A",
  "vs_expectation": "above/below/in-line/N/A",
  "management_guidance": "positive/negative/neutral/N/A",
  "analyst_action": "upgrade/downgrade/initiate/maintain/N/A",
  "regulatory_news": "positive/negative/neutral/N/A",
  "insider_activity": "buying/selling/none/N/A",
  "overall_sentiment_score": 5,
  "sentiment": "NEUTRAL",
  "one_line_summary": "one sentence max"
}}

News:
{text[:2500]}"""

    # ─── NEWS COLLECTION ──────────────────────────────────────

    def _collect_news(self, symbol: str) -> List[Dict]:
        articles = []

        # Source 1: feedparser RSS (always free — ET, MC, BS)
        if HAS_FEEDPARSER:
            articles += self._feedparser_news(symbol)

        # Source 2: Google News RSS (always free, no key needed)
        articles += self._google_news_rss(symbol)

        # Source 3: Investing.com RSS (always free)
        articles += self._investing_rss(symbol)

        # Source 4: NewsAPI (optional, only if key provided)
        if self.newsapi_key and len(articles) < 5:
            articles += self._newsapi_search(symbol)

        articles += self._telegram_whitelist_news(symbol)

        # Dedup
        seen, unique = set(), []
        for a in articles:
            t = a.get("title", "")
            if t and t not in seen:
                seen.add(t); unique.append(a)

        # Full text via trafilatura (top 2 only to save time)
        if HAS_TRAFILATURA:
            for article in unique[:2]:
                url = article.get("url", "")
                if url:
                    try:
                        dl = trafilatura.fetch_url(url)
                        if dl:
                            txt = trafilatura.extract(dl, include_comments=False,
                                                       include_tables=False)
                            if txt:
                                article["full_text"] = txt[:1500]
                    except Exception:
                        pass

        return unique[:12]

    def _feedparser_news(self, symbol: str) -> List[Dict]:
        articles = []
        for url in RSS_FEEDS:
            try:
                feed = feedparser.parse(url)
                for e in feed.entries[:15]:
                    title = e.get("title", "")
                    if self._symbol_in_text(symbol, title + " " + e.get("summary", "")):
                        articles.append({
                            "title":        title,
                            "source":       feed.feed.get("title", "RSS"),
                            "url":          e.get("link", ""),
                            "published_at": e.get("published", ""),
                            "description":  e.get("summary", "")[:300],
                        })
            except Exception:
                continue
        return articles

    def _newsapi_search(self, symbol: str) -> List[Dict]:
        try:
            q    = requests.utils.quote(f"{self._symbol_to_company(symbol)} NSE India")
            from_d = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
            url  = (f"https://newsapi.org/v2/everything?q={q}"
                    f"&language=en&sortBy=publishedAt&pageSize=5&from={from_d}"
                    f"&apiKey={self.newsapi_key}")
            r    = self.session.get(url, timeout=8)
            if r.status_code == 200:
                return [{"title": a.get("title",""), "source": a.get("source",{}).get("name",""),
                         "url": a.get("url",""), "published_at": a.get("publishedAt",""),
                         "description": a.get("description","")}
                        for a in r.json().get("articles", [])]
        except Exception:
            pass
        return []

    def _google_news_rss(self, symbol: str) -> List[Dict]:
        try:
            q    = requests.utils.quote(f"{symbol} NSE stock India")
            url  = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
            resp = self.session.get(url, timeout=6)
            if resp.status_code != 200: return []
            items = re.findall(r'<item>(.*?)</item>', resp.text, re.DOTALL)
            arts  = []
            for item in items[:5]:
                t = re.search(r'<title>(.*?)</title>', item)
                d = re.search(r'<pubDate>(.*?)</pubDate>', item)
                l = re.search(r'<link>(.*?)</link>', item)
                if t:
                    arts.append({
                        "title":        re.sub(r'<[^>]+>', '', t.group(1)),
                        "source":       "Google News",
                        "url":          l.group(1) if l else "",
                        "published_at": d.group(1) if d else "",
                    })
            return arts
        except Exception:
            return []

    def _telegram_whitelist_news(self, symbol: str) -> List[Dict]:
        arts = []
        for ch in TELEGRAM_WHITELIST[:2]:
            try:
                resp = self.session.get(f"https://t.me/s/{ch}", timeout=5)
                if resp.status_code != 200: continue
                msgs = re.findall(r'<div class="tgme_widget_message_text">(.*?)</div>',
                                   resp.text, re.DOTALL)
                for msg in msgs[:8]:
                    clean = re.sub(r'<[^>]+>', '', msg).strip()
                    if self._symbol_in_text(symbol, clean) and len(clean) > 20:
                        arts.append({
                            "title": clean[:120], "source": f"Telegram/{ch}",
                            "url": f"https://t.me/s/{ch}",
                            "published_at": datetime.now().isoformat(),
                        })
            except Exception:
                continue
        return arts

    def _investing_rss(self, symbol: str) -> list:
        """Investing.com RSS — free, no API key. Good for NSE stocks."""
        try:
            company = self._symbol_to_company(symbol)
            q = company.lower().replace(' ', '-').replace('&', '')
            urls = [
                f'https://www.investing.com/rss/news_{symbol.lower()}.rss',
                'https://in.investing.com/rss/news_285.rss',   # India markets
            ]
            arts = []
            for url in urls:
                try:
                    resp = self.session.get(url, timeout=5)
                    if resp.status_code != 200: continue
                    items = __import__('re').findall(r'<item>(.*?)</item>', resp.text, 8)
                    for item in items[:5]:
                        import re
                        t = re.search(r'<title>(.*?)</title>', item)
                        l = re.search(r'<link>(.*?)</link>', item)
                        d = re.search(r'<pubDate>(.*?)</pubDate>', item)
                        if t:
                            title = re.sub(r'<[^>]+>','',t.group(1))
                            if self._symbol_in_text(symbol, title):
                                arts.append({'title':title,'source':'Investing.com',
                                             'url': l.group(1) if l else '','published_at': d.group(1) if d else ''})
                except Exception:
                    continue
            return arts[:3]
        except Exception:
            return []

    # ─── NSE + GLOBAL ─────────────────────────────────────────

    def _fetch_nse_announcements(self, symbol: str) -> List[Dict]:
        try:
            h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                 "Referer": "https://www.nseindia.com"}
            self.session.get("https://www.nseindia.com", headers=h, timeout=4)
            r = self.session.get(
                f"https://www.nseindia.com/api/quote-equity?symbol={symbol}",
                headers=h, timeout=7
            )
            if r.status_code == 200:
                corp = r.json().get("corporateInfo", {}).get("corporate", [])
                return [{"subject": a.get("subject",""), "ex_date": a.get("exDate",""),
                         "type": a.get("purpose","")} for a in corp[:5]]
        except Exception:
            pass
        return []

    def _fetch_global_signals(self) -> Dict:
        signals = {}
        tickers = {"NIFTY": "^NSEI", "DOW": "^DJI", "SGX": "^NSEI"}
        for name, ticker in tickers.items():
            try:
                url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(ticker)}?interval=1d&range=2d"
                r    = requests.get(url, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200:
                    closes = (r.json().get("chart",{}).get("result",[{}])[0]
                               .get("indicators",{}).get("quote",[{}])[0].get("close",[]))
                    if len(closes) >= 2 and closes[-1] and closes[-2]:
                        chg = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                        signals[name] = {"price": round(closes[-1], 2),
                                          "change_pct": round(chg, 2),
                                          "direction": "UP" if chg > 0 else "DOWN"}
            except Exception:
                continue
        return signals

    def _get_current_ltp(self, symbol: str) -> Optional[float]:
        try:
            h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                 "Referer": "https://www.nseindia.com"}
            self.session.get("https://www.nseindia.com", headers=h, timeout=3)
            r = self.session.get(
                f"https://www.nseindia.com/api/quote-equity?symbol={symbol}",
                headers=h, timeout=5
            )
            if r.status_code == 200:
                ltp = r.json().get("priceInfo", {}).get("lastPrice")
                return float(ltp) if ltp else None
        except Exception:
            pass
        return None

    # ─── ATR DIVERGENCE ───────────────────────────────────────

    def _detect_divergence_atr(self, sentiment_score: float,
                                current_price: float, price_at_news_time: float,
                                daily_atr: float) -> Dict:
        if daily_atr <= 0 or price_at_news_time <= 0:
            return {"divergence": False}
        change      = current_price - price_at_news_time
        atr_norm    = change / daily_atr
        THRESHOLD   = 0.10
        if sentiment_score >= 7 and atr_norm <= THRESHOLD:
            return {"divergence": True, "type": "BEARISH_TRAP",
                    "signal": f"Bullish news but only {atr_norm:.2f}x ATR move",
                    "atr_normalized": round(atr_norm, 3)}
        if sentiment_score <= 3 and atr_norm >= -THRESHOLD:
            return {"divergence": True, "type": "BULLISH_HIDDEN",
                    "signal": f"Bearish news but price held {atr_norm:.2f}x ATR",
                    "atr_normalized": round(atr_norm, 3)}
        return {"divergence": False, "atr_normalized": round(atr_norm, 3)}

    # ─── KEYWORD FALLBACK ─────────────────────────────────────

    BULLISH = ["surge","rally","beat","strong","profit","growth","buy","upgrade","bullish",
               "positive","record","outperform","breakout","higher","soar","jump","gains",
               "revenue beat","earnings beat","above expectation"]
    BEARISH = ["fall","drop","loss","weak","miss","downgrade","sell","cut","bearish",
               "negative","decline","underperform","risk","crash","breakdown","lower",
               "slump","plunge","revenue miss","earnings miss","below expectation"]

    def _keyword_sentiment(self, news: List[Dict],
                            anns: List[Dict]) -> Tuple[str, float]:
        text  = " ".join([(n.get("title","")+" "+n.get("description","")).lower()
                           for n in news] + [a.get("subject","").lower() for a in anns])
        bull  = sum(text.count(w) for w in self.BULLISH)
        bear  = sum(text.count(w) for w in self.BEARISH)
        total = bull + bear
        if total == 0: return "NEUTRAL", 5.0
        score = round((bull / total) * 10, 1)
        if   score >= 7: return "BULLISH", score
        elif score <= 3: return "BEARISH", score
        return "NEUTRAL", score

    # ─── HELPERS ──────────────────────────────────────────────

    def _build_news_text(self, symbol: str, articles: List[Dict]) -> str:
        parts = []
        for a in articles[:6]:
            src  = a.get("source", "")
            t    = a.get("title", "")
            d    = a.get("description", "")[:150]
            full = a.get("full_text", "")[:300]
            parts.append(f"[{src}] {t}. {d} {full}")
        return "\n\n".join(parts)

    def _build_summary(self, symbol: str, data: Dict) -> str:
        parts = []
        if data.get("ai_summary"):
            parts.append(data["ai_summary"])
        elif data.get("news"):
            parts.append(data["news"][0].get("title", "")[:100])
        if data.get("nse_announcements"):
            parts.append(f'NSE: {data["nse_announcements"][0].get("subject","")[:60]}')
        n = data.get("global_signals", {}).get("NIFTY", {})
        if n:
            parts.append(f'Nifty: {n["change_pct"]:+.1f}%')
        return " | ".join(parts[:3]) if parts else "No significant news."

    def _symbol_to_company(self, sym: str) -> str:
        m = {"RELIANCE":"Reliance Industries","TCS":"Tata Consultancy",
             "INFY":"Infosys","HDFCBANK":"HDFC Bank","ICICIBANK":"ICICI Bank",
             "SBIN":"State Bank India","TATAMOTORS":"Tata Motors","WIPRO":"Wipro",
             "BAJFINANCE":"Bajaj Finance","ADANIENT":"Adani Enterprises",
             "ITC":"ITC Limited","ZOMATO":"Zomato","INDIGO":"IndiGo"}
        return m.get(sym, sym)

    def _symbol_in_text(self, sym: str, text: str) -> bool:
        hints = {"RELIANCE":"reliance","TCS":"tata consultancy","INFY":"infosys",
                 "HDFCBANK":"hdfc bank","ICICIBANK":"icici","SBIN":"sbi",
                 "TATAMOTORS":"tata motors","WIPRO":"wipro","BAJFINANCE":"bajaj finance",
                 "ITC":"itc","ADANIENT":"adani","ZOMATO":"zomato","INDIGO":"indigo"}
        hint = hints.get(sym, sym.lower())
        return hint in text.lower() or sym.lower() in text.lower()
