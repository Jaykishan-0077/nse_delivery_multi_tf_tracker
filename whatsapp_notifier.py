#!/usr/bin/env python3
"""
NSE Multi-Timeframe Delivery & Volume Expansion Tracker — Notifier
-------------------------------------------------------------------
Runs daily, screens Nifty 500 stocks for Delivery Absorption + Volume Expansion +
1D, 1W, and 1M Positive Candle trends, and dispatches native Excel workbooks
via Telegram Bot API and Meta WhatsApp Cloud API at 9:00 PM IST.
"""

import os
import sys
import argparse
import requests
import pandas as pd
from datetime import datetime

# Import core scanner
from nse_delivery_multi_tf_tracker import (
    get_nifty500_symbols,
    fetch_all_mto,
    fetch_official_nse_bhavdata,
    fetch_multi_tf_candles,
    compute_multi_tf_stats
)

# ──────────────────────────────────────────────────────────────
# CONFIGURATION (Meta Official API & Telegram)
# ──────────────────────────────────────────────────────────────
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "1245645765305543")
META_ACCESS_TOKEN    = os.environ.get("META_ACCESS_TOKEN", "EAAZASTyCbQ10BSRxUSwZCZBrk6CzKCyHMDkaYq0QcLD8l6c1R69Jk1SRXPpTS2PXBgnjPZALsgQKBfeTZBJleq5OEpAC16FgZAb9g3sM0t9X9LZBj7ZAqw78hj2WR9UAL5GjYrBuNLhr1xnBaJaQWva1eAyvYMgyFHQHZBttZAXoawjOeDcloSK2zCARMaRFoM5wZDZD")
RECIPIENT_PHONE      = os.environ.get("RECIPIENT_PHONE", "919898501383")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8989474593:AAGITtd0pWZrHZXqQZjX5JUvgsBYZFATdxA")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "1948266239")


# ──────────────────────────────────────────────────────────────
# TELEGRAM BOT API
# ──────────────────────────────────────────────────────────────
def send_telegram_file(file_path: str, caption: str = "") -> bool:
    """Send Excel workbook directly to user via Telegram Bot API with retries."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    for attempt in range(1, 4):
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(url, data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=60)
                if resp.status_code == 200:
                    print(f"✅ Sent Excel report via Telegram Bot! ({os.path.basename(file_path)})")
                    return True
                else:
                    print(f"⚠️ Telegram API status {resp.status_code} (attempt {attempt}/3): {resp.text}")
        except Exception as e:
            print(f"⚠️ Telegram send attempt {attempt}/3 error: {e}")
        import time; time.sleep(2)
    return False


# ──────────────────────────────────────────────────────────────
# META OFFICIAL WHATSAPP CLOUD API
# ──────────────────────────────────────────────────────────────
def upload_media_meta(file_path, mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
    """Upload media file to Meta WhatsApp Cloud API."""
    url = f"https://graph.facebook.com/v20.0/{META_PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
    
    try:
        with open(file_path, "rb") as f:
            files = {
                "file": (os.path.basename(file_path), f, mime_type),
                "messaging_product": (None, "whatsapp")
            }
            r = requests.post(url, files=files, headers=headers, timeout=30)
            if r.status_code in [200, 201]:
                media_id = r.json().get("id")
                print(f"✅ Uploaded media to Meta Cloud API (Media ID: {media_id})")
                return media_id
            else:
                print(f"⚠️ Meta Upload Error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"⚠️ Error uploading file to Meta: {e}")
    return None


def send_whatsapp_template_meta(media_id, excel_file, report_text):
    """Send Meta Approved Utility Template message."""
    url = f"https://graph.facebook.com/v20.0/{META_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Sanitize parameter text: remove newlines & excessive whitespace
    clean_param_text = " ".join(report_text.replace("\n", " ").split())
    
    payload = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_PHONE,
        "type": "template",
        "template": {
            "name": "nse_daily_report",
            "language": {"code": "en_US"},
            "components": [
                {
                    "type": "header",
                    "parameters": [
                        {
                            "type": "document",
                            "document": {
                                "id": media_id,
                                "filename": os.path.basename(excel_file)
                            }
                        }
                    ]
                },
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": datetime.now().strftime("%d-%b-%Y")},
                        {"type": "text", "text": clean_param_text[:900]}
                    ]
                }
            ]
        }
    }
    
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code in [200, 201]:
            print("✅ Meta Official WhatsApp Template sent successfully!")
            return True
        else:
            print(f"⚠️ Meta Template API Status {r.status_code}: {r.text}")
    except Exception as e:
        print(f"⚠️ Exception sending Meta Template: {e}")
    return False


def build_whatsapp_report(df_all, df_n500):
    """Format summary message for WhatsApp and Telegram."""
    date_str = datetime.now().strftime("%d-%b-%Y")
    f1_df = df_n500[df_n500["Pure Vol Exp + Deliv Acc"] == "YES"]
    f2_df = df_n500[df_n500["Pure Deliv Acc + Vol Dec"] == "YES"]
    f3_df = df_n500[df_n500["Multi-TF Super Signal"] == "YES"]
    f4_df = df_n500[df_n500["Multi-TF Deliv Accumulation"] == "YES"]
    f5_df = df_all[df_all["1D+1W+1M Green Prev 1M Red"] == "YES"]
    f6_df = df_all[df_all["1D+1W+1M Green Prev 1W Red"] == "YES"]
    f7_df = df_all[df_all["1D+1W+1M Green"] == "YES"]
    f8_df = df_all[df_all["1D Red Prev 1W Red 1W Green Prev 1M Red 1M Green"] == "YES"]
    f9_df = df_all[df_all["1M Green Prev 1M Green Vol Contraction"] == "YES"]
    
    msg = f"🌟 *NSE DAILY 9-STRATEGY SCANNER REPORT* ({date_str})\n"
    msg += f"─────────────────────────────────────────────\n"
    msg += f"🔍 Total Stocks Analyzed: {len(df_all)} (Nifty 500: {len(df_n500)})\n"
    msg += f"1️⃣ *Pure Vol Exp + Deliv Acc (Nifty 500)*: {len(f1_df)} stocks\n"
    msg += f"2️⃣ *Pure Deliv Acc + Vol Dec (Nifty 500)*: {len(f2_df)} stocks\n"
    msg += f"3️⃣ *Multi-TF Super Signal (Nifty 500)*: {len(f3_df)} stocks\n"
    msg += f"4️⃣ *Multi-TF Deliv Acc + Vol Dec (Nifty 500)*: {len(f4_df)} stocks\n"
    msg += f"5️⃣ *1D+1W+1M Green + Prev 1M Red (ALL NSE)*: {len(f5_df)} stocks\n"
    msg += f"6️⃣ *1D+1W+1M Green + Prev 1W Red (ALL NSE)*: {len(f6_df)} stocks\n"
    msg += f"7️⃣ *1D+1W+1M Green (ALL NSE)*: {len(f7_df)} stocks\n"
    msg += f"8️⃣ *1D Red + Prev 1W Red + 1W Green + Prev 1M Red + 1M Green (ALL NSE)*: {len(f8_df)} stocks\n"
    msg += f"9️⃣ *1M Green + Prev 1M Green + Vol Contraction (ALL NSE)*: {len(f9_df)} stocks\n\n"
    
    if not f3_df.empty:
        msg += f"🏆 *TOP MULTI-TF SUPER SIGNALS (File 3)*:\n"
        for idx, row in f3_df.head(5).iterrows():
            msg += f"• *{row['Symbol']}* (₹{row['Price (₹)']}): Deliv {row['Yest Deliv %']}% | Vol {row['Yest Volume']:,} | 🟢 1D 1W 1M | 🔴 Prev 1M\n"
        msg += "\n"
    elif not f5_df.empty:
        msg += f"🕯️ *TOP CANDLE PATTERN STOCKS (File 5)*:\n"
        for idx, row in f5_df.head(5).iterrows():
            msg += f"• *{row['Symbol']}* (₹{row['Price (₹)']}): 🟢 1D ({row['1D %']}%) 1W ({row['1W %']}%) 1M ({row['1M %']}%) | 🔴 Prev 1M\n"
        msg += "\n"
            
    msg += f"📁 9 separate strategy Excel files attached below."
    return msg


# ──────────────────────────────────────────────────────────────
# MAIN PIPELINE & NOTIFICATION
# ──────────────────────────────────────────────────────────────
def run_daily_notification():
    print("\n" + "═" * 65)
    print("   💬 NSE MULTI-TIMEFRAME SCANNER NOTIFIER (9:05 PM IST)")
    print(f"   Run Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 65 + "\n")

    # Fetch Nifty 500 symbol list
    nifty500_symbols = set(get_nifty500_symbols() or [])

    # Fetch MTO delivery files for last 30 trading days
    daily_dfs = fetch_all_mto(target_days=30)
    if not daily_dfs:
        print("❌ No MTO files downloaded.")
        return

    # Extract all active NSE symbols from MTO files (~2,670 stocks)
    latest_key = sorted(daily_dfs.keys(), key=lambda x: datetime.strptime(x, "%d%m%Y"), reverse=True)[0]
    all_nse_symbols = sorted(daily_dfs[latest_key]["Symbol"].unique().tolist())
    print(f"ℹ️ Loaded {len(all_nse_symbols)} active symbols from NSE MTO delivery database.")
    print(f"ℹ️ Loaded {len(nifty500_symbols)} official Nifty 500 stock symbols.")

    # Fetch official NSE Bhavcopy prices for the latest trading day to ensure zero price lag
    latest_bhav_dict = fetch_official_nse_bhavdata(latest_key)

    # Fetch candle data for ALL NSE symbols patched with official NSE prices
    candle_dict = fetch_multi_tf_candles(all_nse_symbols, latest_bhav_dict=latest_bhav_dict)

    results = []
    for sym in all_nse_symbols:
        stats = compute_multi_tf_stats(sym, daily_dfs, candle_dict)
        if stats:
            stats["In Nifty 500"] = "YES" if sym in nifty500_symbols else "NO"
            results.append(stats)

    df_all = pd.DataFrame(results)
    df_n500 = df_all[df_all["In Nifty 500"] == "YES"]

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M")
    date_str = datetime.now().strftime("%d-%b-%Y")
    out_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Filter DataFrames for each of the 9 strategies:
    # Files 1, 2, 3, 4: Restricted to NIFTY 500 STOCKS
    f1_df = df_n500[df_n500["Pure Vol Exp + Deliv Acc"] == "YES"]
    f2_df = df_n500[df_n500["Pure Deliv Acc + Vol Dec"] == "YES"]
    f3_df = df_n500[df_n500["Multi-TF Super Signal"] == "YES"]
    f4_df = df_n500[df_n500["Multi-TF Deliv Accumulation"] == "YES"]

    # Files 5, 6, 7, 8, 9: Scans ALL ~2,670 NSE STOCKS
    f5_df = df_all[df_all["1D+1W+1M Green Prev 1M Red"] == "YES"]
    f6_df = df_all[df_all["1D+1W+1M Green Prev 1W Red"] == "YES"]
    f7_df = df_all[df_all["1D+1W+1M Green"] == "YES"]
    f8_df = df_all[df_all["1D Red Prev 1W Red 1W Green Prev 1M Red 1M Green"] == "YES"]
    f9_df = df_all[df_all["1M Green Prev 1M Green Vol Contraction"] == "YES"]

    # File 1: Pure Vol Expansion + Deliv Accumulation (Nifty 500)
    file_1 = os.path.join(out_dir, f"pure_vol_exp_deliv_acc_nifty500_{timestamp_str}.xlsx")
    with pd.ExcelWriter(file_1, engine="openpyxl") as writer:
        f1_df.to_excel(writer, sheet_name="Pure Vol Exp + Deliv Acc", index=False)
        df_n500.to_excel(writer, sheet_name="Nifty 500 All Signals", index=False)

    # File 2: Pure Deliv Accumulation + Vol Contraction (Nifty 500)
    file_2 = os.path.join(out_dir, f"pure_deliv_acc_vol_contraction_nifty500_{timestamp_str}.xlsx")
    with pd.ExcelWriter(file_2, engine="openpyxl") as writer:
        f2_df.to_excel(writer, sheet_name="Pure Deliv Acc + Vol Dec", index=False)
        df_n500.to_excel(writer, sheet_name="Nifty 500 All Signals", index=False)

    # File 3: Multi-TF Super Signal (Nifty 500)
    file_3 = os.path.join(out_dir, f"multi_tf_super_signal_nifty500_{timestamp_str}.xlsx")
    with pd.ExcelWriter(file_3, engine="openpyxl") as writer:
        f3_df.to_excel(writer, sheet_name="Multi-TF Super Signal", index=False)
        df_n500.to_excel(writer, sheet_name="Nifty 500 All Signals", index=False)

    # File 4: Multi-TF Delivery Accumulation (Nifty 500)
    file_4 = os.path.join(out_dir, f"multi_tf_deliv_accumulation_nifty500_{timestamp_str}.xlsx")
    with pd.ExcelWriter(file_4, engine="openpyxl") as writer:
        f4_df.to_excel(writer, sheet_name="Multi-TF Deliv Accumulation", index=False)
        df_n500.to_excel(writer, sheet_name="Nifty 500 All Signals", index=False)

    # File 5: 1D+1W+1M Green + Prev 1M Red (ALL NSE STOCKS)
    file_5 = os.path.join(out_dir, f"pure_multi_tf_candle_pattern_ALL_NSE_{timestamp_str}.xlsx")
    with pd.ExcelWriter(file_5, engine="openpyxl") as writer:
        f5_df.to_excel(writer, sheet_name="1D+1W+1M Green Prev 1M Red", index=False)
        df_all.to_excel(writer, sheet_name="ALL NSE Stocks Signals", index=False)

    # File 6: 1D+1W+1M Green + Prev 1W Red (ALL NSE STOCKS)
    file_6 = os.path.join(out_dir, f"candle_pattern_prev_1w_red_ALL_NSE_{timestamp_str}.xlsx")
    with pd.ExcelWriter(file_6, engine="openpyxl") as writer:
        f6_df.to_excel(writer, sheet_name="1D+1W+1M Green Prev 1W Red", index=False)
        df_all.to_excel(writer, sheet_name="ALL NSE Stocks Signals", index=False)

    # File 7: 1D+1W+1M Green (ALL NSE STOCKS)
    file_7 = os.path.join(out_dir, f"pure_3tf_green_candle_ALL_NSE_{timestamp_str}.xlsx")
    with pd.ExcelWriter(file_7, engine="openpyxl") as writer:
        f7_df.to_excel(writer, sheet_name="1D+1W+1M Green", index=False)
        df_all.to_excel(writer, sheet_name="ALL NSE Stocks Signals", index=False)

    # File 8: 1D Red + Prev 1W Red + 1W Green + Prev 1M Red + 1M Green (ALL NSE STOCKS)
    file_8 = os.path.join(out_dir, f"candle_pattern_1d_red_prev_1w_red_1w_green_prev_1m_red_1m_green_ALL_NSE_{timestamp_str}.xlsx")
    with pd.ExcelWriter(file_8, engine="openpyxl") as writer:
        f8_df.to_excel(writer, sheet_name="5-Cond Candle Pattern", index=False)
        df_all.to_excel(writer, sheet_name="ALL NSE Stocks Signals", index=False)

    # File 9: 1M Green + Prev 1M Green + Vol Contraction (ALL NSE STOCKS)
    file_9 = os.path.join(out_dir, f"candle_pattern_1m_green_prev_1m_green_vol_contraction_ALL_NSE_{timestamp_str}.xlsx")
    with pd.ExcelWriter(file_9, engine="openpyxl") as writer:
        f9_df.to_excel(writer, sheet_name="1M Green Prev 1M Green Vol Cont", index=False)
        df_all.to_excel(writer, sheet_name="ALL NSE Stocks Signals", index=False)

    print(f"💾 Saved 9 Strategy Files:")
    print(f"   1. {file_1} ({len(f1_df)} stocks)")
    print(f"   2. {file_2} ({len(f2_df)} stocks)")
    print(f"   3. {file_3} ({len(f3_df)} stocks)")
    print(f"   4. {file_4} ({len(f4_df)} stocks)")
    print(f"   5. {file_5} ({len(f5_df)} stocks)")
    print(f"   6. {file_6} ({len(f6_df)} stocks)")
    print(f"   7. {file_7} ({len(f7_df)} stocks)")
    print(f"   8. {file_8} ({len(f8_df)} stocks)")
    print(f"   9. {file_9} ({len(f9_df)} stocks)")
    
    report_text = build_whatsapp_report(df_all, df_n500)
    
    # Dispatch all 9 files via Telegram Bot
    print("\n📤 Sending 9 files via Telegram Bot...")
    for file_path, caption in [
        (file_1, f"1️⃣ File 1: Pure Vol Exp + Deliv Acc [Nifty 500] ({len(f1_df)} stocks) — {date_str}"),
        (file_2, f"2️⃣ File 2: Pure Deliv Acc + Vol Dec [Nifty 500] ({len(f2_df)} stocks) — {date_str}"),
        (file_3, f"3️⃣ File 3: Multi-TF Super Signal [Nifty 500] ({len(f3_df)} stocks) — {date_str}"),
        (file_4, f"4️⃣ File 4: Multi-TF Deliv Accumulation [Nifty 500] ({len(f4_df)} stocks) — {date_str}"),
        (file_5, f"5️⃣ File 5: 1D+1W+1M Green + Prev 1M Red [ALL NSE] ({len(f5_df)} stocks) — {date_str}"),
        (file_6, f"6️⃣ File 6: 1D+1W+1M Green + Prev 1W Red [ALL NSE] ({len(f6_df)} stocks) — {date_str}"),
        (file_7, f"7️⃣ File 7: 1D+1W+1M Green [ALL NSE] ({len(f7_df)} stocks) — {date_str}"),
        (file_8, f"8️⃣ File 8: 1D Red + Prev 1W Red + 1W Green + Prev 1M Red + 1M Green [ALL NSE] ({len(f8_df)} stocks) — {date_str}"),
        (file_9, f"9️⃣ File 9: 1M Green + Prev 1M Green + Vol Contraction [ALL NSE] ({len(f9_df)} stocks) — {date_str}"),
    ]:
        send_telegram_file(file_path, caption)
        import time; time.sleep(1.5)
    
    # Dispatch primary Super Signal file via Meta Official WhatsApp Cloud API
    media_id = upload_media_meta(file_3)
    if media_id:
        send_whatsapp_template_meta(media_id, file_3, report_text)

    print("\n🎉 Multi-Timeframe 9-file notification pipeline finished successfully!\n")


if __name__ == "__main__":
    run_daily_notification()


