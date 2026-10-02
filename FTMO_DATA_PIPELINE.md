# Aurvex veri hattı — şema, kurulum, doğrulama (Sprint 1)

> Salt-okunur yerel veri hattı: canlı MT5 → CSV → SQLite → günlük rapor. VPS yok,
> ücretli API yok, **sıfır işlem yetkisi.** Mevcut 4 işlem EA'sına dokunmaz.
> ⚠️ MQL5 collector bu ortamda **derlenmedi** (derleyici yok); Python importer
> **gerçek verilerle doğrulandı** (aşağıda). Collector'ı F7 ile sen derlersin.

## Parçalar
1. **`mql5/AurvexCollector.mq5`** — ayrı 5. grafikte çalışan salt-okunur toplayıcı.
2. **`scripts/aurvex_collector_import.py`** — CSV → SQLite artımlı importer + günlük rapor.
3. (opsiyonel) **DecisionJournal** — `AurvexFTMO_v3_15_live.mq5` içinde default-OFF;
   reddedilen sinyalleri loglar (collector bunları göremez).

---

## 1. Collector (MQL5) — ne yapar
- `CollectSymbols="XAUUSD,XAGUSD,GER40.cash,JP225.cash"`; Timer'da `CopyTicksRange`
  ile 4 sembolün tick akışı. **Emir açma/değiştirme/kapatma fonksiyonu YOK** (CTrade
  include edilmedi; statik tarama: sıfır trade çağrısı).
- Restart-safe cursor: her sembol için `last_msc:count` checkpoint dosyasında; aynı
  ms'teki birden fazla tick korunur, mükerrer yazılmaz, restart'ta kaldığı yerden devam.
- Deals: `OnTradeTransaction`'da anlık + periyodik `HistorySelect` reconciliation;
  başlangıçta `HistoryBackfillDays` gün geriye tarar. **İlk planlanan SL ve EA sürümü
  gözlemlenemediği için `unknown` yazılır** (tahmin yok).
- Snapshots: account (balance/equity/margin/open_risk_est/connected/server), positions,
  symbols (point/tick_size/tick_value/min-lot/step/profit-ccy/spread/stops/freeze).
- Broker zamanı, UTC ve toplama zamanı AYRI kolonlar.
- Günlük dosya döndürme (dosya adında tarih); append-close yazım (handle sızıntısı yok);
  health log (disconnect, tick-cap, day_rollover, start/stop).

### Collector CSV şeması (tab-separated, `MQL5/Files/AurvexCollector/v12/`)
> **v1.2:** çıktı **versiyonlu alt-klasör** `v12/`'de — değişen şema eski (v1.0/v1.1)
> dosyalara **asla karışmaz**. Migration = burada sıfırdan başla; eski dosyaya append etme.
| dosya | kolonlar |
|---|---|
| `ticks_<SYM>_<YYYYMMDD>.csv` | collect_msc, tick_msc, **seq**, broker_time, utc_time, bid, ask, last, volume, volume_real, flags |
| `deals_<YYYYMMDD>.csv` | collect_utc, **deal_time_msc**, deal_ticket, order_ticket, position_id, magic, symbol, deal_type, entry_type, volume, price, sl_planned(=unknown), commission, swap, fee, profit, ea_version(=unknown), owner(ours/foreign) |
| `positions_<YYYYMMDD>.csv` | collect_utc, ticket, position_id, magic, symbol, pos_type, volume, price_open, sl, tp, price_current, swap, profit, owner |
| `account_<YYYYMMDD>.csv` | collect_utc, broker_time, utc_time, balance, equity, margin, free_margin, margin_level, open_risk_est, **open_risk_known**(0/1), connected, server |
| `symbols_<YYYYMMDD>.csv` | collect_utc, symbol, point, digits, tick_size, tick_value, volume_min, volume_step, volume_max, currency_profit, spread_points, stops_level, freeze_level |
| `health_<YYYYMMDD>.csv` | collect_utc, event, detail |
| `checkpoint.csv` | key, value (tick_<SYM>=msc:count, last_deal_time_msc) |

### v1.2 dar düzeltmeler (üçüncü review)
- **Committed-length (staging/commit) protokolü:** her data dosyasının yanında bir
  **`<dosya>.commit`** sidecar'ı yayımlanan (tam yazılmış) bayt uzunluğunu tutar.
  Batch, committed offset'e yazılır (önceki başarısız yazımın kuyruğunu üzerine yazar);
  **yalnız payload tam yazıldıktan sonra** `.commit` ilerler (atomik temp+rename).
  Importer dosyayı **yalnız `.commit`'e kadar** okur → yarım/başarısız batch, **kolon
  sayısı tam görünse bile** asla yayımlanmaz. **Partial payload'a newline eklenmez.**
- **Checkpoint doğrulama:** temp checkpoint, move'dan önce **içerik+şema+her sembol
  kaydı** için doğrulanır; geçersiz temp **son sağlam checkpoint'i değiştirmez** (silinir).
- Regression: son-alanda-kesilen-ama-kolon-tam satır (`test_uncommitted_partial_not_published`);
  checkpoint doğrulama (`test_checkpoint_validation`).

### v1.2 düzeltmeleri (ikinci review)
1. **Crash-replay dedup:** her tick'e **ms-içi `seq`** (0-based) verilir → kimlik
   `(symbol, tick_msc, seq)`; collector checkpoint öncesi çökerse yeniden yazılan
   tick'ler importer'da `UNIQUE(symbol,tick_msc,seq)` ile tekilleşir. Aynı-ms, **aynı
   fiyatlı** meşru tick'ler farklı seq ile korunur (yalnız timestamp/fiyat UNIQUE değil).
2. **SAVEPOINT/dosya:** her dosya bir SAVEPOINT; hata olursa o dosyanın satırları **ve**
   offset'i **birlikte rollback** → sonraki çalıştırmada temiz yeniden okunur.
3. **Atomik yazım:** `AppendBatch` **tam payload** yazımını doğrular; eksik yazımda
   bozuk kuyruğu `\n` ile kapatır, cursor ilerlemez. **Checkpoint**: temp dosya → doğrula
   → **atomik `FileMove`**; restart'ta `.tmp`'den kurtarma. Tüm `FileOpen` **FILE_SHARE_READ|WRITE**
   (importer eşzamanlı okur).
4. **Bounded backlog:** `CopyTicksRange` **sonlu pencere** (`TickWindowSec`), poll başına
   `MaxWindowsPerPoll` pencere → uzun kesinti sonrası tüm geçmiş tek çağrıda belleğe
   alınmaz; **boş pencerede de cursor ilerler** (gap atlanır).
5. **Migration:** çıktı `v12/` klasöründe; importer **schema_meta=1.2** tutar ve
   **eski DB'yi reddeder** (sessiz migration yok); header uyuşmayan dosya **atlanır**
   (eski şema sessizce append edilmez).

### v1.1 düzeltmeleri (Sprint-1 review)
1. **Importer byte-offset:** yalnız `\n` ile biten kayıtlar tüketilir; yarım satırda cursor ilerlemez (crash/replay güvenli).
2. **Tick cursor:** tarama boyunca başlangıç (msc,count) **sabit**; yeni cursor ayrı hesaplanır → aynı-ms tick'lerin tamamı korunur. (regression testi: `tests/test_collector_importer.py::test_tick_cursor_*`)
3. **Deal reconcile:** overlap taraması + ticket dedup; `HistoryDealGet*(ticket,...)` ile okunur, **`HistoryDealSelect` yok** (liste sıfırlanmaz); gecikmiş küçük ticket atlanmaz.
4. **Verified-write gating:** tick cursor/checkpoint **yalnız yazım doğrulandıktan sonra** ilerler; aksi halde retried.
5. **DEAL_TIME_MSC:** eklendi; günlük rapor **gerçekleşme tarihine** göre, **net = profit+commission+swap+fee**.
6. **Bounded reads + batch write:** tick'ler sınırlı aralıkta okunur (`TickMaxLookbackSec`, `TicksPerPollMax`), poll başına tek batch yazılır.
7. **open_risk unknown:** SL'siz/hesaplanamayan pozisyonda `open_risk_known=0` (tahmin yok); rapor "UNKNOWN" işaretler.

---

## 2. Importer (Python) — SQLite + rapor
`python scripts/aurvex_collector_import.py --dir <csvdir> --db data/live/aurvex_live.db --report data/live/reports [--date YYYYMMDD]`
- Artımlı: `import_state` tablosu her dosyanın kaç satırının alındığını tutar →
  **tekrar okuma mükerrer kayıt üretmez.**
- Deals ayrıca `deal_ticket` PK ile INSERT OR IGNORE → collector bir deal'i iki kez
  yazsa (event + reconcile) **tek kayıt.**
- SQLite tabloları: ticks, deals, positions, account, symbols, health, import_state.
- Günlük **JSON + Markdown rapor** (tick sayıları, deals ours/foreign + pnl/komisyon/swap,
  son account snapshot, health/reconciliation). **Claude'a kendiliğinden ulaşmaz** —
  `--dir`'i collector klasörüne yönelt, rapor/DB'yi paylaş.

---

## 3. Kurulum (Windows 11, MT5 sürekli açık)
**Collector (MT5):**
1. `AurvexCollector.mq5`'i `MQL5/Experts/`'e koy → MetaEditor **F7** (0 error).
2. **5. bir grafik aç** (herhangi sembol, H1), collector'ı sürükle. `CollectSymbols`
   default 4 sembol. **Algo Trading açık.** (İşlem açmaz; sadece okur.)
3. 4 işlem EA'sına **dokunma** — ayrı grafiklerde çalışmaya devam.
4. Çıktı: `MQL5/Files/AurvexCollector/v12/`. Konum: `File → Open Data Folder`.

**Importer (Python, otomatik):**
1. Python 3 kurulu (ücretsiz). Ek paket gerekmez (stdlib: sqlite3/csv/json).
2. Elle: yukarıdaki komut. `--dir` = collector'ın `AurvexCollector` klasörü.
3. **Otomatik (Task Scheduler):** "Create Task" → Trigger: her 15 dk / oturum açılışında
   → Action: `python.exe C:\...\scripts\aurvex_collector_import.py --dir "C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\<id>\MQL5\Files\AurvexCollector\v12" --db C:\aurvex\aurvex_live.db --report C:\aurvex\reports`.
   "Run whether user is logged on or not" + "If the task fails, restart every 1 min".
4. MT5 ve importer bağımsız; MT5 yazarken importer okur (append-only, güvenli).

**Yeniden başlatma:** MT5 kapanıp açılınca collector checkpoint'ten devam eder; importer
`import_state`'ten devam eder. İkisi de veri kaybı/mükerrer üretmez.

---

## 4. Doğrulama sonuçları (v1.2)
| test | sonuç |
|---|---|
| Tick cursor: aynı-ms tick'ler farklı **seq** ile korunur | **PASS** |
| Tick cursor: resume mükerrer yok; kısmi same-ms prefix seq devam eder | **PASS** |
| Tick cursor: başlangıç sabit (multi-ms regression) | **PASS** |
| **Crash-replay:** yeniden yazılan tick'ler (symbol,msc,seq) ile tekilleşir; yeni seq eklenir | **PASS** |
| **SAVEPOINT:** dosya-ortası hata → satır+offset birlikte rollback; iyi dosya aktarılır | **PASS** |
| Byte-offset: yarım satır tüketilmez, tamamlanınca alınır, truncate yok | **PASS** |
| **Header mismatch (eski şema):** atlanır, offset ilerlemez, not düşülür | **PASS** |
| **Eski DB reddi (schema_meta yok):** SystemExit (sessiz migration yok) | **PASS** |
| Deals: DEAL_TIME_MSC → gerçekleşme tarihi; net=profit+comm+swap+fee | **PASS** (net 18.2) |
| Deal dedup / eksik dosya / open_risk unknown | **PASS** |
| **Committed protokol:** son-alanda kesik ama kolon-tam satır yayımlanmaz; batch tamamlanınca görünür | **PASS** |
| **Checkpoint doğrulama:** şema/eksik-sembol/boş reddedilir, geçerli kabul | **PASS** |
| Tüm suite (FTMO + collector) | **PASS** (154) |
| **MQL5 collector F7 derleme** | **NOT OBSERVED** (derleyici yok — operatör) |
| **Gerçek disk-dolum/crash kurtarma, canlı akış, Windows paylaşım/kesinti, restart** | **NOT OBSERVED** (terminal/OS — operatör; kanıtlanana kadar PASS değil) |

## 5. Başarı ölçütü (iş emri) — durum
- Dört sembolde veri akışı → kod hazır; **canlı akış operatör demo'sunda doğrulanacak.**
- İşlem geçmişiyle mutabakat → reconcile + dedup **mantığı** doğrulandı (Python); canlı NOT OBSERVED.
- Restart sonrası süreklilik → checkpoint/import_state **mantığı** doğrulandı; canlı NOT OBSERVED.
- **Sıfır işlem yetkisi → PASS** (statik: collector'da hiçbir trade fonksiyonu yok).

## 6. DecisionJournal (reddedilen sinyaller)
`AurvexFTMO_v3_15_live.mq5` içinde `DecisionJournalEnabled` (**default false**).
Açıkken her karar (ARM/SKIP + reason: already_broken / low_vol_filter / orb_breakout /
pdhl_breakout) + setup hi/lo + spread% + hedef risk'i `AurvexFTMO_decisions_<SYM>_<magic>.csv`'ye
yazar. **Davranış-nötr** (sadece log, ilk satır `if(!DecisionJournalEnabled) return;`).
**Canlı sürüm demo'da doğrulanmadan açma.**

## Sonraki sprint
Bu veriyle gerçek-tick backtest + geçiş-süresi optimizasyonu (`FTMO_V315_SPEED_LAB.md`).
Hedef: maliyet-sonrası kazanç hızını artırmak, FTMO aşamalarını kısaltmak.
