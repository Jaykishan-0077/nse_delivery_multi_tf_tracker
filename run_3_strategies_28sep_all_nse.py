#!/usr/bin/env python3
"""
Full Market 3-Strategy Scanner across ALL NSE Listed Stocks (~2,600+ symbols) AS OF 28-SEP-2026
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

def run_3_strategies_scan_28sep():
    ref_dt = datetime(2026, 9, 28)
    ref_date_str = ref_dt.strftime("%d-%b-%Y")
    
    print("\n" + "═" * 70)
    print(f"   🌐 FULL MARKET 3-STRATEGY SCANNER: ALL NSE STOCKS AS OF {ref_date_str}")
    print("   Rules: Cond1 / Cond2 + 1D GREEN + 1W GREEN + 1M GREEN + Prev 1M RED")
    print("═" * 70 + "\n")

    # 1. Download MTO Files (up to 28-Sep-2026)
    all_daily_dfs = fetch_all_mto(target_days=35)
    if not all_daily_dfs:
        print("❌ No MTO data downloaded.")
        return

    # Filter out 29092026 to evaluate strictly as of 28-Sep-2026
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

    candle_dict = {}
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

    print(f"✅ Downloaded & evaluated candles for {len(candle_dict)} stocks as of 28-Sep-2026.\n")

    # 3. Compute Stats
    print("🔍 Screening ALL NSE stocks against Strategy Rules as of 28-Sep-2026...")
    results = []
    for sym in all_symbols:
        stats = compute_multi_tf_stats(sym, daily_dfs, candle_dict)
        if stats:
            results.append(stats)

    df_res = pd.DataFrame(results)

    # Filter DataFrames for each strategy
    vol_exp_df = df_res[df_res["Multi-TF Vol Expansion"] == "YES"].sort_values(by="Yest Volume", ascending=False)
    deliv_acc_df = df_res[df_res["Multi-TF Deliv Accumulation"] == "YES"].sort_values(by="Yest Deliv %", ascending=False)
    super_df = df_res[df_res["Multi-TF Super Signal"] == "YES"].sort_values(by="Yest Volume", ascending=False)

    print("\n" + "═" * 70)
    print(f"📊 FULL MARKET 3-STRATEGY SCAN RESULTS AS OF 28-SEP-2026:")
    print(f"   • Total NSE Stocks Analyzed: {len(df_res):,}")
    print(f"   • 1. Multi-TF Vol Expansion: {len(vol_exp_df)} stocks")
    print(f"   • 2. Multi-TF Deliv Accumulation: {len(deliv_acc_df)} stocks")
    print(f"   • 3. Multi-TF Super Signal: {len(super_df)} stocks")
    print("═" * 70 + "\n")

    if not super_df.empty:
        print("🏆 ALL NSE STOCKS MATCHING MULTI-TF SUPER SIGNAL ON 28-SEP-2026:")
        print(super_df[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Prev 1M Candle", "Yest Deliv %", "Yest Volume"]].to_string(index=False))
        print("\n")
    else:
        print("ℹ️ 0 stocks matched Multi-TF Super Signal on 28-Sep-2026.\n")

    if not vol_exp_df.empty:
        print(f"🚀 ALL NSE STOCKS MATCHING MULTI-TF VOLUME EXPANSION ON 28-SEP-2026 ({len(vol_exp_df)} STOCKS):")
        print(vol_exp_df[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Prev 1M Candle", "Yest Volume", "5D Avg Vol"]].head(15).to_string(index=False))
        print("\n")
    else:
        print("ℹ️ 0 stocks matched Multi-TF Volume Expansion on 28-Sep-2026.\n")

    if not deliv_acc_df.empty:
        print(f"📦 ALL NSE STOCKS MATCHING MULTI-TF DELIVERY ACCUMULATION ON 28-SEP-2026 ({len(deliv_acc_df)} STOCKS):")
        print(deliv_acc_df[["Symbol", "Price (₹)", "1D Candle", "1W Candle", "1M Candle", "Prev 1M Candle", "Yest Deliv %", "5D Deliv %"]].head(15).to_string(index=False))
        print("\n")
    else:
        print("ℹ️ 0 stocks matched Multi-TF Delivery Accumulation on 28-Sep-2026.\n")

    # 4. Save 3 Excel Workbooks for 28-Sep-2026
    out_dir = os.path.dirname(os.path.abspath(__file__))

    file_vol_exp = os.path.join(out_dir, "multi_tf_vol_expansion_ALL_NSE_20260928_TEST.xlsx")
    file_deliv_acc = os.path.join(out_dir, "multi_tf_deliv_accumulation_ALL_NSE_20260928_TEST.xlsx")
    file_super = os.path.join(out_dir, "multi_tf_super_signal_ALL_NSE_20260928_TEST.xlsx")

    with pd.ExcelWriter(file_vol_exp, engine="openpyxl") as writer:
        vol_exp_df.to_excel(writer, sheet_name="ALL NSE Vol Expansion", index=False)
        df_res.to_excel(writer, sheet_name="ALL NSE Market Database", index=False)

    with pd.ExcelWriter(file_deliv_acc, engine="openpyxl") as writer:
        deliv_acc_df.to_excel(writer, sheet_name="ALL NSE Deliv Accumulation", index=False)
        df_res.to_excel(writer, sheet_name="ALL NSE Market Database", index=False)

    with pd.ExcelWriter(file_super, engine="openpyxl") as writer:
        super_df.to_excel(writer, sheet_name="ALL NSE Super Signal", index=False)
        df_res.to_excel(writer, sheet_name="ALL NSE Market Database", index=False)

    print(f"💾 Saved 3 Excel Workbooks for 28-Sep-2026:")
    print(f"   1. {file_vol_exp}")
    print(f"   2. {file_deliv_acc}")
    print(f"   3. {file_super}\n")

    # 5. Dispatch via Telegram Bot
    print("📤 Dispatching 3 Strategy Reports for 28-Sep-2026 to Telegram...")
    send_telegram_file(file_vol_exp, f"🌐 28-SEP-2026 SCAN (1/3): Multi-TF Vol Expansion ({len(vol_exp_df)} stocks)")
    send_telegram_file(file_deliv_acc, f"🌐 28-SEP-2026 SCAN (2/3): Multi-TF Deliv Accumulation ({len(deliv_acc_df)} stocks)")
    send_telegram_file(file_super, f"🌐 28-SEP-2026 SCAN (3/3): Multi-TF Super Signal ({len(super_df)} stocks)")

    print("\n🎉 Full market scan for 28-Sep-2026 complete!")

if __name__ == "__main__":
    run_3_strategies_scan_28sep()
