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
    """Send Excel workbook directly to user via Telegram Bot API."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(url, data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
            if resp.status_code == 200:
                print(f"✅ Sent Excel report via Telegram Bot! ({os.path.basename(file_path)})")
                return True
            else:
                print(f"⚠️ Telegram API status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"❌ Error sending Telegram document: {e}")
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


def build_whatsapp_report(df):
    """Format summary message for WhatsApp and Telegram."""
    date_str = datetime.now().strftime("%d-%b-%Y")
    super_df = df[df["Multi-TF Super Signal"] == "YES"]
    vol_exp_df = df[df["Multi-TF Vol Expansion"] == "YES"]
    deliv_acc_df = df[df["Multi-TF Deliv Accumulation"] == "YES"]
    
    msg = f"🌟 *NSE MULTI-TIMEFRAME SCANNER REPORT* ({date_str})\n"
    msg += f"─────────────────────────────────────────────\n"
    msg += f"🔍 Total Nifty 500 Stocks: {len(df)}\n"
    msg += f"🚀 *Multi-TF Volume Expansion*: {len(vol_exp_df)} stocks\n"
    msg += f"📦 *Multi-TF Delivery Accumulation*: {len(deliv_acc_df)} stocks\n"
    msg += f"🔥 *Multi-TF Super Signals*: {len(super_df)} stocks\n"
    msg += f"   *(Deliv % ↑ AND Vol Exp ↑ AND 1D + 1W + 1M Green Candles)*\n\n"
    
    if not super_df.empty:
        msg += f"🏆 *TOP MULTI-TF SUPER ACCUMULATION STOCKS*:\n"
        for idx, row in super_df.head(10).iterrows():
            msg += f"• *{row['Symbol']}* (₹{row['Price (₹)']}): Deliv {row['Yest Deliv %']}% | Vol {row['Yest Volume']:,} | 🟢 1D ({row['1D %']}%) 1W ({row['1W %']}%) 1M ({row['1M %']}%)\n"
        if len(super_df) > 10:
            msg += f"...and {len(super_df) - 10} more in attached Excel.\n"
        msg += "\n"
    elif not vol_exp_df.empty:
        msg += f"📈 *TOP MULTI-TF VOLUME EXPANSION STOCKS*:\n"
        for idx, row in vol_exp_df.head(10).iterrows():
            msg += f"• *{row['Symbol']}* (₹{row['Price (₹)']}): Vol {row['Yest Volume']:,} (5D: {row['5D Avg Vol']:,}) | 🟢 1D ({row['1D %']}%) 1W ({row['1W %']}%) 1M ({row['1M %']}%)\n"
        if len(vol_exp_df) > 10:
            msg += f"...and {len(vol_exp_df) - 10} more in attached Excel.\n"
        msg += "\n"
    else:
        msg += "⚠️ No stocks matched all Multi-TF criteria today.\n\n"
            
    msg += f"📁 Complete Multi-Timeframe report attached below (.xlsx Excel workbook with 4 tabs)."
    return msg


# ──────────────────────────────────────────────────────────────
# MAIN PIPELINE & NOTIFICATION
# ──────────────────────────────────────────────────────────────
def run_daily_notification():
    print("\n" + "═" * 65)
    print("   💬 NSE MULTI-TIMEFRAME SUPER ACCUMULATION NOTIFIER (9:00 PM IST)")
    print(f"   Run Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 65 + "\n")

    symbols = get_nifty500_symbols()
    daily_dfs = fetch_all_mto(target_days=30)
    if not daily_dfs:
        print("❌ No MTO files downloaded.")
        return

    if not symbols:
        latest_key = sorted(daily_dfs.keys(), key=lambda x: datetime.strptime(x, "%d%m%Y"), reverse=True)[0]
        symbols = sorted(daily_dfs[latest_key]["Symbol"].unique().tolist())
        print(f"ℹ️ Loaded {len(symbols)} symbols directly from latest MTO data file.")

    candle_dict = fetch_multi_tf_candles(symbols)

    results = []
    for sym in symbols:
        stats = compute_multi_tf_stats(sym, daily_dfs, candle_dict)
        if stats:
            results.append(stats)

    df_res = pd.DataFrame(results)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = os.path.dirname(os.path.abspath(__file__))
    
    csv_file = os.path.join(out_dir, f"multi_tf_signals_nifty500_{timestamp_str}.csv")
    excel_file = os.path.join(out_dir, f"multi_tf_signals_nifty500_{timestamp_str}.xlsx")
    
    df_res.to_csv(csv_file, index=False)
    
    # Generate openpyxl Excel workbook with 4 sheets
    with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
        df_res.to_excel(writer, sheet_name="Nifty 500 Multi-TF Signals", index=False)
        vol_exp_df = df_res[df_res["Multi-TF Vol Expansion"] == "YES"]
        vol_exp_df.to_excel(writer, sheet_name="Multi-TF Volume Expansion", index=False)
        deliv_acc_df = df_res[df_res["Multi-TF Deliv Accumulation"] == "YES"]
        deliv_acc_df.to_excel(writer, sheet_name="Multi-TF Delivery Accumulation", index=False)
        super_df = df_res[df_res["Multi-TF Super Signal"] == "YES"]
        super_df.to_excel(writer, sheet_name="Multi-TF Super Accumulation", index=False)
        
    print(f"💾 Saved Files → {csv_file} & {excel_file}")
    
    report_text = build_whatsapp_report(df_res)
    
    # 1. Dispatch via Telegram Bot (Instant Delivery)
    send_telegram_file(excel_file, f"📊 NSE Multi-TF Super Accumulation Report ({datetime.now().strftime('%d-%b-%Y')})")
    
    # 2. Dispatch via Meta Official WhatsApp Cloud API
    media_id = upload_media_meta(excel_file)
    if media_id:
        send_whatsapp_template_meta(media_id, excel_file, report_text)

    print("\n🎉 Multi-Timeframe notification pipeline finished!\n")


if __name__ == "__main__":
    run_daily_notification()
