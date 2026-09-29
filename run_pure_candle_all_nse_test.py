#!/usr/bin/env python3
"""
One-time Pure Multi-Timeframe Candle Pattern Scanner across ALL NSE Listed Stocks (~2,600+ symbols)
Pattern: 1D GREEN AND 1W GREEN AND 1M GREEN AND Previous Month RED
"""

import os
import sys
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

from nse_delivery_multi_tf_tracker import fetch_all_mto
from whatsapp_notifier import send_telegram_file

def run_pure_candle_scan_all_nse():
    print("\n" + "═" * 70)
    print("   🕯️ PURE MULTI-TF CANDLE PATTERN SCANNER: ALL NSE LISTED STOCKS")
    print("   Pattern: 1D GREEN + 1W GREEN + 1M GREEN + Previous Month RED")
    print(f"   Run Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 70 + "\n")

    # 1. Download MTO Files to extract all active NSE symbols
    daily_dfs = fetch_all_mto(target_days=5)
    if not daily_dfs:
        print("❌ No MTO files downloaded.")
        return

    latest_key = sorted(daily_dfs.keys(), key=lambda x: datetime.strptime(x, "%d%m%Y"), reverse=True)[0]
    all_symbols = sorted(daily_dfs[latest_key]["Symbol"].unique().tolist())
    print(f"ℹ️ Found {len(all_symbols)} total active stock symbols in NSE database.\n")

    # 2. Download yfinance candle data in chunks
    today_dt = datetime.now()
    current_month_start = datetime(today_dt.year, today_dt.month, 1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = datetime(prev_month_end.year, prev_month_end.month, 1)
    current_week_start = today_dt - timedelta(days=today_dt.weekday())
    current_week_start = datetime(current_week_start.year, current_week_start.month, current_week_start.day)

    candle_results = []
    chunk_size = 400
    
    print(f"📈 Downloading & evaluating multi-timeframe candles for {len(all_symbols)} NSE stocks...")
    for i in range(0, len(all_symbols), chunk_size):
        chunk = all_symbols[i:i + chunk_size]
        yf_symbols = [f"{s}.NS" for s in chunk]
        print(f"  Processing chunk {i//chunk_size + 1}/{(len(all_symbols)-1)//chunk_size + 1} ({len(chunk)} symbols)...")
        
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

                is_match = is_1d_green and is_1w_green and is_1m_green and is_prev_1m_red

                candle_results.append({
                    "Symbol": sym,
                    "Price (₹)": round(close_1d, 2),
                    "1D Candle": "GREEN" if is_1d_green else "RED",
                    "1W Candle": "GREEN" if is_1w_green else "RED",
                    "1M Candle": "GREEN" if is_1m_green else "RED",
                    "Prev 1M Candle": "RED" if is_prev_1m_red else "GREEN",
                    "1D %": round(((close_1d - open_1d) / open_1d) * 100, 2),
                    "1W %": round(((close_1w - open_1w) / open_1w) * 100, 2),
                    "1M %": round(((close_1m - open_1m) / open_1m) * 100, 2),
                    "Pattern Match": "YES" if is_match else "NO"
                })
            except Exception:
                continue

    df_all = pd.DataFrame(candle_results)
    df_matched = df_all[df_all["Pattern Match"] == "YES"].sort_values(by="1D %", ascending=False)

    print("\n" + "═" * 70)
    print(f"📊 PURE MULTI-TF CANDLE SCAN RESULTS ({datetime.now().strftime('%d-%b-%Y')}):")
    print(f"   • Total NSE Stocks Evaluated: {len(df_all):,}")
    print(f"   • Matching Pattern (1D/1W/1M GREEN + Prev 1M RED): {len(df_matched)} stocks")
    print("═" * 70 + "\n")

    if not df_matched.empty:
        print(f"🏆 ALL STOCKS MATCHING CANDLE PATTERN ({len(df_matched)} STOCKS):")
        print(df_matched[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Prev 1M Candle", "1D %", "1W %", "1M %"]].to_string(index=False))
        print("\n")

    # Save to Excel
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M")
    date_str = datetime.now().strftime("%d-%b-%Y")
    out_dir = os.path.dirname(os.path.abspath(__file__))
    excel_file = os.path.join(out_dir, f"pure_multi_tf_candle_pattern_ALL_NSE_{timestamp_str}.xlsx")

    with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
        df_matched.to_excel(writer, sheet_name="Pattern Matched Stocks", index=False)
        df_all.to_excel(writer, sheet_name="All Evaluated Stocks", index=False)

    print(f"💾 Saved Excel Workbook: {excel_file}")

    # Dispatch via Telegram
    print("\n📤 Dispatching report to Telegram...")
    send_telegram_file(excel_file, f"🕯️ PURE MULTI-TF CANDLE PATTERN SCAN ({len(df_matched)} stocks) — {date_str}\n(1D GREEN + 1W GREEN + 1M GREEN + Prev 1M RED)")

    print("\n🎉 Pure Multi-TF Candle Scan complete!")

if __name__ == "__main__":
    run_pure_candle_scan_all_nse()
