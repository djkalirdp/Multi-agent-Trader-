"""
OSINT Intelligence Gatherer
Stock ke baare mein information gather karta hai:
  - News headlines (NewsAPI / RSS feeds)
  - Social sentiment (Reddit WSB / Twitter/X proxy)
  - Basic fundamentals (free sources)
  - Exchange filings (NSE announcements)
  - Global market signals
"""

import requests
import json
import re
import time
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
from urllib.parse import quote


class OSINTGatherer:
    def __init__(self, config: Dict):
        self.config         = config
        self.newsapi_key    = config.get('newsapi_key', '')
        self.alpha_key      = config.get('alphavantage_key', '')
        self.session        = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    # ─────────────────────────────────────────────────────────
    #  MAIN: gather all intelligence for a symbol
    # ─────────────────────────────────────────────────────────

    def gather(self, symbol: str) -> Dict:
        """
        Full OSINT sweep for a given NSE stock symbol.
        Returns structured intelligence dict.
        """
        result = {
            'symbol':        symbol,
            'timestamp':     datetime.now().isoformat(),
            'news':          [],
            'sentiment':     'NEUTRAL',
            'sentiment_score': 5,
            'fundamentals':  {},
            'nse_announcements': [],
            'global_signals': {},
            'summary':       '',
            'errors':        [],
        }

        # Run all intelligence sources
        news_data  = self._fetch_news(symbol)
        result['news'] = news_data

        if self.alpha_key:
            fund_data = self._fetch_alphavantage_sentiment(symbol)
            result['fundamentals'] = fund_data

        nse_data = self._fetch_nse_announcements(symbol)
        result['nse_announcements'] = nse_data

        global_data = self._fetch_global_signals()
        result['global_signals'] = global_data

        # Compute overall sentiment
        sentiment, score = self._compute_sentiment(news_data, nse_data)
        result['sentiment']       = sentiment
        result['sentiment_score'] = score

        # Build summary
        result['summary'] = self._build_summary(symbol, result)

        return result

    def gather_batch(self, symbols: List[str]) -> Dict[str, Dict]:
        """Gather OSINT for multiple symbols."""
        results = {}
        for sym in symbols:
            try:
                results[sym] = self.gather(sym)
                time.sleep(0.5)   # rate limit courtesy
            except Exception as e:
                results[sym] = {'symbol': sym, 'error': str(e), 'sentiment': 'NEUTRAL'}
        return results

    # ─────────────────────────────────────────────────────────
    #  NEWS FETCHING
    # ─────────────────────────────────────────────────────────

    def _fetch_news(self, symbol: str) -> List[Dict]:
        """Fetch news from multiple sources."""
        articles = []

        # Source 1: NewsAPI (if key provided)
        if self.newsapi_key:
            articles += self._newsapi_search(symbol)

        # Source 2: Free Google News RSS
        articles += self._google_news_rss(symbol)

        # Source 3: MoneyControl RSS (NSE-specific)
        articles += self._moneycontrol_rss(symbol)

        # Deduplicate by title
        seen    = set()
        unique  = []
        for a in articles:
            title = a.get('title', '')
            if title and title not in seen:
                seen.add(title)
                unique.append(a)

        return unique[:15]   # top 15 articles

    def _newsapi_search(self, symbol: str) -> List[Dict]:
        """NewsAPI.org search."""
        try:
            company_map = {
                'RELIANCE': 'Reliance Industries', 'TCS': 'Tata Consultancy Services',
                'INFY': 'Infosys', 'HDFCBANK': 'HDFC Bank', 'ICICIBANK': 'ICICI Bank',
                'SBIN': 'State Bank India', 'TATAMOTORS': 'Tata Motors',
                'WIPRO': 'Wipro', 'BAJFINANCE': 'Bajaj Finance',
            }
            query = company_map.get(symbol, symbol) + ' stock NSE India'
            url   = (
                f"https://newsapi.org/v2/everything?q={quote(query)}"
                f"&language=en&sortBy=publishedAt&pageSize=5"
                f"&from={(datetime.now()-timedelta(days=3)).strftime('%Y-%m-%d')}"
                f"&apiKey={self.newsapi_key}"
            )
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return [
                    {
                        'title':       a.get('title',''),
                        'source':      a.get('source',{}).get('name','NewsAPI'),
                        'url':         a.get('url',''),
                        'published_at':a.get('publishedAt',''),
                        'description': a.get('description',''),
                    }
                    for a in data.get('articles', [])
                ]
        except Exception:
            pass
        return []

    def _google_news_rss(self, symbol: str) -> List[Dict]:
        """Scrape Google News RSS for stock news."""
        try:
            query = f"{symbol} NSE stock India"
            url   = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            resp  = self.session.get(url, timeout=8)
            if resp.status_code != 200:
                return []

            # Simple XML parse (no lxml dependency)
            items = re.findall(r'<item>(.*?)</item>', resp.text, re.DOTALL)
            articles = []
            for item in items[:5]:
                title   = re.search(r'<title>(.*?)</title>', item)
                pubdate = re.search(r'<pubDate>(.*?)</pubDate>', item)
                link    = re.search(r'<link>(.*?)</link>', item)
                if title:
                    articles.append({
                        'title':       re.sub(r'<[^>]+>', '', title.group(1)),
                        'source':      'Google News',
                        'url':         link.group(1) if link else '',
                        'published_at':pubdate.group(1) if pubdate else '',
                    })
            return articles
        except Exception:
            return []

    def _moneycontrol_rss(self, symbol: str) -> List[Dict]:
        """MoneyControl news RSS for NSE stocks."""
        try:
            url  = f"https://www.moneycontrol.com/rss/results.xml"
            resp = self.session.get(url, timeout=8)
            if resp.status_code != 200:
                return []

            items = re.findall(r'<item>(.*?)</item>', resp.text, re.DOTALL)
            articles = []
            for item in items[:10]:
                title = re.search(r'<title>(.*?)</title>', item)
                if title:
                    t = re.sub(r'<[^>]+>', '', title.group(1))
                    if symbol.lower() in t.lower() or self._symbol_in_text(symbol, t):
                        link    = re.search(r'<link>(.*?)</link>', item)
                        pubdate = re.search(r'<pubDate>(.*?)</pubDate>', item)
                        articles.append({
                            'title':       t,
                            'source':      'MoneyControl',
                            'url':         link.group(1) if link else '',
                            'published_at':pubdate.group(1) if pubdate else '',
                        })
            return articles[:3]
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────
    #  NSE ANNOUNCEMENTS
    # ─────────────────────────────────────────────────────────

    def _fetch_nse_announcements(self, symbol: str) -> List[Dict]:
        """Fetch corporate announcements from NSE India."""
        try:
            url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json',
                'Referer': 'https://www.nseindia.com',
            }
            # First hit the main page to get cookies
            self.session.get('https://www.nseindia.com', headers=headers, timeout=8)
            resp = self.session.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                announcements = []
                corp_actions = data.get('corporateInfo', {}).get('corporate', [])
                for action in corp_actions[:5]:
                    announcements.append({
                        'subject':   action.get('subject', ''),
                        'ex_date':   action.get('exDate', ''),
                        'rec_date':  action.get('recDate', ''),
                        'type':      action.get('purpose', ''),
                    })
                return announcements
        except Exception:
            pass
        return []

    # ─────────────────────────────────────────────────────────
    #  ALPHA VANTAGE SENTIMENT
    # ─────────────────────────────────────────────────────────

    def _fetch_alphavantage_sentiment(self, symbol: str) -> Dict:
        """Alpha Vantage News Sentiment API."""
        try:
            # Alpha Vantage uses US tickers — map NSE to BSE equivalent for best effort
            url = (
                f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT"
                f"&tickers={symbol}.BSE&limit=10&apikey={self.alpha_key}"
            )
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                feed     = data.get('feed', [])
                if feed:
                    scores = []
                    for article in feed[:5]:
                        for ts in article.get('ticker_sentiment', []):
                            score = float(ts.get('ticker_sentiment_score', 0))
                            scores.append(score)
                    if scores:
                        avg = sum(scores) / len(scores)
                        return {
                            'avg_sentiment_score': round(avg, 3),
                            'articles_analyzed':   len(feed),
                            'source': 'alphavantage',
                        }
        except Exception:
            pass
        return {}

    # ─────────────────────────────────────────────────────────
    #  GLOBAL MARKET SIGNALS
    # ─────────────────────────────────────────────────────────

    def _fetch_global_signals(self) -> Dict:
        """Fetch US futures, DXY, crude oil signals (free sources)."""
        signals = {}
        try:
            # Yahoo Finance for SGX Nifty proxy (^NSEI) and global signals
            tickers = {'NIFTY': '^NSEI', 'SGXNIFTY': 'SG.NIFTY50', 'DXY': 'DX-Y.NYB'}
            for name, ticker in tickers.items():
                url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}?interval=1d&range=2d"
                resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
                if resp.status_code == 200:
                    data  = resp.json()
                    closes = data.get('chart', {}).get('result', [{}])[0].get('indicators', {}).get('quote', [{}])[0].get('close', [])
                    if len(closes) >= 2 and closes[-1] and closes[-2]:
                        chg_pct = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                        signals[name] = {
                            'price':      round(closes[-1], 2),
                            'change_pct': round(chg_pct, 2),
                            'direction':  'UP' if chg_pct > 0 else 'DOWN',
                        }
        except Exception:
            pass
        return signals

    # ─────────────────────────────────────────────────────────
    #  SENTIMENT ANALYSIS
    # ─────────────────────────────────────────────────────────

    BULLISH_WORDS = [
        'surge', 'rally', 'beat', 'strong', 'profit', 'growth', 'buy', 'upgrade',
        'bullish', 'positive', 'record', 'outperform', 'target', 'upside', 'gains',
        'revenue beat', 'earnings beat', 'breakout', 'higher', 'soar', 'jump'
    ]
    BEARISH_WORDS = [
        'fall', 'drop', 'loss', 'weak', 'miss', 'downgrade', 'sell', 'cut',
        'bearish', 'negative', 'decline', 'underperform', 'risk', 'crash',
        'revenue miss', 'earnings miss', 'breakdown', 'lower', 'slump', 'plunge'
    ]

    def _compute_sentiment(self, news: List[Dict], announcements: List[Dict]) -> tuple:
        """Score sentiment from news + announcements."""
        bull_count = 0
        bear_count = 0

        all_text = ' '.join([
            (n.get('title','') + ' ' + n.get('description','')).lower()
            for n in news
        ] + [a.get('subject','').lower() for a in announcements])

        for word in self.BULLISH_WORDS:
            bull_count += all_text.count(word)
        for word in self.BEARISH_WORDS:
            bear_count += all_text.count(word)

        total = bull_count + bear_count
        if total == 0:
            return 'NEUTRAL', 5

        score = round((bull_count / total) * 10, 1)   # 0-10 scale

        if score >= 7:
            return 'BULLISH', score
        elif score <= 3:
            return 'BEARISH', score
        else:
            return 'NEUTRAL', score

    def _build_summary(self, symbol: str, data: Dict) -> str:
        """Build a 2-sentence summary of all OSINT."""
        news   = data.get('news', [])
        anns   = data.get('nse_announcements', [])
        global_signals = data.get('global_signals', {})

        parts = []
        if news:
            parts.append(f"Latest news: {news[0].get('title','')}")
        if anns:
            parts.append(f"NSE announcement: {anns[0].get('subject','')}")
        if global_signals.get('NIFTY'):
            n = global_signals['NIFTY']
            parts.append(f"Nifty: {n['change_pct']:+.1f}%")

        return ' | '.join(parts[:3]) if parts else 'No significant news found.'

    def _symbol_in_text(self, symbol: str, text: str) -> bool:
        """Check if a stock symbol's company name is mentioned in text."""
        company_hints = {
            'RELIANCE': 'reliance', 'TCS': 'tata consultancy', 'INFY': 'infosys',
            'HDFCBANK': 'hdfc bank', 'ICICIBANK': 'icici', 'SBIN': 'sbi',
            'TATAMOTORS': 'tata motors', 'WIPRO': 'wipro', 'BAJFINANCE': 'bajaj finance',
        }
        hint = company_hints.get(symbol, symbol.lower())
        return hint in text.lower()
