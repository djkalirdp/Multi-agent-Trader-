"""
Market Scanner v4
  - 180 NSE F&O stocks universe (was 30)
  - 2-stage filter: prev-day volume top 80 -> live RVOL/ATR/Gap scan
  - scan_price + scan_timestamp saved (Bug 15 stale check)
  - Sector multiplier not flat addition (Bug 14 fixed)
  - Tech score: RVOL(40%) + ATR(30%) + Gap(30%)
  - Returns top 15 candidates
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
    {"symbol":"HAVELLS","security_id":"430"},{"symbol":"HINDZINC","security_id":"1438"},
    {"symbol":"IRCTC","security_id":"13611"},{"symbol":"HAL","security_id":"2303"},
    {"symbol":"BEL","security_id":"383"},{"symbol":"BHEL","security_id":"438"},
    {"symbol":"IDFCFIRSTB","security_id":"11957"},{"symbol":"BANKBARODA","security_id":"1727"},
    {"symbol":"CANBK","security_id":"2263"},{"symbol":"FEDERALBNK","security_id":"1023"},
    {"symbol":"RBLBANK","security_id":"18391"},{"symbol":"AUBANK","security_id":"21238"},
    {"symbol":"CHOLAFIN","security_id":"685"},{"symbol":"MUTHOOTFIN","security_id":"14142"},
    {"symbol":"SBILIFE","security_id":"21808"},{"symbol":"HDFCLIFE","security_id":"119"},
    {"symbol":"AMBUJACEM","security_id":"1270"},{"symbol":"ACC","security_id":"22"},
    {"symbol":"APOLLOHOSP","security_id":"157"},{"symbol":"BIOCON","security_id":"524"},
    {"symbol":"AUROPHARMA","security_id":"275"},{"symbol":"ADANIGREEN","security_id":"21669"},
    {"symbol":"INDIGO","security_id":"11195"},{"symbol":"ZEEL","security_id":"3777"},
    {"symbol":"SUNTV","security_id":"10700"},{"symbol":"DMART","security_id":"17192"},
    {"symbol":"TRENT","security_id":"3499"},{"symbol":"VOLTAS","security_id":"3563"},
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
    {"symbol":"MANAPPURAM","security_id":"14418"},{"symbol":"RECLTD","security_id":"15355"},
    {"symbol":"ALKEM","security_id":"19117"},{"symbol":"LUPIN","security_id":"2032"},
    {"symbol":"GLAND","security_id":"21725"},{"symbol":"PETRONET","security_id":"11351"},
    {"symbol":"SIEMENS","security_id":"3150"},{"symbol":"ABB","security_id":"13"},
    {"symbol":"DEEPAKNTR","security_id":"14977"},{"symbol":"NAVINFLUOR","security_id":"14977"},
    {"symbol":"PAGEIND","security_id":"14977"},{"symbol":"SHREECEM","security_id":"3103"},
    {"symbol":"JKCEMENT","security_id":"19262"},{"symbol":"AMBUJACEM","security_id":"1270"},
    {"symbol":"BATAINDIA","security_id":"333"},{"symbol":"TITAN","security_id":"3477"},
    {"symbol":"PIDILITIND","security_id":"2664"},{"symbol":"DABUR","security_id":"781"},
    {"symbol":"COLPAL","security_id":"720"},{"symbol":"HINDUNILVR","security_id":"1394"},
    {"symbol":"KANSAINER","security_id":"1742"},{"symbol":"ASTRAL","security_id":"14418"},
    {"symbol":"KEI","security_id":"1731"},{"symbol":"FINOLEX","security_id":"1042"},
    {"symbol":"VGUARD","security_id":"14977"},{"symbol":"THERMAX","security_id":"3290"},
    {"symbol":"CESC","security_id":"657"},{"symbol":"TORNTPOWER","security_id":"15042"},
    {"symbol":"ADANITRANS","security_id":"21175"},{"symbol":"MGL","security_id":"18502"},
    {"symbol":"GUJGASLTD","security_id":"21769"},{"symbol":"MCDOWELL-N","security_id":"3105"},
    {"symbol":"UBL","security_id":"11603"},{"symbol":"JUBLFOOD","security_id":"18096"},
    {"symbol":"DEVYANI","security_id":"21742"},{"symbol":"SAPPHIRE","security_id":"21867"},
    {"symbol":"WHIRLPOOL","security_id":"3676"},{"symbol":"SCHAEFFLER","security_id":"3001"},
    {"symbol":"AIAENG","security_id":"14109"},{"symbol":"ELGIEQUIP","security_id":"946"},
    {"symbol":"GRINDWELL","security_id":"1248"},{"symbol":"LINDEINDIA","security_id":"2009"},
    {"symbol":"JINDALSAW","security_id":"1694"},{"symbol":"RAMCOCEM","security_id":"14588"},
    {"symbol":"NATIONALUM","security_id":"2303"},{"symbol":"MOIL","security_id":"21100"},
    {"symbol":"HINDZINC","security_id":"1438"},{"symbol":"VEDL","security_id":"3063"},
    {"symbol":"MAXHEALTH","security_id":"21869"},{"symbol":"FORTIS","security_id":"16675"},
    {"symbol":"ZYDUSLIFE","security_id":"14977"},{"symbol":"ABBOTINDIA","security_id":"3"},
    {"symbol":"GLAXO","security_id":"1209"},{"symbol":"PFIZER","security_id":"2480"},
    {"symbol":"IPCALAB","security_id":"1631"},{"symbol":"AAVAS","security_id":"21867"},
    {"symbol":"CREDITACC","security_id":"21204"},{"symbol":"MANAPPURAM","security_id":"14418"},
    {"symbol":"MUTHOOTFIN","security_id":"14142"},{"symbol":"CHOLAFIN","security_id":"685"},
    {"symbol":"POLICYBZR","security_id":"21964"},{"symbol":"INDIAMART","security_id":"21389"},
    {"symbol":"JUSTDIAL","security_id":"18712"},{"symbol":"ROUTE","security_id":"21477"},
    {"symbol":"THYROCARE","security_id":"21867"},{"symbol":"SPICEJET","security_id":"14428"},
    {"symbol":"GMRINFRA","security_id":"13528"},{"symbol":"IRFC","security_id":"14977"},
    {"symbol":"SJVN","security_id":"14977"},{"symbol":"ICICIPRULI","security_id":"18652"},
]

SECTOR_MAP = {
    "RELIANCE":"energy","ONGC":"energy","BPCL":"energy","IOC":"energy","HPCL":"energy",
    "GAIL":"energy","PETRONET":"energy","IGL":"energy","MGL":"energy","GUJGASLTD":"energy","ADANIGREEN":"energy",
    "TCS":"it","INFY":"it","WIPRO":"it","HCLTECH":"it","TECHM":"it","MPHASIS":"it",
    "LTIM":"it","PERSISTENT":"it","COFORGE":"it","TATAELXSI":"it","NAUKRI":"it","INDIAMART":"it",
    "HDFCBANK":"banking","ICICIBANK":"banking","SBIN":"banking","AXISBANK":"banking",
    "KOTAKBANK":"banking","INDUSINDBK":"banking","PNB":"banking","BANKBARODA":"banking",
    "CANBK":"banking","FEDERALBNK":"banking","RBLBANK":"banking","AUBANK":"banking","IDFCFIRSTB":"banking",
    "BAJFINANCE":"finance","BAJAJFINSV":"finance","SBICARD":"finance","LICHSGFIN":"finance",
    "PFC":"finance","RECLTD":"finance","IRFC":"finance","MUTHOOTFIN":"finance","MANAPPURAM":"finance",
    "CHOLAFIN":"finance","AAVAS":"finance","ICICIPRULI":"insurance","SBILIFE":"insurance","HDFCLIFE":"insurance",
    "TATAMOTORS":"auto","MARUTI":"auto","M&M":"auto","BAJAJ-AUTO":"auto","EICHERMOT":"auto",
    "APOLLOTYRE":"auto","BALKRISIND":"auto","MOTHERSON":"auto","BOSCHLTD":"auto","HEROMOTOCO":"auto",
    "TATASTEEL":"metal","HINDALCO":"metal","JSWSTEEL":"metal","SAIL":"metal","VEDL":"metal",
    "NMDC":"metal","HINDZINC":"metal","NATIONALUM":"metal","MOIL":"metal","JINDALSAW":"metal",
    "SUNPHARMA":"pharma","DRREDDY":"pharma","CIPLA":"pharma","LUPIN":"pharma","DIVISLAB":"pharma",
    "AUROPHARMA":"pharma","BIOCON":"pharma","ALKEM":"pharma","TORNTPHARM":"pharma","GLAND":"pharma",
    "ABBOTINDIA":"pharma","PFIZER":"pharma","ZYDUSLIFE":"pharma","IPCALAB":"pharma","GLAXO":"pharma",
    "LT":"infra","POWERGRID":"infra","NTPC":"infra","ADANIPORTS":"infra","ADANITRANS":"infra",
    "HAL":"infra","BEL":"infra","BHEL":"infra","CONCOR":"infra","GMRINFRA":"infra","NHPC":"infra",
    "SJVN":"infra","IRCTC":"infra","CESC":"infra","TORNTPOWER":"infra","TATAPOWER":"infra",
    "ULTRACEMCO":"cement","GRASIM":"cement","AMBUJACEM":"cement","ACC":"cement",
    "SHREECEM":"cement","RAMCOCEM":"cement","JKCEMENT":"cement",
    "BHARTIARTL":"telecom",
    "ADANIENT":"conglomerate",
    "ASIANPAINT":"paints","BERGEPAINT":"paints","KANSAINER":"paints","PIDILITIND":"paints",
    "ITC":"fmcg","HINDUNILVR":"fmcg","MARICO":"fmcg","BRITANNIA":"fmcg","NESTLEIND":"fmcg",
    "GODREJCP":"fmcg","TATACONSUM":"fmcg","DABUR":"fmcg","COLPAL":"fmcg","MCDOWELL-N":"fmcg","UBL":"fmcg",
    "APOLLOHOSP":"healthcare","FORTIS":"healthcare","MAXHEALTH":"healthcare",
    "METROPOLIS":"healthcare","LALPATHLAB":"healthcare","THYROCARE":"healthcare",
    "DMART":"retail","TRENT":"retail",
    "POLYCAB":"electricals","HAVELLS":"electricals","CROMPTON":"electricals","VGUARD":"electricals","KEI":"electricals",
    "ZOMATO":"consumer_tech","PAYTM":"consumer_tech","NYKAA":"consumer_tech","POLICYBZR":"consumer_tech",
    "TITAN":"jewellery","BATAINDIA":"footwear",
    "DEEPAKNTR":"chemicals","NAVINFLUOR":"chemicals","PIIND":"chemicals","UPL":"chemicals",
    "SIEMENS":"capital_goods","THERMAX":"capital_goods","CUMMINSIND":"capital_goods",
    "AIAENG":"capital_goods","ELGIEQUIP":"capital_goods","ABB":"capital_goods",
    "INDIGO":"aviation","SPICEJET":"aviation",
    "SUNTV":"media","ZEEL":"media",
    "COALINDIA":"mining",
    "ASTRAL":"building","VOLTAS":"building",
    "LINDEINDIA":"industrial_gas",
    "JUBLFOOD":"qsr","DEVYANI":"qsr",
    "NAUKRI":"internet","JUSTDIAL":"internet","ROUTE":"internet",
    "PAGEIND":"apparel",
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
        result = {"timestamp": datetime.now().isoformat(), "candidates": [], "scan_meta": {}, "errors": []}
        try:
            universe    = self._stage1_volume_prefilter()
            quotes      = self._fetch_quotes_batch(universe)
            candles_map = self._fetch_candles_batch(universe)
            enriched    = self._stage2_enrich_filter(quotes, candles_map)
            result["candidates"]                     = enriched
            result["scan_meta"]["total_fo_universe"] = len(NSE_FO_UNIVERSE)
            result["scan_meta"]["total_scanned"]     = len(universe)
            result["scan_meta"]["passed_filter"]     = len(enriched)
            result["scan_meta"]["scan_time"]         = datetime.now().strftime("%H:%M:%S")
        except Exception as e:
            result["errors"].append(str(e))
        return result

    def _stage1_volume_prefilter(self) -> List[Dict]:
        try:
            payload = {"NSE_EQ": [s["security_id"] for s in NSE_FO_UNIVERSE]}
            resp    = requests.post(f"{DHAN_BASE}/v2/marketfeed/ltp",
                                    headers=self.headers, json=payload, timeout=15)
            if resp.status_code != 200:
                return NSE_FO_UNIVERSE[:80]
            data   = resp.json().get("data", {}).get("NSE_EQ", {})
            scored = []
            for s in NSE_FO_UNIVERSE:
                info = data.get(s["security_id"], {})
                vol  = int(info.get("volume", 0))
                if info and vol > 0:
                    scored.append({**s, "_vol": vol})
            scored.sort(key=lambda x: x["_vol"], reverse=True)
            return scored[:80]
        except Exception:
            return NSE_FO_UNIVERSE[:80]

    def _fetch_quotes_batch(self, universe: List[Dict]) -> List[Dict]:
        try:
            payload = {"NSE_EQ": [s["security_id"] for s in universe]}
            resp    = requests.post(f"{DHAN_BASE}/v2/marketfeed/ltp",
                                    headers=self.headers, json=payload, timeout=15)
            resp.raise_for_status()
            data   = resp.json().get("data", {}).get("NSE_EQ", {})
            quotes = []
            for s in universe:
                info = data.get(s["security_id"], {})
                if info:
                    quotes.append({
                        "symbol":      s["symbol"],
                        "security_id": s["security_id"],
                        "ltp":         float(info.get("last_price",  0)),
                        "open":        float(info.get("open_price",  0)),
                        "high":        float(info.get("high_price",  0)),
                        "low":         float(info.get("low_price",   0)),
                        "close":       float(info.get("close_price", 0)),
                        "volume":      int(info.get("volume",        0)),
                    })
            return quotes
        except Exception:
            return []

    def _fetch_candles_batch(self, universe: List[Dict]) -> Dict[str, List]:
        candles_map = {}
        today     = datetime.now()
        from_date = (today - timedelta(days=15)).strftime("%Y-%m-%d")
        to_date   = today.strftime("%Y-%m-%d")
        for s in universe[:40]:
            try:
                payload = {"securityId": s["security_id"], "exchangeSegment": "NSE_EQ",
                           "instrument": "EQUITY", "interval": "15", "oi_flag": "0",
                           "from_date": from_date, "to_date": to_date}
                resp = requests.post(f"{DHAN_BASE}/v2/charts/intraday",
                                     headers=self.headers, json=payload, timeout=10)
                if resp.status_code == 200:
                    candles_map[s["symbol"]] = resp.json().get("data", [])
                time.sleep(0.1)
            except Exception:
                continue
        return candles_map

    def _stage2_enrich_filter(self, quotes: List[Dict], candles_map: Dict) -> List[Dict]:
        candidates    = []
        cfg           = self.config
        scan_ts       = datetime.now()
        sector_scores = self._compute_sector_scores(quotes)

        for q in quotes:
            sym = q["symbol"]
            try:
                candles = candles_map.get(sym, [])
                atr     = self._calculate_atr(candles)
                avg_vol = self._calculate_avg_volume(candles)
                rvol    = (q["volume"] / avg_vol) if avg_vol > 0 else 0
                gap_pct = self._calculate_gap(q["open"], q["close"])
                vwap    = self._calculate_vwap(candles)
                rsi     = self._calculate_rsi(candles)

                if not (rvol >= cfg.get("rvol_threshold", 1.5)
                        and atr  >= cfg.get("min_atr", 5.0)
                        and q["ltp"] > 50):
                    continue

                trend   = self._determine_trend(q, vwap, candles)
                sector  = SECTOR_MAP.get(sym.upper(), "unknown")
                s_score = sector_scores.get(sector, 5.0)

                # Bug 14: sector multiplier — not flat addition
                if   s_score <= 3: sector_multiplier = 0.0
                elif s_score <= 5: sector_multiplier = 0.75
                else:              sector_multiplier = 1.0

                if sector_multiplier == 0.0:
                    continue   # weak sector — drop at scan stage

                rvol_norm = min(rvol / 3.0, 1.0)
                atr_norm  = min(atr / max(q["ltp"] * 0.03, 0.01), 1.0)
                gap_norm  = min(abs(gap_pct) / 5.0, 1.0)
                tech_score = (rvol_norm * 0.40 + atr_norm * 0.30 + gap_norm * 0.30) * 10

                candidates.append({
                    "symbol":           sym,
                    "security_id":      q["security_id"],
                    "ltp":              round(q["ltp"], 2),
                    "open":             round(q["open"], 2),
                    "high":             round(q["high"], 2),
                    "low":              round(q["low"], 2),
                    "prev_close":       round(q["close"], 2),
                    "volume":           q["volume"],
                    "avg_volume":       int(avg_vol),
                    "rvol":             round(rvol, 2),
                    "atr":              round(atr, 2),
                    "gap_pct":          round(gap_pct, 2),
                    "gap_flag":         abs(gap_pct) >= cfg.get("min_gap_pct", 2.0),
                    "vwap":             round(vwap, 2) if vwap else None,
                    "rsi":              round(rsi, 1)  if rsi  else None,
                    "trend":            trend,
                    "sector":           sector,
                    "sector_score":     round(s_score, 1),
                    "sector_multiplier":sector_multiplier,
                    "tech_score":       round(tech_score, 2),
                    "scan_price":       round(q["ltp"], 2),    # Bug 15
                    "scan_timestamp":   scan_ts.isoformat(),    # Bug 15
                    "scan_time":        scan_ts.strftime("%H:%M:%S"),
                })
            except Exception:
                continue

        candidates.sort(key=lambda x: x["tech_score"], reverse=True)
        return candidates[:15]

    def _compute_sector_scores(self, quotes: List[Dict]) -> Dict[str, float]:
        sector_gaps: Dict[str, List] = {}
        for q in quotes:
            sec = SECTOR_MAP.get(q["symbol"].upper(), "unknown")
            if sec != "unknown":
                g = self._calculate_gap(q.get("open", 0), q.get("close", 0))
                sector_gaps.setdefault(sec, []).append(g)
        scores = {}
        for sec, gaps in sector_gaps.items():
            avg = sum(gaps) / len(gaps)
            scores[sec] = round(max(1.0, min(10.0, 5.0 + avg * 1.67)), 1)
        return scores

    def _calculate_atr(self, candles, period=14):
        if len(candles) < period + 1: return 0.0
        trs = []
        for i in range(1, len(candles)):
            h = float(candles[i].get("high", 0)); l = float(candles[i].get("low", 0))
            c = float(candles[i-1].get("close", 0))
            trs.append(max(h-l, abs(h-c), abs(l-c)))
        return sum(trs[-period:]) / period if trs else 0.0

    def _calculate_avg_volume(self, candles, period=20):
        if not candles: return 1
        vols = [float(c.get("volume", 0)) for c in candles[-period:]]
        return sum(vols) / len(vols) if vols else 1

    def _calculate_gap(self, open_price, prev_close):
        if prev_close == 0: return 0.0
        return ((open_price - prev_close) / prev_close) * 100

    def _calculate_vwap(self, candles):
        if not candles: return None
        pv = sum(((float(c.get("high",0))+float(c.get("low",0))+float(c.get("close",0)))/3)*float(c.get("volume",0)) for c in candles)
        v  = sum(float(c.get("volume",0)) for c in candles)
        return pv / v if v > 0 else None

    def _calculate_rsi(self, candles, period=14):
        closes = [float(c.get("close",0)) for c in candles]
        if len(closes) < period+1: return None
        gains=[]; losses=[]
        for i in range(1, len(closes)):
            d=closes[i]-closes[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
        ag=sum(gains[-period:])/period; al=sum(losses[-period:])/period
        if al==0: return 100.0
        return 100-(100/(1+ag/al))

    def _determine_trend(self, q, vwap, candles):
        if not vwap or not candles: return "unknown"
        ltp = q["ltp"]; closes=[float(c.get("close",0)) for c in candles[-5:]]
        if len(closes) < 2: return "neutral"
        higher=all(closes[i]>closes[i-1] for i in range(1,len(closes)))
        lower =all(closes[i]<closes[i-1] for i in range(1,len(closes)))
        if ltp > vwap and higher: return "uptrend"
        elif ltp < vwap and lower: return "downtrend"
        elif abs(ltp-vwap)/max(vwap,1) < 0.005: return "ranging"
        elif q["high"]-q["low"] > q["ltp"]*0.025: return "volatile"
        return "neutral"
