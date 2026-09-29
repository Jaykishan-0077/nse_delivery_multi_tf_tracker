#!/usr/bin/env python3
"""
Test Multi-Timeframe Strategy on Yesterday's Data (28/09/2026)
"""

import os
import sys
import pandas as pd
from datetime import datetime, timedelta

# Import functions from main module
from nse_delivery_multi_tf_tracker import (
    get_nifty500_symbols,
    fetch_all_mto,
    fetch_multi_tf_candles,
    compute_multi_tf_stats
)
from whatsapp_notifier import send_telegram_file, build_whatsapp_report

def run_test_as_of_28sep():
    print("\n" + "═" * 65)
    print("   🧪 RUNNING MULTI-TF TEST AS OF YESTERDAY (28-Sep-2026)")
    print("═" * 65 + "\n")

    symbols = get_nifty500_symbols()
    
    # 1. Fetch 30 days MTO data
    all_daily_dfs = fetch_all_mto(target_days=35)
    if not all_daily_dfs:
        print("❌ No MTO data downloaded.")
        return

    # Exclude 29092026 to test strictly AS OF 28-Sep-2026
    daily_dfs = {k: v for k, v in all_daily_dfs.items() if k != "29092026"}
    
    date_keys = sorted(daily_dfs.keys(), key=lambda x: datetime.strptime(x, "%d%m%Y"), reverse=True)
    print(f"📅 Primary Test Date (Yesterday): {date_keys[0]} ({datetime.strptime(date_keys[0], '%d%m%Y').strftime('%d-%b-%Y')})")
    print(f"📊 Historical Days Loaded: {len(date_keys)} trading days (from {date_keys[0]} back to {date_keys[-1]})\n")

    # 2. Fetch Multi-TF Candles and trim to <= 2026-09-28
    print("📈 Fetching and trimming yfinance candle data up to 2026-09-28...")
    import yfinance as yf
    yf_symbols = [f"{s}.NS" for s in symbols]
    data = yf.download(yf_symbols, period="6mo", interval="1d", group_by="ticker", progress=False)
    
    ref_dt = datetime(2026, 9, 28)
    current_month_start = datetime(2026, 9, 1)
    current_week_start = ref_dt - timedelta(days=ref_dt.weekday())  # Monday of week of Sep 28
    current_week_start = datetime(current_week_start.year, current_week_start.month, current_week_start.day)

    candle_dict = {}
    for sym in symbols:
        ticker = f"{sym}.NS"
        try:
            if ticker in data.columns.levels[0]:
                df_sym = data[ticker].dropna(how="all").copy()
            elif len(symbols) == 1:
                df_sym = data.dropna(how="all").copy()
            else:
                continue

            if df_sym.empty:
                continue

            df_sym = df_sym.sort_index()
            # Trim data to <= 2026-09-28
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

            # 1M Candle as of month of Sep 2026
            df_month = df_sym[df_sym.index >= pd.Timestamp(current_month_start)]
            if not df_month.empty:
                open_1m  = float(df_month.iloc[0]["Open"])
                close_1m = float(df_month.iloc[-1]["Close"])
            else:
                open_1m  = float(df_sym.iloc[-min(20, len(df_sym))]["Open"])
                close_1m = float(df_sym.iloc[-1]["Close"])
            is_1m_green = close_1m > open_1m

            # Prev 1M Candle (August 2026)
            prev_month_end = current_month_start - timedelta(days=1)
            prev_month_start = datetime(prev_month_end.year, prev_month_end.month, 1)
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

    print(f"✅ Processed trimmed candles for {len(candle_dict)} stocks as of 28-Sep-2026.\n")

    # 3. Compute stats
    results = []
    for sym in symbols:
        stats = compute_multi_tf_stats(sym, daily_dfs, candle_dict)
        if stats:
            results.append(stats)

    df_res = pd.DataFrame(results)

    # Filter DataFrames
    vol_exp_df = df_res[df_res["Multi-TF Vol Expansion"] == "YES"]
    deliv_acc_df = df_res[df_res["Multi-TF Deliv Accumulation"] == "YES"]
    super_df = df_res[df_res["Multi-TF Super Signal"] == "YES"]

    print("═" * 65)
    print(f"📊 SUMMARY AS OF 28-SEP-2026:")
    print(f"   • Total Stocks Screened: {len(df_res)}")
    print(f"   • Multi-TF Vol Expansion: {len(vol_exp_df)} stocks")
    print(f"   • Multi-TF Deliv Accumulation: {len(deliv_acc_df)} stocks")
    print(f"   • Multi-TF Super Signal: {len(super_df)} stocks")
    print("═" * 65 + "\n")

    if not super_df.empty:
        print("🏆 STOCKS MATCHING MULTI-TF SUPER SIGNAL ON 28-SEP-2026:")
        print(super_df[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Yest Deliv %", "Yest Volume"]].to_string(index=False))
        print("\n")
    if not vol_exp_df.empty:
        print("📈 TOP MULTI-TF VOL EXPANSION STOCKS ON 28-SEP-2026:")
        print(vol_exp_df[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Yest Volume", "5D Avg Vol"]].head(10).to_string(index=False))
        print("\n")

    # 4. Generate 3 files for 28-Sep-2026
    out_dir = os.path.dirname(os.path.abspath(__file__))
    file_vol_exp = os.path.join(out_dir, "multi_tf_vol_expansion_nifty500_20260928_TEST.xlsx")
    file_deliv_acc = os.path.join(out_dir, "multi_tf_deliv_accumulation_nifty500_20260928_TEST.xlsx")
    file_super = os.path.join(out_dir, "multi_tf_super_signal_nifty500_20260928_TEST.xlsx")

    with pd.ExcelWriter(file_vol_exp, engine="openpyxl") as writer:
        vol_exp_df.to_excel(writer, sheet_name="Multi-TF Vol Expansion", index=False)
        df_res.to_excel(writer, sheet_name="Nifty 500 All Signals", index=False)

    with pd.ExcelWriter(file_deliv_acc, engine="openpyxl") as writer:
        deliv_acc_df.to_excel(writer, sheet_name="Multi-TF Deliv Accumulation", index=False)
        df_res.to_excel(writer, sheet_name="Nifty 500 All Signals", index=False)

    with pd.ExcelWriter(file_super, engine="openpyxl") as writer:
        super_df.to_excel(writer, sheet_name="Multi-TF Super Signal", index=False)
        df_res.to_excel(writer, sheet_name="Nifty 500 All Signals", index=False)

    print(f"💾 Saved 3 Test Files for 28-Sep-2026:")
    print(f"   1. {file_vol_exp}")
    print(f"   2. {file_deliv_acc}")
    print(f"   3. {file_super}\n")

    # 5. Dispatch via Telegram
    print("📤 Dispatching test files for 28-Sep-2026 to Telegram...")
    send_telegram_file(file_vol_exp, f"🧪 TEST (28-Sep-2026) 1/3: Multi-TF Vol Expansion ({len(vol_exp_df)} stocks)")
    send_telegram_file(file_deliv_acc, f"🧪 TEST (28-Sep-2026) 2/3: Multi-TF Deliv Accumulation ({len(deliv_acc_df)} stocks)")
    send_telegram_file(file_super, f"🧪 TEST (28-Sep-2026) 3/3: Multi-TF Super Signal ({len(super_df)} stocks)")

    print("\n✅ Test run for 28-Sep-2026 complete!")

if __name__ == "__main__":
    run_test_as_of_28sep()
