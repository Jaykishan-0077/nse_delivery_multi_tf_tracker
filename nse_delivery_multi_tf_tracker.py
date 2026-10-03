#!/usr/bin/env python3
"""
NSE Delivery & Volume Expansion Multi-Timeframe Tracker (Nifty 500)
-------------------------------------------------------------------
Strategy Overview:
  1. Base Signal (Delivery Absorption + Volume Expansion):
     - Condition 1 (Deliv Absorption): 30D Avg Deliv % < 5D Avg Deliv % < Yesterday Deliv %
     - Condition 2 (Volume Expansion):  30D Avg Volume < 5D Avg Volume < Yesterday Volume
     - Strict Accumulation: Condition 1 == TRUE AND Condition 2 == TRUE

  2. Multi-Timeframe Candle Positivity Filter:
     - 1-Day (1D) Candle:  Yesterday Close > Yesterday Open  (Daily Green Candle)
     - 1-Week (1W) Candle: Current Week Close > Current Week Open (Weekly Green Candle)
     - 1-Month (1M) Candle: Current Month Close > Current Month Open (Monthly Green Candle)

  3. Multi-TF Super Signal:
     - Strict Accumulation == YES AND 1D == GREEN AND 1W == GREEN AND 1M == GREEN
"""

import os
import io
import sys
import argparse
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

def get_nifty500_symbols():
    """Fetch official Nifty 500 stock symbols."""
    urls = [
        "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://niftyindices.com/IndexAutomation-Concept/Indices/data/ind_nifty500list.csv",
        "https://raw.githubusercontent.com/anandkunal/indian-stock-market-symbols/main/nifty500.csv"
    ]
    for url in urls:
        try:
            req = requests.get(url, headers=NSE_HEADERS, timeout=10)
            if req.status_code == 200:
                df = pd.read_csv(io.StringIO(req.text), on_bad_lines='skip')
                for col in ["Symbol", "symbol", "SYMBOL", "Ticker"]:
                    if col in df.columns:
                        symbols = df[col].astype(str).str.strip().unique().tolist()
                        clean_syms = [s for s in symbols if s and s != "nan"]
                        if len(clean_syms) >= 100:
                            return sorted(clean_syms)
        except Exception:
            continue
            
    print("ℹ️ Extracting symbols directly from downloaded MTO files...")
    return None


def get_trading_days(count=30):
    """Generate potential NSE trading days going backwards from today."""
    days = []
    curr = datetime.now()
    while len(days) < count + 15:
        if curr.weekday() < 5:  # Mon-Fri
            days.append(curr.strftime("%d%m%Y"))
        curr -= timedelta(days=1)
    return days


def fetch_mto_for_date(date_str):
    """Download MTO file for a specific date (DDMMYYYY format)."""
    url = f"https://archives.nseindia.com/archives/equities/mto/MTO_{date_str}.DAT"
    try:
        resp = requests.get(url, headers=NSE_HEADERS, timeout=15)
        if resp.status_code == 200:
            lines = resp.text.splitlines()
            records = []
            for line in lines:
                if not line.startswith("20,"):
                    continue
                parts = line.split(",")
                if len(parts) >= 7:
                    try:
                        symbol = parts[2].strip()
                        series = parts[3].strip()
                        if series in ["EQ", "BE"]:
                            traded_qty = float(parts[4].strip())
                            deliv_qty = float(parts[5].strip())
                            deliv_pct = float(parts[6].strip())
                            records.append({
                                "Symbol": symbol,
                                "TradedQty": traded_qty,
                                "DelivQty": deliv_qty,
                                "DelivPct": deliv_pct
                            })
                    except (ValueError, IndexError):
                        continue
            if records:
                return pd.DataFrame(records)
    except Exception:
        pass
    return None


def fetch_all_mto(target_days=30):
    """Fetch MTO files for the last N valid NSE trading days."""
    dates_to_try = get_trading_days(target_days)
    daily_dfs = {}
    print(f"📥 Downloading NSE MTO delivery files (looking for {target_days} trading days)...\n")
    
    for date_str in dates_to_try:
        df = fetch_mto_for_date(date_str)
        if df is not None and not df.empty:
            dt_obj = datetime.strptime(date_str, "%d%m%Y")
            formatted_date = dt_obj.strftime("%d-%b-%Y (%a)")
            print(f"  📄  {formatted_date} ... ✅  {len(df):,} records")
            daily_dfs[date_str] = df
            if len(daily_dfs) >= target_days:
                break
                
    print(f"\n✅ Downloaded {len(daily_dfs)} trading day(s) of data.\n")
    return daily_dfs


def fetch_official_nse_bhavdata(date_str):
    """
    Fetch official NSE security bhavdata CSV for a specific date (DDMMYYYY format)
    to get exact, real-time official Open, High, Low, Close prices.
    """
    url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    try:
        resp = requests.get(url, headers=NSE_HEADERS, timeout=15)
        if resp.status_code == 200:
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = [c.strip() for c in df.columns]
            bhav_dict = {}
            dt_obj = datetime.strptime(date_str, "%d%m%Y")
            for idx, row in df.iterrows():
                sym = str(row.get("SYMBOL", "")).strip()
                series = str(row.get("SERIES", "")).strip()
                if series in ["EQ", "BE"]:
                    try:
                        bhav_dict[sym] = {
                            "Open": float(row["OPEN_PRICE"]),
                            "High": float(row["HIGH_PRICE"]),
                            "Low": float(row["LOW_PRICE"]),
                            "Close": float(row["CLOSE_PRICE"]),
                            "Date": dt_obj
                        }
                    except (ValueError, KeyError):
                        continue
            if bhav_dict:
                print(f"  📄 Loaded official NSE Bhavcopy prices for {len(bhav_dict):,} stocks on {dt_obj.strftime('%d-%b-%Y')}.")
                return bhav_dict
    except Exception:
        pass
    return {}


def fetch_multi_tf_candles(symbols, latest_bhav_dict=None):
    """
    Download daily OHLC price history for stock symbols via yfinance
    and calculate 1D, 1W, and 1M candle positivity (GREEN vs RED).
    Patches yfinance data with official NSE Bhavdata to ensure zero price lagging.
    """
    print(f"📈 Fetching multi-timeframe candle data for {len(symbols)} stocks via yfinance...")
    candle_dict = {}
    
    today_dt = datetime.now()
    current_month_start = datetime(today_dt.year, today_dt.month, 1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = datetime(prev_month_end.year, prev_month_end.month, 1)
    current_week_start = today_dt - timedelta(days=today_dt.weekday())  # Monday of current week
    current_week_start = datetime(current_week_start.year, current_week_start.month, current_week_start.day)
    prev_week_start = current_week_start - timedelta(days=7)

    chunk_size = 400
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        yf_symbols = [f"{s}.NS" for s in chunk]
        
        if len(symbols) > chunk_size:
            print(f"  Downloading candle chunk {i//chunk_size + 1}/{(len(symbols)-1)//chunk_size + 1} ({len(chunk)} symbols)...")
            
        try:
            data = yf.download(yf_symbols, period="6mo", interval="1d", group_by="ticker", progress=False, threads=True)
        except Exception as e:
            print(f"⚠️ Error downloading chunk: {e}")
            continue

        for sym in chunk:
            ticker = f"{sym}.NS"
            try:
                if ticker in data.columns.levels[0]:
                    df_sym = data[ticker].dropna(subset=["Close", "Open"]).copy()
                elif len(chunk) == 1:
                    df_sym = data.dropna(subset=["Close", "Open"]).copy()
                else:
                    continue

                if df_sym.empty:
                    continue

                # Filter out synthetic 0-volume holiday rows inserted by yfinance (e.g. market holidays)
                if "Volume" in df_sym.columns:
                    df_sym = df_sym[~((df_sym["Volume"] == 0) & (df_sym["Open"] == df_sym["Close"]))]

                # Patch/sync latest row with official NSE Bhavdata if available to prevent 1-day yfinance lag
                if latest_bhav_dict and sym in latest_bhav_dict:
                    b_info = latest_bhav_dict[sym]
                    latest_dt = pd.Timestamp(b_info["Date"])
                    if df_sym.empty or df_sym.index[-1] < latest_dt:
                        new_row = pd.DataFrame([{
                            "Open": b_info["Open"],
                            "High": b_info["High"],
                            "Low": b_info["Low"],
                            "Close": b_info["Close"],
                            "Volume": 0
                        }], index=[latest_dt])
                        df_sym = pd.concat([df_sym, new_row])
                    elif df_sym.index[-1] == latest_dt:
                        df_sym.loc[latest_dt, "Close"] = b_info["Close"]
                        df_sym.loc[latest_dt, "Open"]  = b_info["Open"]
                        df_sym.loc[latest_dt, "High"]  = b_info["High"]
                        df_sym.loc[latest_dt, "Low"]   = b_info["Low"]

                if len(df_sym) < 2:
                    continue

                # Ensure sorted index
                df_sym = df_sym.sort_index()

                # 1D Candle (Daily) - Most recent completed bar
                last_row = df_sym.iloc[-1]
                close_1d = float(last_row["Close"])
                open_1d  = float(last_row["Open"])
                is_1d_green = close_1d > open_1d

                # Prev 1D Candle (Previous Daily Bar)
                if len(df_sym) >= 2:
                    prev_1d_row = df_sym.iloc[-2]
                    close_prev_1d = float(prev_1d_row["Close"])
                    open_prev_1d  = float(prev_1d_row["Open"])
                    is_prev_1d_red = close_prev_1d < open_prev_1d
                    is_prev_1d_green = close_prev_1d > open_prev_1d
                else:
                    is_prev_1d_red = False
                    is_prev_1d_green = False

                # 1W Candle (Weekly) - Open of first trading day of current week vs Latest Close
                df_week = df_sym[df_sym.index >= pd.Timestamp(current_week_start)]
                if not df_week.empty:
                    open_1w  = float(df_week.iloc[0]["Open"])
                    close_1w = float(df_week.iloc[-1]["Close"])
                else:
                    open_1w  = float(df_sym.iloc[-min(5, len(df_sym))]["Open"])
                    close_1w = float(df_sym.iloc[-1]["Close"])
                is_1w_green = close_1w > open_1w

                # Prev 1W Candle (Previous Weekly) - Open vs Close of previous trading week
                df_prev_week = df_sym[(df_sym.index >= pd.Timestamp(prev_week_start)) & (df_sym.index < pd.Timestamp(current_week_start))]
                if not df_prev_week.empty:
                    open_prev_1w  = float(df_prev_week.iloc[0]["Open"])
                    close_prev_1w = float(df_prev_week.iloc[-1]["Close"])
                    is_prev_1w_red = close_prev_1w < open_prev_1w
                else:
                    is_prev_1w_red = False

                # 1M Candle (Current Monthly) - Open of first trading day of current month vs Latest Close
                df_month = df_sym[df_sym.index >= pd.Timestamp(current_month_start)]
                if not df_month.empty:
                    open_1m  = float(df_month.iloc[0]["Open"])
                    close_1m = float(df_month.iloc[-1]["Close"])
                else:
                    open_1m  = float(df_sym.iloc[-min(20, len(df_sym))]["Open"])
                    close_1m = float(df_sym.iloc[-1]["Close"])
                is_1m_green = close_1m > open_1m

                # Prev 1M Candle (Previous Monthly) - Open vs Close of previous calendar month
                df_prev_month = df_sym[(df_sym.index >= pd.Timestamp(prev_month_start)) & (df_sym.index <= pd.Timestamp(prev_month_end))]
                if not df_prev_month.empty:
                    open_prev_1m  = float(df_prev_month.iloc[0]["Open"])
                    close_prev_1m = float(df_prev_month.iloc[-1]["Close"])
                    is_prev_1m_red = close_prev_1m < open_prev_1m
                    is_prev_1m_green = close_prev_1m > open_prev_1m
                    vol_prev_1m   = float(df_prev_month["Volume"].sum())
                else:
                    is_prev_1m_red = False
                    is_prev_1m_green = False
                    vol_prev_1m = 0.0

                # Past completed months average volume calculation
                df_past_months = df_sym[df_sym.index < pd.Timestamp(current_month_start)]
                if not df_past_months.empty:
                    monthly_vols = df_past_months.groupby(pd.Grouper(freq="ME"))["Volume"].sum()
                    avg_monthly_vol = float(monthly_vols.mean()) if len(monthly_vols) > 0 else 0.0
                else:
                    avg_monthly_vol = 0.0

                is_prev_1m_vol_less = (vol_prev_1m > 0) and (avg_monthly_vol > 0) and (vol_prev_1m < avg_monthly_vol)

                candle_dict[sym] = {
                    "1D Candle": "GREEN" if is_1d_green else "RED",
                    "Prev 1D Candle": "RED" if is_prev_1d_red else ("GREEN" if is_prev_1d_green else "N/A"),
                    "1W Candle": "GREEN" if is_1w_green else "RED",
                    "Prev 1W Candle": "RED" if is_prev_1w_red else "GREEN",
                    "1M Candle": "GREEN" if is_1m_green else "RED",
                    "Prev 1M Candle": "GREEN" if is_prev_1m_green else ("RED" if is_prev_1m_red else "N/A"),
                    "Prev 1M Vol Less": is_prev_1m_vol_less,
                    "Prev 1M Vol": int(vol_prev_1m),
                    "Avg Monthly Vol": int(avg_monthly_vol),
                    "1D %": round(((close_1d - open_1d) / open_1d) * 100, 2),
                    "1W %": round(((close_1w - open_1w) / open_1w) * 100, 2),
                    "1M %": round(((close_1m - open_1m) / open_1m) * 100, 2),
                    "Latest Price": round(close_1d, 2)
                }
            except Exception:
                continue

    print(f"✅ Processed multi-timeframe candles for {len(candle_dict)} stocks.\n")
    return candle_dict


def compute_multi_tf_stats(symbol, daily_dfs, candle_dict):
    """
    Compute volume-weighted delivery % and volume averages for a symbol,
    and combine with multi-timeframe strategy rules.
    """
    date_keys = sorted(daily_dfs.keys(), key=lambda x: datetime.strptime(x, "%d%m%Y"), reverse=True)
    if not date_keys:
        return None

    symbol_history = []
    for d in date_keys:
        df = daily_dfs[d]
        row = df[df["Symbol"] == symbol]
        if not row.empty:
            r = row.iloc[0]
            symbol_history.append({
                "Date": d,
                "TradedQty": r["TradedQty"],
                "DelivQty": r["DelivQty"],
                "DelivPct": r["DelivPct"]
            })

    if len(symbol_history) < 5:
        return None

    # Yesterday = most recent day in history (Index 0)
    yest = symbol_history[0]
    yest_deliv_pct = yest["DelivPct"]
    yest_vol = yest["TradedQty"]

    # 5-Day Metrics (Volume-Weighted)
    h5 = symbol_history[:5]
    vol_5 = sum(x["TradedQty"] for x in h5)
    deliv_5 = sum(x["DelivQty"] for x in h5)
    avg_deliv_5 = (deliv_5 / vol_5 * 100) if vol_5 > 0 else 0.0
    avg_vol_5 = vol_5 / len(h5)

    # 30-Day Metrics (Volume-Weighted)
    h30 = symbol_history[:min(30, len(symbol_history))]
    vol_30 = sum(x["TradedQty"] for x in h30)
    deliv_30 = sum(x["DelivQty"] for x in h30)
    avg_deliv_30 = (deliv_30 / vol_30 * 100) if vol_30 > 0 else 0.0
    avg_vol_30 = vol_30 / len(h30)

    # Base Strategy Conditions
    cond1 = (avg_deliv_30 < avg_deliv_5) and (avg_deliv_5 < yest_deliv_pct)  # Deliv Inc
    cond2 = (avg_vol_30 < avg_vol_5) and (avg_vol_5 < yest_vol)              # Vol Exp
    cond_vol_dec = (avg_vol_30 > avg_vol_5) and (avg_vol_5 > yest_vol)      # Vol Dec (30D Vol > 5D Vol > Yest Vol)

    # Multi-Timeframe Candle Info
    c_info = candle_dict.get(symbol, {
        "1D Candle": "N/A", "Prev 1D Candle": "N/A", "1W Candle": "N/A", "Prev 1W Candle": "N/A", "1M Candle": "N/A", "Prev 1M Candle": "N/A",
        "Prev 1M Vol Less": False, "Prev 1M Vol": 0, "Avg Monthly Vol": 0,
        "1D %": 0.0, "1W %": 0.0, "1M %": 0.0, "Latest Price": 0.0
    })

    cand_1d = c_info["1D Candle"]
    cand_prev_1d = c_info.get("Prev 1D Candle", "N/A")
    cand_1w = c_info["1W Candle"]
    cand_prev_1w = c_info.get("Prev 1W Candle", "N/A")
    cand_1m = c_info["1M Candle"]
    cand_prev_1m = c_info.get("Prev 1M Candle", "N/A")

    # Candle Pattern Rules:
    pattern_prev_1m_red = (cand_1d == "GREEN") and (cand_1w == "GREEN") and (cand_1m == "GREEN") and (cand_prev_1m == "RED")
    pattern_prev_1w_red = (cand_1d == "GREEN") and (cand_1w == "GREEN") and (cand_prev_1w == "RED") and (cand_1m == "GREEN")
    pattern_3tf_green   = (cand_1d == "GREEN") and (cand_1w == "GREEN") and (cand_1m == "GREEN")
    pattern_5cond       = (cand_1d == "RED") and (cand_prev_1w == "RED") and (cand_1w == "GREEN") and (cand_prev_1m == "RED") and (cand_1m == "GREEN")
    pattern_strat9      = (cand_1m == "GREEN") and (cand_prev_1m == "GREEN") and c_info.get("Prev 1M Vol Less", False)
    pattern_strat10     = (cand_prev_1d == "RED") and (cand_1d == "GREEN") and (cand_prev_1w == "RED") and (cand_1w == "GREEN") and (cand_prev_1m == "RED") and (cand_1m == "GREEN")
    
    # Strategy Rules:
    # 1. Pure Vol Exp + Deliv Acc: Cond 2 AND Cond 1
    pure_vol_exp_deliv_acc = cond2 and cond1

    # 2. Pure Deliv Acc + Vol Dec: Cond 1 AND Vol Dec
    pure_deliv_acc_vol_dec = cond1 and cond_vol_dec

    # 3. Multi-TF Super Signal: Cond 2 AND Cond 1 AND (1D GREEN + 1W GREEN + 1M GREEN + Prev 1M RED)
    multi_tf_super_signal = cond2 and cond1 and pattern_prev_1m_red

    # 4. Multi-TF Deliv Accumulation: Cond 1 AND Vol Dec AND (1D GREEN + 1W GREEN + 1M GREEN + Prev 1M RED)
    multi_tf_deliv_accumulation = cond1 and cond_vol_dec and pattern_prev_1m_red

    # 5. Pure Candle Pattern (1D+1W+1M Green + Prev 1M Red)
    candle_pattern_prev_1m_red = pattern_prev_1m_red

    # 6. Candle Pattern (1D+1W+1M Green + Prev 1W Red)
    candle_pattern_prev_1w_red = pattern_prev_1w_red

    # 7. Pure 3-TF Green (1D+1W+1M Green)
    candle_pattern_3tf_green = pattern_3tf_green

    # 8. 5-Cond Candle Pattern (1D Red + Prev 1W Red + 1W Green + Prev 1M Red + 1M Green)
    candle_pattern_5cond = pattern_5cond

    # 9. 1M Green + Prev 1M Green + Prev 1M Vol Contraction
    candle_pattern_strat9 = pattern_strat9

    # 10. Prev 1D Red + 1D Green + Prev 1W Red + 1W Green + Prev 1M Red + 1M Green
    candle_pattern_strat10 = pattern_strat10

    return {
        "Symbol": symbol,
        "Price (₹)": c_info["Latest Price"],
        "1D Candle": cand_1d,
        "Prev 1D Candle": cand_prev_1d,
        "1W Candle": cand_1w,
        "Prev 1W Candle": cand_prev_1w,
        "1M Candle": cand_1m,
        "Prev 1M Candle": cand_prev_1m,
        "1D %": c_info["1D %"],
        "1W %": c_info["1W %"],
        "1M %": c_info["1M %"],
        "Yest Deliv %": round(yest_deliv_pct, 2),
        "5D Deliv %": round(avg_deliv_5, 2),
        "30D Deliv %": round(avg_deliv_30, 2),
        "Yest Volume": int(yest_vol),
        "5D Avg Vol": int(avg_vol_5),
        "30D Avg Vol": int(avg_vol_30),
        "Prev 1M Vol": c_info.get("Prev 1M Vol", 0),
        "Avg Monthly Vol": c_info.get("Avg Monthly Vol", 0),
        "Cond 1 (Deliv Inc)": cond1,
        "Cond 2 (Vol Exp)": cond2,
        "Vol Dec (30D>5D>Yest)": cond_vol_dec,
        "Pure Vol Exp + Deliv Acc": "YES" if pure_vol_exp_deliv_acc else "NO",
        "Pure Deliv Acc + Vol Dec": "YES" if pure_deliv_acc_vol_dec else "NO",
        "Multi-TF Super Signal": "YES" if multi_tf_super_signal else "NO",
        "Multi-TF Deliv Accumulation": "YES" if multi_tf_deliv_accumulation else "NO",
        "1D+1W+1M Green Prev 1M Red": "YES" if candle_pattern_prev_1m_red else "NO",
        "1D+1W+1M Green Prev 1W Red": "YES" if candle_pattern_prev_1w_red else "NO",
        "1D+1W+1M Green": "YES" if candle_pattern_3tf_green else "NO",
        "1D Red Prev 1W Red 1W Green Prev 1M Red 1M Green": "YES" if candle_pattern_5cond else "NO",
        "1M Green Prev 1M Green Vol Contraction": "YES" if candle_pattern_strat9 else "NO",
        "Prev 1D Red 1D Green Prev 1W Red 1W Green Prev 1M Red 1M Green": "YES" if candle_pattern_strat10 else "NO"
    }


def run_screener(target_trading_days=30):
    """Run full Nifty 500 screening for Multi-TF Delivery & Volume Expansion Strategy."""
    symbols = get_nifty500_symbols()
    if not symbols:
        print("❌ Failed to fetch symbol list.")
        return None

    daily_dfs = fetch_all_mto(target_days=target_trading_days)
    if not daily_dfs:
        print("❌ No MTO delivery data found.")
        return None

    latest_key = sorted(daily_dfs.keys(), key=lambda x: datetime.strptime(x, "%d%m%Y"), reverse=True)[0]
    latest_bhav_dict = fetch_official_nse_bhavdata(latest_key)

    # Load candle data for Nifty 500 symbols patched with official NSE Bhavdata
    candle_dict = fetch_multi_tf_candles(symbols, latest_bhav_dict=latest_bhav_dict)

    results = []
    print("🔍 Screening stocks for Multi-Timeframe Super Accumulation...")
    for sym in symbols:
        stats = compute_multi_tf_stats(sym, daily_dfs, candle_dict)
        if stats:
            results.append(stats)

    df_res = pd.DataFrame(results)
    return df_res


if __name__ == "__main__":
    df = run_screener(30)
    if df is not None and not df.empty:
        super_df = df[df["Multi-TF Super Signal"] == "YES"]
        print(f"\n📊 Screened {len(df)} stocks.")
        print(f"🌟 Multi-TF Super Accumulation Signals (Deliv Up + Vol Exp + 1D/1W/1M Green): {len(super_df)} stocks found.\n")
        if not super_df.empty:
            print(super_df[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Yest Deliv %", "Yest Volume"]].to_string(index=False))
