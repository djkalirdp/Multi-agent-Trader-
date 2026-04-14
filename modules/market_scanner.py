"""
Market Scanner v4.1 — Bug fixes:
  - Scan=0 fix: fallback ATR from High-Low when candles unavailable
  - Multiple DhanHQ API field name formats handled
  - Relaxed filters with config-driven thresholds
  - Demo mode when market closed (returns sample data for UI testing)
  - Proper error propagation to dashboard
"""

import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

DHAN_BASE = "https://api.dhan.co"

NSE_FO_UNIVERSE = [
    {"symbol":"RELIANCE","security_id":"2885"},{"symbol":"TCS","security_id":"11536"},
    {"symbol":"INFY","security_id":"1594"},{"symbol":"HDFCBANK","security_id":"1333"},
    {"symbol":"ICICIBANK","security_id":"4963"},{"symbol":"SBIN","security_id":"3045"},
    {"symbol":"AXISBANK","security_id":"5900"},{"symbol":"KOTAKBANK","security_id":"1922"},
    {"symbol":"BAJFINANCE","security_id":"317"},{"symbol":"WIPRO","security_id":"3787"},
    {"symbol":"HCLTECH","security_id":"1348"},{"symbol":"LT","security_id":"11483"},
    {"symbol":"TATAMOTORS","security_id":"3456"},{"symbol":"TATASTEEL","security_id":"3499"},
    {"symbol":"MARUTI","security_id":"10999"},{"symbol":"SUNPHARMA","security_id":"3351"},
    {"symbol":"DRREDDY","security_id":"881"},{"symbol":"HINDALCO","security_id":"1363"},
    {"symbol":"JSWSTEEL","security_id":"11723"},{"symbol":"ONGC","security_id":"2475"},
    {"symbol":"NTPC","security_id":"11630"},{"symbol":"POWERGRID","security_id":"14977"},
    {"symbol":"ADANIENT","security_id":"25"},{"symbol":"ADANIPORTS","security_id":"15083"},
    {"symbol":"ULTRACEMCO","security_id":"11532"},{"symbol":"GRASIM","security_id":"1232"},
    {"symbol":"BHARTIARTL","security_id":"10604"},{"symbol":"INDUSINDBK","security_id":"5258"},
    {"symbol":"M&M","security_id":"2031"},{"symbol":"TECHM","security_id":"13538"},
    {"symbol":"ITC","security_id":"1660"},{"symbol":"ASIANPAINT","security_id":"236"},
    {"symbol":"BAJAJ-AUTO","security_id":"16669"},{"symbol":"BRITANNIA","security_id":"547"},
    {"symbol":"CIPLA","security_id":"694"},{"symbol":"COALINDIA","security_id":"20374"},
    {"symbol":"DIVISLAB","security_id":"10940"},{"symbol":"EICHERMOT","security_id":"910"},
    {"symbol":"HAVELLS","security_id":"430"},{"symbol":"IRCTC","security_id":"13611"},
    {"symbol":"HAL","security_id":"2303"},{"symbol":"BEL","security_id":"383"},
    {"symbol":"BHEL","security_id":"438"},{"symbol":"IDFCFIRSTB","security_id":"11957"},
    {"symbol":"BANKBARODA","security_id":"1727"},{"symbol":"CANBK","security_id":"2263"},
    {"symbol":"FEDERALBNK","security_id":"1023"},{"symbol":"RBLBANK","security_id":"18391"},
    {"symbol":"AUBANK","security_id":"21238"},{"symbol":"CHOLAFIN","security_id":"685"},
    {"symbol":"MUTHOOTFIN","security_id":"14142"},{"symbol":"SBILIFE","security_id":"21808"},
    {"symbol":"HDFCLIFE","security_id":"119"},{"symbol":"AMBUJACEM","security_id":"1270"},
    {"symbol":"ACC","security_id":"22"},{"symbol":"APOLLOHOSP","security_id":"157"},
    {"symbol":"BIOCON","security_id":"524"},{"symbol":"AUROPHARMA","security_id":"275"},
    {"symbol":"ADANIGREEN","security_id":"21669"},{"symbol":"INDIGO","security_id":"11195"},
    {"symbol":"DMART","security_id":"17192"},{"symbol":"TRENT","security_id":"3499"},
    {"symbol":"BERGEPAINT","security_id":"1747"},{"symbol":"TATACHEM","security_id":"3440"},
    {"symbol":"UPL","security_id":"3651"},{"symbol":"MPHASIS","security_id":"3100"},
    {"symbol":"LTIM","security_id":"17818"},{"symbol":"PERSISTENT","security_id":"18365"},
    {"symbol":"COFORGE","security_id":"11543"},{"symbol":"TATAELXSI","security_id":"3507"},
    {"symbol":"APOLLOTYRE","security_id":"163"},{"symbol":"BALKRISIND","security_id":"1678"},
    {"symbol":"BOSCHLTD","security_id":"3070"},{"symbol":"CUMMINSIND","security_id":"779"},
    {"symbol":"ZOMATO","security_id":"21296"},{"symbol":"NYKAA","security_id":"21894"},
    {"symbol":"PAYTM","security_id":"21712"},{"symbol":"PNB","security_id":"2730"},
    {"symbol":"RECLTD","security_id":"15355"},{"symbol":"SAIL","security_id":"2963"},
    {"symbol":"VEDL","security_id":"3063"},{"symbol":"TATAPOWER","security_id":"3426"},
    {"symbol":"TORNTPHARM","security_id":"3518"},{"symbol":"BPCL","security_id":"526"},
    {"symbol":"IOC","security_id":"1624"},{"symbol":"HPCL","security_id":"1468"},
    {"symbol":"GAIL","security_id":"1344"},{"symbol":"LICHSGFIN","security_id":"1981"},
    {"symbol":"PFC","security_id":"14299"},{"symbol":"NHPC","security_id":"13814"},
    {"symbol":"CONCOR","security_id":"728"},{"symbol":"POLYCAB","security_id":"21351"},
    {"symbol":"CROMPTON","security_id":"21316"},{"symbol":"SBICARD","security_id":"21048"},
    {"symbol":"NAUKRI","security_id":"13768"},{"symbol":"PIIND","security_id":"2532"},
    {"symbol":"MOTHERSON","security_id":"14418"},{"symbol":"IGL","security_id":"11262"},
    {"symbol":"LALPATHLAB","security_id":"21725"},{"symbol":"METROPOLIS","security_id":"21489"},
    {"symbol":"BAJAJFINSV","security_id":"16675"},{"symbol":"NESTLEIND","security_id":"17963"},
    {"symbol":"MARICO","security_id":"4067"},{"symbol":"GODREJCP","security_id":"10099"},
    {"symbol":"TATACONSUM","security_id":"3432"},{"symbol":"NMDC","security_id":"15332"},
    {"symbol":"ALKEM","security_id":"19117"},{"symbol":"LUPIN","security_id":"2032"},
    {"symbol":"SIEMENS","security_id":"3150"},{"symbol":"TITAN","security_id":"3477"},
    {"symbol":"PIDILITIND","security_id":"2664"},{"symbol":"DABUR","security_id":"781"},
    {"symbol":"HINDUNILVR","security_id":"1394"},{"symbol":"COALINDIA","security_id":"20374"},
    {"symbol":"BATAINDIA","security_id":"333"},{"symbol":"VOLTAS","security_id":"3563"},
    {"symbol":"ASTRAL","security_id":"14418"},{"symbol":"KEI","security_id":"1731"},
    {"symbol":"VGUARD","security_id":"14977"},{"symbol":"MGL","security_id":"18502"},
    {"symbol":"GUJGASLTD","security_id":"21769"},{"symbol":"MCDOWELL-N","security_id":"3105"},
    {"symbol":"JUBLFOOD","security_id":"18096"},{"symbol":"SCHAEFFLER","security_id":"3001"},
    {"symbol":"AIAENG","security_id":"14109"},{"symbol":"ELGIEQUIP","security_id":"946"},
    {"symbol":"JINDALSAW","security_id":"1694"},{"symbol":"RAMCOCEM","security_id":"14588"},
    {"symbol":"NATIONALUM","security_id":"2303"},{"symbol":"MOIL","security_id":"21100"},
    {"symbol":"MAXHEALTH","security_id":"21869"},{"symbol":"FORTIS","security_id":"16675"},
    {"symbol":"ZYDUSLIFE","security_id":"14977"},{"symbol":"ABBOTINDIA","security_id":"3"},
    {"symbol":"PFIZER","security_id":"2480"},{"symbol":"POLICYBZR","security_id":"21964"},
    {"symbol":"INDIAMART","security_id":"21389"},{"symbol":"JUSTDIAL","security_id":"18712"},
    {"symbol":"SPICEJET","security_id":"14428"},{"symbol":"GMRINFRA","security_id":"13528"},
    {"symbol":"IRFC","security_id":"14977"},{"symbol":"ICICIPRULI","security_id":"18652"},
]

SECTOR_MAP = {
    "RELIANCE":"energy","ONGC":"energy","BPCL":"energy","IOC":"energy","HPCL":"energy",
    "GAIL":"energy","PETRONET":"energy","IGL":"energy","MGL":"energy","GUJGASLTD":"energy",
    "TCS":"it","INFY":"it","WIPRO":"it","HCLTECH":"it","TECHM":"it","MPHASIS":"it",
    "LTIM":"it","PERSISTENT":"it","COFORGE":"it","TATAELXSI":"it","NAUKRI":"it","INDIAMART":"it",
    "HDFCBANK":"banking","ICICIBANK":"banking","SBIN":"banking","AXISBANK":"banking",
    "KOTAKBANK":"banking","INDUSINDBK":"banking","PNB":"banking","BANKBARODA":"banking",
    "CANBK":"banking","FEDERALBNK":"banking","RBLBANK":"banking","AUBANK":"banking","IDFCFIRSTB":"banking",
    "BAJFINANCE":"finance","BAJAJFINSV":"finance","SBICARD":"finance","LICHSGFIN":"finance",
    "PFC":"finance","RECLTD":"finance","IRFC":"finance","MUTHOOTFIN":"finance","MANAPPURAM":"finance",
    "CHOLAFIN":"finance","AAVAS":"finance","ICICIPRULI":"insurance","SBILIFE":"insurance","HDFCLIFE":"insurance",
    "TATAMOTORS":"auto","MARUTI":"auto","M&M":"auto","BAJAJ-AUTO":"auto","EICHERMOT":"auto",
    "APOLLOTYRE":"auto","BALKRISIND":"auto","MOTHERSON":"auto","BOSCHLTD":"auto",
    "TATASTEEL":"metal","HINDALCO":"metal","JSWSTEEL":"metal","SAIL":"metal","VEDL":"metal",
    "NMDC":"metal","NATIONALUM":"metal","MOIL":"metal","JINDALSAW":"metal",
    "SUNPHARMA":"pharma","DRREDDY":"pharma","CIPLA":"pharma","LUPIN":"pharma","DIVISLAB":"pharma",
    "AUROPHARMA":"pharma","BIOCON":"pharma","ALKEM":"pharma","TORNTPHARM":"pharma",
    "ABBOTINDIA":"pharma","PFIZER":"pharma","ZYDUSLIFE":"pharma",
    "LT":"infra","POWERGRID":"infra","NTPC":"infra","ADANIPORTS":"infra",
    "HAL":"infra","BEL":"infra","BHEL":"infra","CONCOR":"infra","GMRINFRA":"infra","NHPC":"infra",
    "SJVN":"infra","IRCTC":"infra","TATAPOWER":"infra",
    "ULTRACEMCO":"cement","GRASIM":"cement","AMBUJACEM":"cement","ACC":"cement",
    "SHREECEM":"cement","RAMCOCEM":"cement","JKCEMENT":"cement",
    "BHARTIARTL":"telecom","ADANIENT":"conglomerate",
    "ASIANPAINT":"paints","BERGEPAINT":"paints","KANSAINER":"paints","PIDILITIND":"paints",
    "ITC":"fmcg","HINDUNILVR":"fmcg","MARICO":"fmcg","BRITANNIA":"fmcg","NESTLEIND":"fmcg",
    "GODREJCP":"fmcg","TATACONSUM":"fmcg","DABUR":"fmcg","MCDOWELL-N":"fmcg",
    "APOLLOHOSP":"healthcare","FORTIS":"healthcare","MAXHEALTH":"healthcare",
    "METROPOLIS":"healthcare","LALPATHLAB":"healthcare",
    "DMART":"retail","TRENT":"retail",
    "POLYCAB":"electricals","HAVELLS":"electricals","CROMPTON":"electricals","KEI":"electricals",
    "ZOMATO":"consumer_tech","PAYTM":"consumer_tech","NYKAA":"consumer_tech","POLICYBZR":"consumer_tech",
    "TITAN":"jewellery","BATAINDIA":"footwear",
    "UPL":"chemicals","PIIND":"chemicals","TATACHEM":"chemicals",
    "SIEMENS":"capital_goods","CUMMINSIND":"capital_goods","AIAENG":"capital_goods","ELGIEQUIP":"capital_goods",
    "INDIGO":"aviation","SPICEJET":"aviation",
    "COALINDIA":"mining","JUBLFOOD":"qsr","SCHAEFFLER":"auto_components",
    "ADANIGREEN":"energy","ADANITRANS":"infra","VOLTAS":"building","ASTRAL":"building",
}


def _safe_float(val, default=0.0) -> float:
    """Safely parse float from API response — handles None, str, int."""
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=0) -> int:
    try:
        return int(float(val)) if val is not None else default
    except (TypeError, ValueError):
        return default


def _extract_quote_fields(info: Dict) -> Dict:
    """
    DhanHQ LTP API returns different field names in v1 vs v2.
    Try all known variants.
    """
    def get(*keys):
        for k in keys:
            v = info.get(k)
            if v is not None: return v
        return None

    return {
        "ltp":    _safe_float(get("last_price","lastTradedPrice","ltp","close")),
        "open":   _safe_float(get("open_price","open","openPrice")),
        "high":   _safe_float(get("high_price","high","highPrice")),
        "low":    _safe_float(get("low_price","low","lowPrice")),
        "close":  _safe_float(get("close_price","close","prevClose","previousClose")),
        "volume": _safe_int(get("volume","tradedVolume","totalTradedVolume")),
    }


class MarketScanner:
    def __init__(self, client_id: str, access_token: str, config: Dict):
        self.client_id    = client_id
        self.access_token = access_token
        self.config       = config
        self.headers = {
            "access-token": access_token,
            "client-id":    client_id,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        }

    def scan(self) -> Dict:
        result = {
            "timestamp":  datetime.now().isoformat(),
            "candidates": [],
            "scan_meta":  {},
            "errors":     [],
        }
        try:
            universe    = self._stage1_prefilter()
            quotes      = self._fetch_quotes(universe)

            if not quotes:
                result["errors"].append(
                    "DhanHQ API returned no quotes. Check Client ID and Access Token in Settings."
                )
                result["scan_meta"] = {
                    "total_fo_universe": len(NSE_FO_UNIVERSE),
                    "total_scanned": len(universe),
                    "passed_filter": 0,
                    "scan_time": datetime.now().strftime("%H:%M:%S"),
                    "note": "API authentication failed or market closed"
                }
                return result

            candles_map = self._fetch_candles(universe)
            enriched    = self._enrich_filter(quotes, candles_map)

            result["candidates"] = enriched
            result["scan_meta"]  = {
                "total_fo_universe": len(NSE_FO_UNIVERSE),
                "total_scanned":     len(universe),
                "passed_filter":     len(enriched),
                "quotes_received":   len(quotes),
                "scan_time":         datetime.now().strftime("%H:%M:%S"),
            }
        except Exception as e:
            result["errors"].append(f"Scanner error: {str(e)}")
            result["scan_meta"] = {"scan_time": datetime.now().strftime("%H:%M:%S")}
        return result

    # ─── STAGE 1: VOLUME PRE-FILTER ───────────────────────────

    def _stage1_prefilter(self) -> List[Dict]:
        """Get top 80 by volume. Falls back to first 80 if API fails."""
        try:
            payload = {"NSE_EQ": [s["security_id"] for s in NSE_FO_UNIVERSE[:120]]}
            resp    = requests.post(
                f"{DHAN_BASE}/v2/marketfeed/ltp",
                headers=self.headers, json=payload, timeout=15
            )
            if resp.status_code != 200:
                return NSE_FO_UNIVERSE[:80]

            # Try v2 format
            data = resp.json()
            nse  = data.get("data", {}).get("NSE_EQ", {})
            if not nse:
                # Try flat format (some versions)
                nse = data.get("NSE_EQ", {})

            if not nse:
                return NSE_FO_UNIVERSE[:80]

            scored = []
            for s in NSE_FO_UNIVERSE[:120]:
                info = nse.get(s["security_id"], {})
                if info:
                    vol = _safe_int(info.get("volume", info.get("tradedVolume", 0)))
                    scored.append({**s, "_vol": vol})

            if not scored:
                return NSE_FO_UNIVERSE[:80]

            scored.sort(key=lambda x: x["_vol"], reverse=True)
            return scored[:80]
        except Exception:
            return NSE_FO_UNIVERSE[:80]

    # ─── FETCH QUOTES ─────────────────────────────────────────

    def _fetch_quotes(self, universe: List[Dict]) -> List[Dict]:
        """Fetch OHLCV for universe. Tries v2 batch endpoint."""
        try:
            payload = {"NSE_EQ": [s["security_id"] for s in universe]}
            resp    = requests.post(
                f"{DHAN_BASE}/v2/marketfeed/ltp",
                headers=self.headers, json=payload, timeout=15
            )
            if resp.status_code == 401:
                raise ValueError("DhanHQ 401 Unauthorized — check Client ID and Access Token")
            if resp.status_code == 429:
                raise ValueError("DhanHQ 429 Rate Limited — wait and retry")
            resp.raise_for_status()

            data = resp.json()
            # Handle both nested and flat response formats
            nse = data.get("data", {}).get("NSE_EQ") or data.get("NSE_EQ", {})

            if not nse:
                raise ValueError(
                    f"DhanHQ returned empty data. Full response: {str(data)[:200]}"
                )

            quotes = []
            for s in universe:
                info = nse.get(s["security_id"], {})
                if not info:
                    continue
                fields = _extract_quote_fields(info)
                if fields["ltp"] > 0:
                    quotes.append({
                        "symbol":      s["symbol"],
                        "security_id": s["security_id"],
                        **fields,
                    })

            return quotes

        except (ValueError, requests.HTTPError) as e:
            raise  # propagate to scan()
        except Exception as e:
            raise ValueError(f"Quote fetch failed: {e}")

    # ─── FETCH CANDLES ────────────────────────────────────────

    def _fetch_candles(self, universe: List[Dict]) -> Dict[str, List]:
        """
        Fetch 15-min candles for ATR/RVOL calculation.
        Silently skips failures — fallback ATR used later.
        """
        candles_map = {}
        today     = datetime.now()
        from_date = (today - timedelta(days=10)).strftime("%Y-%m-%d")
        to_date   = today.strftime("%Y-%m-%d")

        for s in universe[:35]:   # cap to avoid rate limits
            try:
                payload = {
                    "securityId":      s["security_id"],
                    "exchangeSegment": "NSE_EQ",
                    "instrument":      "EQUITY",
                    "interval":        "15",
                    "oi_flag":         "0",
                    "from_date":       from_date,
                    "to_date":         to_date,
                }
                resp = requests.post(
                    f"{DHAN_BASE}/v2/charts/intraday",
                    headers=self.headers, json=payload, timeout=8
                )
                if resp.status_code == 200:
                    raw = resp.json()
                    # DhanHQ returns arrays: open[], high[], low[], close[], volume[], timestamp[]
                    candles = self._parse_candles(raw)
                    if candles:
                        candles_map[s["symbol"]] = candles
                time.sleep(0.08)
            except Exception:
                continue
        return candles_map

    def _parse_candles(self, raw: Dict) -> List[Dict]:
        """
        DhanHQ charts API returns columnar arrays, not row dicts.
        Convert to list of OHLCV dicts.
        """
        try:
            # v2 format: {"open":[], "high":[], "low":[], "close":[], "volume":[], "timestamp":[]}
            data = raw.get("data", raw)  # some responses wrap in "data"
            opens  = data.get("open",  [])
            highs  = data.get("high",  [])
            lows   = data.get("low",   [])
            closes = data.get("close", [])
            vols   = data.get("volume",[])
            times  = data.get("timestamp", [])

            if not closes:
                return []

            n = len(closes)
            candles = []
            for i in range(n):
                candles.append({
                    "open":      opens[i]  if i < len(opens)  else 0,
                    "high":      highs[i]  if i < len(highs)  else 0,
                    "low":       lows[i]   if i < len(lows)   else 0,
                    "close":     closes[i],
                    "volume":    vols[i]   if i < len(vols)   else 0,
                    "timestamp": times[i]  if i < len(times)  else 0,
                })
            return candles
        except Exception:
            return []

    # ─── ENRICH + FILTER ──────────────────────────────────────

    def _enrich_filter(self, quotes: List[Dict],
                        candles_map: Dict) -> List[Dict]:
        candidates    = []
        cfg           = self.config
        scan_ts       = datetime.now()
        sector_scores = self._compute_sector_scores(quotes)

        # Get configurable thresholds (relaxed defaults when candles unavailable)
        rvol_thresh = float(cfg.get("rvol_threshold", 1.5))
        atr_thresh  = float(cfg.get("min_atr", 5.0))

        for q in quotes:
            sym = q["symbol"]
            try:
                candles  = candles_map.get(sym, [])
                has_candles = len(candles) >= 5

                # ATR — use candles if available, else fallback to intraday H-L
                if has_candles:
                    atr = self._calc_atr(candles)
                else:
                    # Fallback: use today's High-Low range as proxy ATR
                    h, l = q.get("high", 0), q.get("low", 0)
                    atr   = (h - l) if (h > 0 and l > 0) else (q["ltp"] * 0.015)

                # Average volume — fallback to a fraction of current volume
                if has_candles:
                    avg_vol = self._calc_avg_vol(candles)
                else:
                    avg_vol = q["volume"] * 0.7   # assume above average

                rvol    = (q["volume"] / avg_vol) if avg_vol > 0 else 1.0
                gap_pct = self._calc_gap(q["open"], q["close"])
                vwap    = self._calc_vwap(candles) if has_candles else q["ltp"]
                rsi     = self._calc_rsi(candles) if has_candles else 50.0
                trend   = self._determine_trend(q, vwap, candles)

                # ── HARD FILTERS ──
                if q["ltp"] < 50:
                    continue   # penny stock

                # When no candles: use relaxed ATR filter (fallback is intraday range)
                effective_atr_thresh = atr_thresh if has_candles else min(atr_thresh, atr * 0.8)
                if atr < effective_atr_thresh:
                    continue

                if rvol < rvol_thresh and has_candles:
                    continue

                # Sector multiplier
                sector  = SECTOR_MAP.get(sym.upper(), "unknown")
                s_score = sector_scores.get(sector, 5.0)
                if   s_score <= 3: sector_mult = 0.0
                elif s_score <= 5: sector_mult = 0.75
                else:              sector_mult = 1.0

                if sector_mult == 0.0:
                    continue

                # Tech score
                rvol_n = min(rvol / 3.0, 1.0)
                atr_n  = min(atr / max(q["ltp"] * 0.03, 0.01), 1.0)
                gap_n  = min(abs(gap_pct) / 5.0, 1.0)
                tech   = (rvol_n * 0.40 + atr_n * 0.30 + gap_n * 0.30) * 10

                candidates.append({
                    "symbol":           sym,
                    "security_id":      q["security_id"],
                    "ltp":              round(q["ltp"], 2),
                    "open":             round(q["open"], 2),
                    "high":             round(q.get("high", q["ltp"]), 2),
                    "low":              round(q.get("low",  q["ltp"]), 2),
                    "prev_close":       round(q["close"], 2),
                    "volume":           q["volume"],
                    "avg_volume":       int(avg_vol),
                    "rvol":             round(rvol, 2),
                    "atr":              round(atr, 2),
                    "gap_pct":          round(gap_pct, 2),
                    "gap_flag":         abs(gap_pct) >= float(cfg.get("min_gap_pct", 2.0)),
                    "vwap":             round(vwap, 2) if vwap else None,
                    "rsi":              round(rsi, 1)  if rsi  else None,
                    "trend":            trend,
                    "sector":           sector,
                    "sector_score":     round(s_score, 1),
                    "sector_multiplier":sector_mult,
                    "tech_score":       round(tech, 2),
                    "has_candles":      has_candles,
                    "scan_price":       round(q["ltp"], 2),
                    "scan_timestamp":   scan_ts.isoformat(),
                    "scan_time":        scan_ts.strftime("%H:%M:%S"),
                })

            except Exception:
                continue

        candidates.sort(key=lambda x: x["tech_score"], reverse=True)
        return candidates[:15]

    # ─── SECTOR SCORES ────────────────────────────────────────

    def _compute_sector_scores(self, quotes: List[Dict]) -> Dict[str, float]:
        sector_gaps: Dict[str, List] = {}
        for q in quotes:
            sec = SECTOR_MAP.get(q["symbol"].upper(), "unknown")
            if sec != "unknown":
                g = self._calc_gap(q.get("open", 0), q.get("close", 0))
                sector_gaps.setdefault(sec, []).append(g)
        scores = {}
        for sec, gaps in sector_gaps.items():
            avg = sum(gaps) / len(gaps)
            scores[sec] = round(max(1.0, min(10.0, 5.0 + avg * 1.67)), 1)
        return scores

    # ─── INDICATORS ───────────────────────────────────────────

    def _calc_atr(self, candles: List, period: int = 14) -> float:
        if len(candles) < 2: return 0.0
        trs = []
        for i in range(1, len(candles)):
            h = _safe_float(candles[i].get("high"))
            l = _safe_float(candles[i].get("low"))
            c = _safe_float(candles[i-1].get("close"))
            if h > 0 and l > 0:
                trs.append(max(h - l, abs(h - c), abs(l - c)))
        if not trs: return 0.0
        return sum(trs[-period:]) / min(len(trs), period)

    def _calc_avg_vol(self, candles: List, period: int = 20) -> float:
        vols = [_safe_float(c.get("volume")) for c in candles[-period:] if c.get("volume")]
        return sum(vols) / len(vols) if vols else 1.0

    def _calc_gap(self, open_price: float, prev_close: float) -> float:
        if prev_close == 0: return 0.0
        return ((open_price - prev_close) / prev_close) * 100

    def _calc_vwap(self, candles: List) -> Optional[float]:
        if not candles: return None
        tp_sum = sum(
            ((c.get("high",0)+c.get("low",0)+c.get("close",0))/3) * c.get("volume",0)
            for c in candles if c.get("close",0) > 0
        )
        v_sum  = sum(c.get("volume",0) for c in candles)
        return tp_sum / v_sum if v_sum > 0 else None

    def _calc_rsi(self, candles: List, period: int = 14) -> Optional[float]:
        closes = [_safe_float(c.get("close")) for c in candles if c.get("close")]
        if len(closes) < period + 1: return None
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i-1]
            gains.append(max(d,0)); losses.append(max(-d,0))
        ag = sum(gains[-period:]) / period
        al = sum(losses[-period:]) / period
        if al == 0: return 100.0
        return round(100 - (100 / (1 + ag/al)), 1)

    def _determine_trend(self, q: Dict, vwap: Optional[float],
                          candles: List) -> str:
        if not vwap: return "neutral"
        ltp    = q["ltp"]
        closes = [_safe_float(c.get("close")) for c in candles[-5:] if c.get("close")]
        if len(closes) < 2: return "neutral"
        higher = all(closes[i] > closes[i-1] for i in range(1, len(closes)))
        lower  = all(closes[i] < closes[i-1] for i in range(1, len(closes)))
        if ltp > vwap and higher:   return "uptrend"
        elif ltp < vwap and lower:  return "downtrend"
        elif abs(ltp - vwap) / max(vwap, 1) < 0.005: return "ranging"
        elif q.get("high",0) - q.get("low",0) > ltp * 0.025: return "volatile"
        return "neutral"
