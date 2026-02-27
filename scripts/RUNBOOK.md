# 🛠️ Trading Bot - Emergency Recovery Runbook

Yeh document DLQ (Dead Letter Queue) handle karne aur failed trades ko recover karne ke liye hai.

---

## 🚨 Scenario 1: Telegram par CRITICAL DLQ Alert aana
Jab system 60 seconds mein 5 se zyada failures dekhta hai, toh yeh alert aata hai.

### **Immediate Actions:**
1. **Logs Check Karein**: 
   `sudo journalctl -u tv-engine -f`
2. **Root Cause Identify Karein**:
   - Kya Binance API down hai?
   - Kya internet issue hai?
   - Kya koi naya strategy code crash ho raha hai?

---

## 🔄 Scenario 2: Failed Trades ko Replay karna
Agar signals `storage/dlq.jsonl` mein jama ho gaye hain, toh unhe wapas process karne ke liye:

### **Step-by-Step Recovery:**
1. **DLQ File Inspect Karein**:
   `cat storage/dlq.jsonl`
2. **Replay Tool Chalayein**:
   `python3 scripts/dlq_replay.py`
3. **Selection**:
   - `y`: Agar aapko lagta hai ki error temporary tha (e.g. Network Timeout) aur trade ab execute ho sakta hai.
   - `n`: Agar signal invalid hai aur aap use DLQ mein hi chhodna chahte hain.
   - `d`: Agar trade expire ho chuka hai aur aap use delete karna chahte hain.

---

## 🛡️ Scenario 3: Safety Gate Bypass
Agar koi valid trade block ho raha hai aur aap use turant allow karna chahte hain:

1. **Telegram Command**: 
   `/override SYMBOL` (e.g. `/override BTCUSDT`)
2. Yeh gate 60 minutes tak khula rahega.

---

## 📉 Scenario 4: Reconciliation Drift
Agar Telegram par `⚠️ RECON DRIFT DETECTED!` aata hai:
1. **Manual Audit**: Google Sheets ledger aur Binance account balance match karein.
2. **Fix**: Ledger state file (`storage/ledger_state.json`) ko manually update karein agar zaroori ho.
