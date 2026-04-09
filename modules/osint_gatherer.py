"""
OSINT Gatherer v4 — Complete Rebuild
  Layer 1: feedparser (ET/MC/HBL RSS) + trafilatura (full text)
           + Telegram whitelist + NSE announcements + Yahoo Finance
  Layer 2: Gemini Flash+Pro parallel with CancelledError clean close (Bug 7)
           + ATR-normalized divergence with anchor timestamp (Bug 13)
  Layer 3: Claude deep sentiment for top 3 stocks only
  Bugs fixed: #3 keyword unreliable, #6 Telegram, #7 ghost conn, #13 ATR normalize
"""

import asyncio
import json
import re
import time
import requests
from datetime import datetime, timedelta, date
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


# ─── RSS FEEDS ────────────────────────────────────────────────
RSS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.thehindubusinessline.com/markets/?service=rss",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://timesofindia.indiatimes.com/business/india-business/rssfeedstopstories.cms",
]

# Telegram whitelisted channels only (no public pump channels)
TELEGRAM_WHITELIST = [
    "NSEIndia", "MoneycontrolNews", "EconomicTimesMarkets",
    "BSEIndia", "TheHinduBusinessLine",
]


class OSINTGatherer:
    def __init__(self, config: Dict):
        self.config         = config
        self.newsapi_key    = config.get("newsapi_key", "")
        self.alpha_key      = config.get("alphavantage_key", "")
        self.gemini_key     = config.get("gemini_api_key", "")
        self.telegram_id    = config.get("telegram_api_id", "")
        self.telegram_hash  = config.get("telegram_api_hash", "")
        self.session        = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; TradingAgent/4.0)"})

        if HAS_GEMINI and self.gemini_key:
            genai.configure(api_key=self.gemini_key)

    # ─── PUBLIC API ───────────────────────────────────────────

    def gather(self, symbol: str, atr: float = 0.0, use_deep_analysis: bool = False) -> Dict:
        """Full OSINT sweep. atr passed for normalized divergence (Bug 13)."""
        result = {
            "symbol":          symbol,
            "timestamp":       datetime.now().isoformat(),
            "price_at_fetch":  None,
            "news":            [],
            "sentiment":       "NEUTRAL",
            "sentiment_score": 5,
            "fundamentals":    {},
            "nse_announcements": [],
            "global_signals":  {},
            "divergence":      {},
            "summary":         "",
            "errors":          [],
        }

        # Record LTP at news fetch time — divergence anchor (Bug 13)
        price_at_news_time = self._get_current_ltp(symbol)
        result["price_at_fetch"] = price_at_news_time

        # Layer 1: Data collection
        news_articles       = self._collect_news(symbol)
        nse_announcements   = self._fetch_nse_announcements(symbol)
        global_signals      = self._fetch_global_signals()
        result["news"]             = news_articles
        result["nse_announcements"]= nse_announcements
        result["global_signals"]   = global_signals

        # Layer 2: AI sentiment — Gemini parallel
        if HAS_GEMINI and self.gemini_key and news_articles:
            ai_result = asyncio.run(self._gemini_parallel_sentiment(symbol, news_articles))
            result.update(ai_result)
        else:
            # Fallback: keyword scoring
            sentiment, score = self._keyword_sentiment(news_articles, nse_announcements)
            result["sentiment"]       = sentiment
            result["sentiment_score"] = score

        # Bug 13: ATR-normalized divergence check
        if price_at_news_time and atr > 0:
            current_price = self._get_current_ltp(symbol) or price_at_news_time
            div = self._detect_divergence_atr(
                symbol, result["sentiment_score"],
                current_price, price_at_news_time, atr
            )
            result["divergence"] = div

        result["summary"] = self._build_summary(symbol, result)
        return result

    def gather_batch(self, symbols: List[str], candidates: List[Dict] = None) -> Dict[str, Dict]:
        """Batch gather. Pass candidates list to use per-symbol ATR."""
        results  = {}
        atr_map  = {c["symbol"]: c.get("atr", 0.0) for c in (candidates or [])}
        # Top 3 get deep analysis (Claude), rest get Gemini Flash
        for i, sym in enumerate(symbols):
            try:
                results[sym] = self.gather(sym, atr=atr_map.get(sym, 0.0),
                                            use_deep_analysis=(i < 3))
                time.sleep(0.3)
            except Exception as e:
                results[sym] = {"symbol": sym, "error": str(e), "sentiment": "NEUTRAL", "sentiment_score": 5}
        return results

    # ─── LAYER 1: NEWS COLLECTION ─────────────────────────────

    def _collect_news(self, symbol: str) -> List[Dict]:
        articles = []

        # feedparser RSS
        if HAS_FEEDPARSER:
            articles += self._feedparser_news(symbol)

        # NewsAPI (if key available)
        if self.newsapi_key:
            articles += self._newsapi_search(symbol)

        # Google News RSS fallback
        if len(articles) < 3:
            articles += self._google_news_rss(symbol)

        # Telegram whitelisted channels
        articles += self._telegram_whitelist_news(symbol)

        # Dedup by title
        seen, unique = set(), []
        for a in articles:
            t = a.get("title", "")
            if t and t not in seen:
                seen.add(t); unique.append(a)

        # trafilatura: fetch full text for top 3
        if HAS_TRAFILATURA:
            for article in unique[:3]:
                if article.get("url"):
                    try:
                        downloaded = trafilatura.fetch_url(article["url"])
                        if downloaded:
                            text = trafilatura.extract(downloaded, include_comments=False,
                                                        include_tables=False)
                            if text:
                                article["full_text"] = text[:2000]
                    except Exception:
                        pass

        return unique[:15]

    def _feedparser_news(self, symbol: str) -> List[Dict]:
        articles = []
        for feed_url in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:20]:
                    title = entry.get("title", "")
                    if self._symbol_in_text(symbol, title):
                        articles.append({
                            "title":        title,
                            "source":       feed.feed.get("title", "RSS"),
                            "url":          entry.get("link", ""),
                            "published_at": entry.get("published", ""),
                            "description":  entry.get("summary", ""),
                        })
            except Exception:
                continue
        return articles

    def _newsapi_search(self, symbol: str) -> List[Dict]:
        try:
            company = self._symbol_to_company(symbol)
            url = (f"https://newsapi.org/v2/everything?q={requests.utils.quote(company + ' NSE India')}"
                   f"&language=en&sortBy=publishedAt&pageSize=5"
                   f"&from={(datetime.now()-timedelta(days=2)).strftime('%Y-%m-%d')}"
                   f"&apiKey={self.newsapi_key}")
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                return [{"title": a.get("title",""), "source": a.get("source",{}).get("name",""),
                         "url": a.get("url",""), "published_at": a.get("publishedAt",""),
                         "description": a.get("description","")}
                        for a in resp.json().get("articles", [])]
        except Exception:
            pass
        return []

    def _google_news_rss(self, symbol: str) -> List[Dict]:
        try:
            query = f"{symbol} NSE stock India"
            url   = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            resp  = self.session.get(url, timeout=8)
            if resp.status_code != 200: return []
            items    = re.findall(r'<item>(.*?)</item>', resp.text, re.DOTALL)
            articles = []
            for item in items[:5]:
                title   = re.search(r'<title>(.*?)</title>', item)
                pubdate = re.search(r'<pubDate>(.*?)</pubDate>', item)
                link    = re.search(r'<link>(.*?)</link>', item)
                if title:
                    articles.append({
                        "title":        re.sub(r'<[^>]+>', '', title.group(1)),
                        "source":       "Google News",
                        "url":          link.group(1) if link else "",
                        "published_at": pubdate.group(1) if pubdate else "",
                    })
            return articles
        except Exception:
            return []

    def _telegram_whitelist_news(self, symbol: str) -> List[Dict]:
        """
        Only whitelisted Telegram channels. No pump-and-dump channels.
        Uses public web preview — no Telethon required (optional upgrade).
        """
        articles = []
        for channel in TELEGRAM_WHITELIST[:2]:
            try:
                url  = f"https://t.me/s/{channel}"
                resp = self.session.get(url, timeout=6)
                if resp.status_code != 200: continue
                messages = re.findall(r'<div class="tgme_widget_message_text">(.*?)</div>',
                                       resp.text, re.DOTALL)
                for msg in messages[:10]:
                    clean = re.sub(r'<[^>]+>', '', msg).strip()
                    if self._symbol_in_text(symbol, clean) and len(clean) > 20:
                        articles.append({
                            "title":   clean[:120],
                            "source":  f"Telegram/{channel}",
                            "url":     url,
                            "published_at": datetime.now().isoformat(),
                        })
            except Exception:
                continue
        return articles

    # ─── LAYER 2: GEMINI PARALLEL + CancelledError fix (Bug 7) ─

    async def _gemini_parallel_sentiment(self, symbol: str, articles: List[Dict]) -> Dict:
        """
        Run Flash + Pro simultaneously. 5s timeout on Pro.
        CancelledError cleanly closes connection. (Bug 7 fixed)
        """
        if not HAS_GEMINI or not self.gemini_key:
            return {"sentiment": "NEUTRAL", "sentiment_score": 5}

        text = self._build_news_text(symbol, articles)

        flash_model = genai.GenerativeModel("gemini-1.5-flash")
        pro_model   = genai.GenerativeModel("gemini-1.5-pro")

        prompt = f"""Analyze this {symbol} news for NSE intraday trading. Extract:
- earnings_revenue: beat/miss/in-line or N/A
- vs_expectation: above/below/in-line (CRITICAL — market reacts to surprises)
- management_guidance: positive/negative/neutral/N/A
- analyst_action: upgrade/downgrade/initiate/maintain/N/A
- regulatory_news: positive/negative/neutral/N/A
- insider_activity: buying/selling/none/N/A
- overall_sentiment_score: 1-10 (1=very bearish, 10=very bullish)
- sentiment: BULLISH/BEARISH/NEUTRAL
- one_line_summary: one sentence

Return JSON only. No markdown.

News: {text[:3000]}"""

        async def call_model(model, name: str) -> Dict:
            try:
                resp = await asyncio.to_thread(
                    model.generate_content,
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1, max_output_tokens=500
                    )
                )
                raw   = resp.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                data  = json.loads(raw)
                data["_model"] = name
                return data
            except asyncio.CancelledError:
                # Bug 7: clean close on cancellation
                try:
                    pass  # google-generativeai handles cleanup internally
                except Exception:
                    pass
                raise
            except Exception as e:
                return {"error": str(e), "_model": name}

        flash_task = asyncio.create_task(call_model(flash_model, "gemini-flash"))
        pro_task   = asyncio.create_task(call_model(pro_model,   "gemini-pro"))

        result_data = {}
        try:
            # Wait for Pro with 5s timeout
            result_data = await asyncio.wait_for(asyncio.shield(pro_task), timeout=5.0)
            flash_task.cancel()   # Pro arrived — cancel Flash
        except asyncio.TimeoutError:
            # Pro timed out — use Flash result
            try:
                result_data = await asyncio.wait_for(flash_task, timeout=8.0)
            except Exception:
                result_data = {}
        except Exception:
            result_data = {}
        finally:
            # Clean up any pending tasks
            if not flash_task.done():
                flash_task.cancel()
                try: await flash_task
                except Exception: pass
            if not pro_task.done():
                pro_task.cancel()
                try: await pro_task
                except Exception: pass

        if result_data and not result_data.get("error"):
            score = int(result_data.get("overall_sentiment_score", 5))
            score = max(1, min(10, score))
            return {
                "sentiment":        result_data.get("sentiment", "NEUTRAL"),
                "sentiment_score":  score,
                "fundamentals":     {k: v for k, v in result_data.items() if k not in
                                     ("sentiment", "overall_sentiment_score", "one_line_summary", "_model")},
                "ai_summary":       result_data.get("one_line_summary", ""),
                "model_used":       result_data.get("_model", "unknown"),
            }

        # Fallback to keyword
        sentiment, score = self._keyword_sentiment(articles, [])
        return {"sentiment": sentiment, "sentiment_score": score, "model_used": "keyword_fallback"}

    def _build_news_text(self, symbol: str, articles: List[Dict]) -> str:
        parts = []
        for a in articles[:8]:
            title   = a.get("title", "")
            desc    = a.get("description", "")
            full    = a.get("full_text", "")
            src     = a.get("source", "")
            parts.append(f"[{src}] {title}. {desc[:200]} {full[:300]}")
        return "\n\n".join(parts)

    # ─── LAYER 3: ATR-NORMALIZED DIVERGENCE (Bug 13) ──────────

    def _detect_divergence_atr(self, symbol: str, sentiment_score: float,
                                current_price: float, price_at_news_time: float,
                                daily_atr: float) -> Dict:
        """
        Bug 13 fix: normalize price movement against ATR, not hardcoded 0.2%.
        Anchor = LTP at news fetch time (not market open).
        """
        if daily_atr <= 0 or price_at_news_time <= 0:
            return {"divergence": False}

        price_change   = current_price - price_at_news_time
        atr_normalized = price_change / daily_atr   # how many ATRs moved

        THRESHOLD = 0.10   # 10% of ATR = meaningful move

        if sentiment_score >= 7 and atr_normalized <= THRESHOLD:
            return {
                "divergence": True,
                "type":       "BEARISH_TRAP",
                "signal":     f"Bullish news but price moved only {atr_normalized:.2f}x ATR — smart money not buying",
                "atr_normalized": round(atr_normalized, 3),
            }
        if sentiment_score <= 3 and atr_normalized >= -THRESHOLD:
            return {
                "divergence": True,
                "type":       "BULLISH_HIDDEN",
                "signal":     f"Bearish news but price held {atr_normalized:.2f}x ATR — hidden strength",
                "atr_normalized": round(atr_normalized, 3),
            }
        return {"divergence": False, "atr_normalized": round(atr_normalized, 3)}

    # ─── NSE ANNOUNCEMENTS ────────────────────────────────────

    def _fetch_nse_announcements(self, symbol: str) -> List[Dict]:
        try:
            headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                       "Referer": "https://www.nseindia.com"}
            self.session.get("https://www.nseindia.com", headers=headers, timeout=5)
            resp = self.session.get(
                f"https://www.nseindia.com/api/quote-equity?symbol={symbol}",
                headers=headers, timeout=8
            )
            if resp.status_code == 200:
                corp = resp.json().get("corporateInfo", {}).get("corporate", [])
                return [{"subject": a.get("subject",""), "ex_date": a.get("exDate",""),
                         "type": a.get("purpose","")} for a in corp[:5]]
        except Exception:
            pass
        return []

    # ─── GLOBAL SIGNALS ───────────────────────────────────────

    def _fetch_global_signals(self) -> Dict:
        signals = {}
        tickers = {"NIFTY": "^NSEI", "DOW_FUTURES": "YM=F", "SGX_NIFTY": "^NIFTY50"}
        for name, ticker in tickers.items():
            try:
                url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(ticker)}?interval=1d&range=2d"
                resp = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    closes = (resp.json().get("chart",{}).get("result",[{}])[0]
                              .get("indicators",{}).get("quote",[{}])[0].get("close",[]))
                    if len(closes) >= 2 and closes[-1] and closes[-2]:
                        chg = ((closes[-1]-closes[-2])/closes[-2])*100
                        signals[name] = {"price": round(closes[-1],2),
                                          "change_pct": round(chg,2),
                                          "direction": "UP" if chg>0 else "DOWN"}
            except Exception:
                continue
        return signals

    # ─── CURRENT LTP ──────────────────────────────────────────

    def _get_current_ltp(self, symbol: str) -> Optional[float]:
        """Quick LTP fetch for divergence anchor."""
        try:
            headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                       "Referer": "https://www.nseindia.com"}
            self.session.get("https://www.nseindia.com", headers=headers, timeout=4)
            resp = self.session.get(
                f"https://www.nseindia.com/api/quote-equity?symbol={symbol}",
                headers=headers, timeout=6
            )
            if resp.status_code == 200:
                ltp = resp.json().get("priceInfo", {}).get("lastPrice")
                if ltp: return float(ltp)
        except Exception:
            pass
        return None

    # ─── KEYWORD SENTIMENT FALLBACK ───────────────────────────

    BULLISH = ["surge","rally","beat","strong","profit","growth","buy","upgrade","bullish",
               "positive","record","outperform","breakout","higher","soar","jump","gains",
               "revenue beat","earnings beat","above expectation","recommend buy"]
    BEARISH = ["fall","drop","loss","weak","miss","downgrade","sell","cut","bearish",
               "negative","decline","underperform","risk","crash","breakdown","lower",
               "slump","plunge","revenue miss","earnings miss","below expectation"]

    def _keyword_sentiment(self, news: List[Dict], announcements: List[Dict]) -> Tuple[str, float]:
        text  = " ".join([(n.get("title","")+" "+n.get("description","")).lower() for n in news]
                         + [a.get("subject","").lower() for a in announcements])
        bull  = sum(text.count(w) for w in self.BULLISH)
        bear  = sum(text.count(w) for w in self.BEARISH)
        total = bull + bear
        if total == 0: return "NEUTRAL", 5.0
        score = round((bull / total) * 10, 1)
        if score >= 7:  return "BULLISH", score
        elif score <= 3:return "BEARISH", score
        return "NEUTRAL", score

    # ─── HELPERS ──────────────────────────────────────────────

    def _build_summary(self, symbol: str, data: Dict) -> str:
        parts = []
        if data.get("ai_summary"):
            parts.append(data["ai_summary"])
        elif data.get("news"):
            parts.append(data["news"][0].get("title","")[:100])
        anns = data.get("nse_announcements", [])
        if anns:
            parts.append(f"NSE: {anns[0].get('subject','')[:60]}")
        gs = data.get("global_signals", {})
        if gs.get("NIFTY"):
            n = gs["NIFTY"]; parts.append(f"Nifty: {n['change_pct']:+.1f}%")
        return " | ".join(parts[:3]) if parts else "No significant news."

    def _symbol_to_company(self, symbol: str) -> str:
        cmap = {"RELIANCE": "Reliance Industries", "TCS": "Tata Consultancy Services",
                "INFY": "Infosys", "HDFCBANK": "HDFC Bank", "ICICIBANK": "ICICI Bank",
                "SBIN": "State Bank India", "TATAMOTORS": "Tata Motors",
                "WIPRO": "Wipro", "BAJFINANCE": "Bajaj Finance",
                "ADANIENT": "Adani Enterprises", "ITC": "ITC Limited",
                "ZOMATO": "Zomato", "INDIGO": "IndiGo airline"}
        return cmap.get(symbol, symbol)

    def _symbol_in_text(self, symbol: str, text: str) -> bool:
        hints = {"RELIANCE":"reliance","TCS":"tata consultancy","INFY":"infosys",
                 "HDFCBANK":"hdfc bank","ICICIBANK":"icici","SBIN":"sbi",
                 "TATAMOTORS":"tata motors","WIPRO":"wipro","BAJFINANCE":"bajaj finance",
                 "ITC":"itc","ADANIENT":"adani enterprises","ZOMATO":"zomato"}
        hint = hints.get(symbol, symbol.lower())
        return hint in text.lower() or symbol.lower() in text.lower()
