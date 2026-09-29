#!/usr/bin/env python3
"""
One-time Multi-Timeframe Strategy Scanner across ALL NSE Listed Stocks (~2,600+ symbols)
"""

import os
import sys
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

from nse_delivery_multi_tf_tracker import (
    fetch_all_mto,
    compute_multi_tf_stats
)
from whatsapp_notifier import send_telegram_file

def fetch_multi_tf_candles_all(symbols):
    """
    Download yfinance candles for ~2,000+ symbols in chunked batches of 400.
    """
    print(f"📈 Downloading multi-timeframe OHLC data for ALL {len(symbols)} NSE stocks via yfinance...")
    
    today_dt = datetime.now()
    current_month_start = datetime(today_dt.year, today_dt.month, 1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = datetime(prev_month_end.year, prev_month_end.month, 1)
    current_week_start = today_dt - timedelta(days=today_dt.weekday())
    current_week_start = datetime(current_week_start.year, current_week_start.month, current_week_start.day)

    candle_dict = {}
    chunk_size = 400
    
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        yf_symbols = [f"{s}.NS" for s in chunk]
        print(f"  Downloading chunk {i//chunk_size + 1}/{(len(symbols)-1)//chunk_size + 1} ({len(chunk)} symbols)...")
        
        try:
            data = yf.download(yf_symbols, period="6mo", interval="1d", group_by="ticker", progress=False, threads=True)
        except Exception as e:
            print(f"  ⚠️ Error downloading chunk: {e}")
            continue

        for sym in chunk:
            ticker = f"{sym}.NS"
            try:
                if ticker in data.columns.levels[0]:
                    df_sym = data[ticker].dropna(how="all").copy()
                elif len(chunk) == 1:
                    df_sym = data.dropna(how="all").copy()
                else:
                    continue

                if df_sym.empty or len(df_sym) < 2:
                    continue

                df_sym = df_sym.sort_index()

                # 1D Candle
                last_row = df_sym.iloc[-1]
                close_1d = float(last_row["Close"])
                open_1d  = float(last_row["Open"])
                is_1d_green = close_1d > open_1d

                # 1W Candle
                df_week = df_sym[df_sym.index >= pd.Timestamp(current_week_start)]
                if not df_week.empty:
                    open_1w  = float(df_week.iloc[0]["Open"])
                    close_1w = float(df_week.iloc[-1]["Close"])
                else:
                    open_1w  = float(df_sym.iloc[-min(5, len(df_sym))]["Open"])
                    close_1w = float(df_sym.iloc[-1]["Close"])
                is_1w_green = close_1w > open_1w

                # 1M Candle (Current Month)
                df_month = df_sym[df_sym.index >= pd.Timestamp(current_month_start)]
                if not df_month.empty:
                    open_1m  = float(df_month.iloc[0]["Open"])
                    close_1m = float(df_month.iloc[-1]["Close"])
                else:
                    open_1m  = float(df_sym.iloc[-min(20, len(df_sym))]["Open"])
                    close_1m = float(df_sym.iloc[-1]["Close"])
                is_1m_green = close_1m > open_1m

                # Prev 1M Candle (Previous Month)
                df_prev_month = df_sym[(df_sym.index >= pd.Timestamp(prev_month_start)) & (df_sym.index <= pd.Timestamp(prev_month_end))]
                if not df_prev_month.empty:
                    open_prev_1m  = float(df_prev_month.iloc[0]["Open"])
                    close_prev_1m = float(df_prev_month.iloc[-1]["Close"])
                    is_prev_1m_red = close_prev_1m < open_prev_1m
                else:
                    is_prev_1m_red = False

                candle_dict[sym] = {
                    "1D Candle": "GREEN" if is_1d_green else "RED",
                    "1W Candle": "GREEN" if is_1w_green else "RED",
                    "1M Candle": "GREEN" if is_1m_green else "RED",
                    "Prev 1M Candle": "RED" if is_prev_1m_red else "GREEN",
                    "1D %": round(((close_1d - open_1d) / open_1d) * 100, 2),
                    "1W %": round(((close_1w - open_1w) / open_1w) * 100, 2),
                    "1M %": round(((close_1m - open_1m) / open_1m) * 100, 2),
                    "Latest Price": round(close_1d, 2)
                }
            except Exception:
                continue

    print(f"✅ Downloaded candle data for {len(candle_dict)} NSE stocks.\n")
    return candle_dict


def run_all_nse_scan():
    print("\n" + "═" * 70)
    print("   🌐 ONE-TIME SCANNER: ALL NSE LISTED STOCKS (~2,600+ SYMBOLS)")
    print(f"   Run Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 70 + "\n")

    # 1. Download MTO Files
    daily_dfs = fetch_all_mto(target_days=30)
    if not daily_dfs:
        print("❌ No MTO files downloaded.")
        return

    # Extract ALL unique equity symbols from latest MTO file
    latest_key = sorted(daily_dfs.keys(), key=lambda x: datetime.strptime(x, "%d%m%Y"), reverse=True)[0]
    all_symbols = sorted(daily_dfs[latest_key]["Symbol"].unique().tolist())
    print(f"ℹ️ Found {len(all_symbols)} total unique stock symbols in NSE MTO database.\n")

    # 2. Fetch Candle Data for ALL stocks
    candle_dict = fetch_multi_tf_candles_all(all_symbols)

    # 3. Compute Stats
    print("🔍 Screening ALL NSE stocks against Strategy Rules...")
    results = []
    for sym in all_symbols:
        stats = compute_multi_tf_stats(sym, daily_dfs, candle_dict)
        if stats:
            results.append(stats)

    df_res = pd.DataFrame(results)

    # Filter DataFrames
    vol_exp_df = df_res[df_res["Multi-TF Vol Expansion"] == "YES"]
    deliv_acc_df = df_res[df_res["Multi-TF Deliv Accumulation"] == "YES"]
    super_df = df_res[df_res["Multi-TF Super Signal"] == "YES"]

    print("\n" + "═" * 70)
    print(f"📊 FULL NSE MARKET SCAN RESULTS ({datetime.now().strftime('%d-%b-%Y')}):")
    print(f"   • Total NSE Stocks Analyzed: {len(df_res):,}")
    print(f"   • Multi-TF Vol Expansion (Cond2 + Cond1 + 1D/1W/1M Green + Prev1M Red): {len(vol_exp_df)} stocks")
    print(f"   • Multi-TF Deliv Accumulation (Cond1 + VolDec + 1D/1W/1M Green + Prev1M Red): {len(deliv_acc_df)} stocks")
    print(f"   • Multi-TF Super Signal (Both + 1D/1W/1M Green + Prev1M Red): {len(super_df)} stocks")
    print("═" * 70 + "\n")

    if not super_df.empty:
        print("🏆 ALL NSE STOCKS MATCHING MULTI-TF SUPER SIGNAL:")
        print(super_df[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Prev 1M Candle", "Yest Deliv %", "Yest Volume"]].to_string(index=False))
        print("\n")

    if not vol_exp_df.empty:
        print("🚀 ALL NSE STOCKS MATCHING MULTI-TF VOLUME EXPANSION:")
        print(vol_exp_df[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Prev 1M Candle", "Yest Volume", "5D Avg Vol"]].to_string(index=False))
        print("\n")

    if not deliv_acc_df.empty:
        print("📦 ALL NSE STOCKS MATCHING MULTI-TF DELIVERY ACCUMULATION:")
        print(deliv_acc_df[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Prev 1M Candle", "Yest Deliv %", "5D Deliv %"]].to_string(index=False))
        print("\n")

    # 4. Save 3 Excel Workbooks
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M")
    date_str = datetime.now().strftime("%d-%b-%Y")
    out_dir = os.path.dirname(os.path.abspath(__file__))

    file_vol_exp = os.path.join(out_dir, f"multi_tf_vol_expansion_ALL_NSE_{timestamp_str}.xlsx")
    file_deliv_acc = os.path.join(out_dir, f"multi_tf_deliv_accumulation_ALL_NSE_{timestamp_str}.xlsx")
    file_super = os.path.join(out_dir, f"multi_tf_super_signal_ALL_NSE_{timestamp_str}.xlsx")

    with pd.ExcelWriter(file_vol_exp, engine="openpyxl") as writer:
        vol_exp_df.to_excel(writer, sheet_name="ALL NSE Vol Expansion", index=False)
        df_res.to_excel(writer, sheet_name="ALL NSE Market Database", index=False)

    with pd.ExcelWriter(file_deliv_acc, engine="openpyxl") as writer:
        deliv_acc_df.to_excel(writer, sheet_name="ALL NSE Deliv Accumulation", index=False)
        df_res.to_excel(writer, sheet_name="ALL NSE Market Database", index=False)

    with pd.ExcelWriter(file_super, engine="openpyxl") as writer:
        super_df.to_excel(writer, sheet_name="ALL NSE Super Signal", index=False)
        df_res.to_excel(writer, sheet_name="ALL NSE Market Database", index=False)

    print(f"💾 Saved 3 Excel Workbooks for ALL NSE Stocks:")
    print(f"   1. {file_vol_exp}")
    print(f"   2. {file_deliv_acc}")
    print(f"   3. {file_super}\n")

    # 5. Dispatch via Telegram Bot
    print("📤 Dispatching ALL NSE stock reports to Telegram...")
    send_telegram_file(file_vol_exp, f"🌐 ALL NSE SCAN (1/3): Multi-TF Vol Expansion ({len(vol_exp_df)} stocks) — {date_str}")
    send_telegram_file(file_deliv_acc, f"🌐 ALL NSE SCAN (2/3): Multi-TF Deliv Accumulation ({len(deliv_acc_df)} stocks) — {date_str}")
    send_telegram_file(file_super, f"🌐 ALL NSE SCAN (3/3): Multi-TF Super Signal ({len(super_df)} stocks) — {date_str}")

    print("\n🎉 ALL NSE stock scan complete!")

if __name__ == "__main__":
    run_all_nse_scan()
