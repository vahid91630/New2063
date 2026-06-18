# new2063

ربات الگوریتمی تلگرام برای پایش خودکار XAU/USD و ارسال سیگنال با منطق SMC / ICT / Price Action، بدون اتصال به مدل هوش مصنوعی.

## این برنامه دقیقاً چه کار می‌کند
- خودش از API داده OHLC می‌گیرد.
- روی چند تایم‌فریم تحلیل top-down انجام می‌دهد.
- ساختار بازار را به Bullish / Bearish / Range تقسیم می‌کند.
- BOS / CHoCH / EQH / EQL / liquidity sweep / internal-external liquidity را با heuristic داخل کد پیدا می‌کند.
- Order Block / Breaker / Mitigation / FVG / Premium-Discount را از روی کندل‌ها استخراج می‌کند.
- فقط وقتی تایم‌فریم‌های بالاتر و تایم‌فریم اجرا هم‌جهت باشند و حداقل `MIN_CONFLUENCE_COUNT` تأیید وجود داشته باشد، سیگنال به تلگرام می‌فرستد.
- اگر confluence کم باشد، سیگنال نمی‌فرستد.

## نکته مهم
این پروژه **هیچ سود یا win rate ثابتی را تضمین نمی‌کند**. منطق آن باید قبل از استفاده واقعی، روی داده گذشته و سپس paper trade و forward test بررسی شود.

## معماری
```text
new2063/
├─ app/
│  ├─ services/
│  │  ├─ analysis.py
│  │  ├─ market_data.py
│  │  ├─ runner.py
│  │  ├─ signals.py
│  │  └─ telegram_notifier.py
│  ├─ utils/
│  │  └─ logging_config.py
│  ├─ config.py
│  ├─ healthcheck.py
│  ├─ main.py
│  └─ models.py
├─ .env.example
├─ railway.toml
├─ requirements.txt
└─ README.md
```

## منطق تحلیل
### 1) ساختار بازار
در `analysis.py` با swing high / swing low:
- اگر HH + HL → `Bullish`
- اگر LH + LL → `Bearish`
- در غیر این صورت → `Range`

### 2) BOS / CHoCH
- اگر کلوز آخر از swing مهم عبور کند، BOS ثبت می‌شود.
- اگر ساختار قبلی شکسته شود، CHoCH ثبت می‌شود.

### 3) نقدینگی
- EQH و EQL با مقایسه swingهای نزدیک و tolerance پویا پیدا می‌شوند.
- sweep وقتی ثبت می‌شود که wick سطح را بزند اما کلوز برگردد.
- internal و external liquidity بر اساس موقعیت سطوح نسبت به قیمت فعلی طبقه‌بندی می‌شوند.

### 4) Smart Money Zones
- Order Block: آخرین کندل مخالف قبل از displacement
- Breaker: OBی که توسط قیمت نقض شده
- Mitigation: OBی که قیمت به آن برگشته
- FVG: gap سه‌ کندلی
- Premium / Discount: نیمه بالایی و پایینی dealing range اخیر

### 5) ساخت سیگنال
در `signals.py`:
- اول ساختار تایم‌فریم بالاتر و execution timeframe باید align باشد.
- بعد entry zone از OB یا FVG گرفته می‌شود.
- حداقل 3 confluence لازم است.
- SL / TP / R:R / probability محاسبه می‌شود.
- اگر setup ضعیف باشد، خروجی `NO TRADE` می‌ماند و چیزی ارسال نمی‌شود.

## جایی که باید بعداً API را وصل کنی
فایل:
- `app/services/market_data.py`

اگر Twelve Data استفاده کردی:
- فقط `TWELVEDATA_API_KEY` را در env بگذار.
- provider آماده است.

اگر API دیگری گرفتی:
- همین interface را نگه دار:
```python
async def fetch_ohlc(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
    ...
```
- کلاس جدید provider را در همان فایل اضافه کن.
- در `build_market_data_provider` آن را انتخاب کن.

### یادداشت مستقیم برای تو
**وحید:**  
وقتی API واقعی را گرفتی، اینجا وصلش کن:
- `app/services/market_data.py`
- `.env`

## متغیرهای محیطی
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `PORT`
- `ACCOUNT_BALANCE`
- `RISK_PERCENT`
- `SYMBOL`
- `TOP_DOWN_TIMEFRAMES`
- `EXECUTION_TIMEFRAME`
- `POLL_INTERVAL_SECONDS`
- `BARS_LIMIT`
- `MIN_CONFLUENCE_COUNT`
- `MIN_SIGNAL_INTERVAL_MINUTES`
- `MARKET_DATA_PROVIDER`
- `TWELVEDATA_API_KEY`
- `TWELVEDATA_BASE_URL`

## اجرای محلی
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

## استقرار روی Railway
1. این پوشه را داخل GitHub push کن.
2. در Railway گزینه Deploy from GitHub repo را بزن.
3. repo را انتخاب کن.
4. environment variableها را ثبت کن.
5. برنامه با `python -m app.main` بالا می‌آید.
6. health check روی `/health` فعال است.

Railway از GitHub deploy و start command در config-as-code را پشتیبانی می‌کند. citeturn410626search1turn410626search4turn410626search16

## وابستگی‌ها
- `python-telegram-bot` برای ارسال پیام تلگرام. این کتابخانه به‌صورت async برای Python 3.10+ ارائه می‌شود. citeturn410626search6turn410626search3
- Twelve Data به‌عنوان provider آماده‌ی اولیه برای XAU/USD گذاشته شده و در مستنداتش XAU/USD را در forex/commodities پوشش می‌دهد. citeturn410626search5turn410626search8turn410626search11
