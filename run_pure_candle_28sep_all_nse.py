#!/usr/bin/env python3
"""
Pure Multi-TF Candle Pattern Scanner across ALL NSE Listed Stocks (~2,600+ symbols) AS OF 28-SEP-2026
Pattern: 1D GREEN + 1W GREEN + 1M GREEN + Previous Month RED (as of 28/09/2026)
"""

import os
import sys
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

from nse_delivery_multi_tf_tracker import fetch_all_mto
from whatsapp_notifier import send_telegram_file

def run_pure_candle_scan_28sep():
    ref_dt = datetime(2026, 9, 28)
    ref_date_str = ref_dt.strftime("%d-%b-%Y")
    
    print("\n" + "═" * 70)
    print(f"   🕯️ PURE MULTI-TF CANDLE SCANNER: ALL NSE STOCKS AS OF {ref_date_str}")
    print("   Pattern: 1D GREEN + 1W GREEN + 1M GREEN + Previous Month RED")
    print("═" * 70 + "\n")

    # 1. Download MTO Files (up to 28-Sep-2026)
    all_daily_dfs = fetch_all_mto(target_days=10)
    if not all_daily_dfs:
        print("❌ No MTO data downloaded.")
        return

    # Filter for dates <= 28092026
    daily_dfs = {k: v for k, v in all_daily_dfs.items() if k != "29092026"}
    date_keys = sorted(daily_dfs.keys(), key=lambda x: datetime.strptime(x, "%d%m%Y"), reverse=True)
    
    latest_key = date_keys[0] # 28092026
    all_symbols = sorted(daily_dfs[latest_key]["Symbol"].unique().tolist())
    print(f"📅 Primary Test Date: {latest_key} ({datetime.strptime(latest_key, '%d%m%Y').strftime('%d-%b-%Y')})")
    print(f"ℹ️ Found {len(all_symbols)} total active stock symbols in NSE database.\n")

    # 2. Download yfinance candles & slice <= 2026-09-28
    current_month_start = datetime(2026, 9, 1)
    prev_month_end = current_month_start - timedelta(days=1) # 2026-08-31
    prev_month_start = datetime(prev_month_end.year, prev_month_end.month, 1) # 2026-08-01
    current_week_start = ref_dt - timedelta(days=ref_dt.weekday()) # Monday 28-Sep-2026
    current_week_start = datetime(current_week_start.year, current_week_start.month, current_week_start.day)

    candle_results = []
    chunk_size = 400
    
    print(f"📈 Downloading & evaluating multi-timeframe candles for {len(all_symbols)} NSE stocks as of 28-Sep-2026...")
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

                if df_sym.empty:
                    continue

                # Clean NaNs and trim to <= 2026-09-28
                df_sym = df_sym.dropna(subset=["Close", "Open"]).sort_index()
                df_sym = df_sym[df_sym.index <= pd.Timestamp(ref_dt)]

                if len(df_sym) < 2:
                    continue

                # 1D Candle as of 28-Sep
                last_row = df_sym.iloc[-1]
                close_1d = float(last_row["Close"])
                open_1d  = float(last_row["Open"])
                is_1d_green = close_1d > open_1d

                # 1W Candle as of week of 28-Sep
                df_week = df_sym[df_sym.index >= pd.Timestamp(current_week_start)]
                if not df_week.empty:
                    open_1w  = float(df_week.iloc[0]["Open"])
                    close_1w = float(df_week.iloc[-1]["Close"])
                else:
                    open_1w  = float(df_sym.iloc[-min(5, len(df_sym))]["Open"])
                    close_1w = float(df_sym.iloc[-1]["Close"])
                is_1w_green = close_1w > open_1w

                # 1M Candle (September 2026)
                df_month = df_sym[df_sym.index >= pd.Timestamp(current_month_start)]
                if not df_month.empty:
                    open_1m  = float(df_month.iloc[0]["Open"])
                    close_1m = float(df_month.iloc[-1]["Close"])
                else:
                    open_1m  = float(df_sym.iloc[-min(20, len(df_sym))]["Open"])
                    close_1m = float(df_sym.iloc[-1]["Close"])
                is_1m_green = close_1m > open_1m

                # Prev 1M Candle (August 2026)
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
    print(f"📊 PURE MULTI-TF CANDLE SCAN RESULTS AS OF 28-SEP-2026:")
    print(f"   • Total NSE Stocks Evaluated: {len(df_all):,}")
    print(f"   • Matching Pattern (1D/1W/1M GREEN + Prev 1M RED): {len(df_matched)} stocks")
    print("═" * 70 + "\n")

    if not df_matched.empty:
        print(f"🏆 ALL STOCKS MATCHING CANDLE PATTERN ON 28-SEP-2026 ({len(df_matched)} STOCKS):")
        print(df_matched[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Prev 1M Candle", "1D %", "1W %", "1M %"]].to_string(index=False))
        print("\n")

    # Save to Excel
    out_dir = os.path.dirname(os.path.abspath(__file__))
    excel_file = os.path.join(out_dir, "pure_multi_tf_candle_pattern_ALL_NSE_20260928_TEST.xlsx")

    with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
        df_matched.to_excel(writer, sheet_name="Pattern Matched Stocks", index=False)
        df_all.to_excel(writer, sheet_name="All Evaluated Stocks", index=False)

    print(f"💾 Saved Excel Workbook: {excel_file}")

    # Dispatch via Telegram
    print("\n📤 Dispatching report to Telegram...")
    send_telegram_file(excel_file, f"🕯️ PURE MULTI-TF CANDLE PATTERN SCAN ({len(df_matched)} stocks) — 28-Sep-2026\n(1D GREEN + 1W GREEN + 1M GREEN + Prev 1M RED)")

    print("\n🎉 Pure Multi-TF Candle Scan for 28-Sep-2026 complete!")

if __name__ == "__main__":
    run_pure_candle_scan_28sep()
