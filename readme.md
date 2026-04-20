# LiTTrans v5.6

**Pipeline dịch tự động truyện LitRPG / Tu Tiên** — từ tiếng Anh sang tiếng Việt, nhất quán từ chương 1 đến chương 1000.

> Dùng **Gemini AI** (miễn phí) hoặc **Claude (Anthropic)** làm engine dịch.  
> Giữ nhất quán tên nhân vật, xưng hô, kỹ năng và thuật ngữ xuyên suốt toàn bộ tác phẩm.

---

## Mục lục

- [LiTTrans làm được gì?](#littrans-làm-được-gì)
- [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
- [Lấy API Key](#lấy-api-key)
- [Cài đặt nhanh](#cài-đặt-nhanh)
- [Cấu hình `.env`](#cấu-hình-env)
- [Bắt đầu dùng](#bắt-đầu-dùng)
  - [Cào truyện từ web](#cào-truyện-từ-web)
  - [Pipeline 1-click (web → dịch)](#pipeline-1-click-web--dịch)
  - [Xử lý EPUB](#xử-lý-epub)
  - [Dịch thủ công](#dịch-thủ-công)
  - [Dùng CLI](#dùng-cli)
- [Tính năng chính](#tính-năng-chính)
- [Bible System](#bible-system)
- [Pipeline hoạt động như thế nào?](#pipeline-hoạt-động-như-thế-nào)
- [Xử lý sự cố](#xử-lý-sự-cố)
- [Tất cả tùy chọn cấu hình](#tất-cả-tùy-chọn-cấu-hình)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)

---

## LiTTrans làm được gì?

Khi dịch truyện dài hàng trăm chương bằng AI thông thường, bạn sẽ gặp vấn đề: **nhân vật bị gọi bằng 5 cái tên khác nhau, xưng hô loạn xạ, kỹ năng dịch mỗi chương một kiểu**. LiTTrans giải quyết điều này bằng cách xây dựng "bộ nhớ" cho toàn bộ quá trình dịch.

| Vấn đề thường gặp | LiTTrans giải quyết như thế nào |
|---|---|
| Phải tự copy-paste từng chương | **Scraper** — tự cào truyện từ web, resume được nếu bị ngắt |
| Tên nhân vật bị dịch khác nhau | **Name Lock** — chốt cứng một bản dịch duy nhất |
| Xưng hô "anh/em" → "ta/ngươi" loạn | **EPS** — theo dõi mức độ thân mật từng cặp nhân vật |
| Kỹ năng dịch mỗi chương một kiểu | **Skills DB** — lưu và tái sử dụng tên kỹ năng |
| AI quên bối cảnh chương trước | **Arc Memory + Scout AI** — tóm tắt và nhắc bối cảnh |
| Phải ngồi canh từng chương | **Batch pipeline** — tự động chạy hết queue, có retry |
| Có file EPUB muốn dịch | **EPUB Processor** — bóc nội dung EPUB → dịch → xuất EPUB mới |

---

## Yêu cầu hệ thống

- **Python 3.11+**
- **Playwright** (cần cài riêng cho scraper)

```bash
# Kiểm tra Python
python --version   # phải ≥ 3.11

# Sau khi cài xong thư viện, cài browser cho Playwright (chỉ 1 lần):
playwright install chromium
```

---

## Lấy API Key

### Gemini API Key — bắt buộc, miễn phí

1. Vào [aistudio.google.com](https://aistudio.google.com) → đăng nhập Google
2. Nhấn **"Get API key"** → **"Create API key"**
3. Copy key (dạng `AIzaSy...`)

> **Gói miễn phí:** ~1.000 request/ngày — đủ 30–50 chương/ngày.  
> **Mẹo:** Tạo nhiều key từ tài khoản khác nhau → dùng `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`... để tăng quota.

### Anthropic API Key — tùy chọn

Nếu muốn dùng Claude làm engine dịch chính:

1. Vào [console.anthropic.com](https://console.anthropic.com) → **API Keys** → **Create Key**
2. Copy key (dạng `sk-ant-...`) → thêm vào `.env`

---

## Cài đặt nhanh

```bash
git clone <repo-url>
cd NovelPipeline

python -m venv .venv

# macOS / Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -e .
pip install ".[fast]"     # khuyến nghị — tăng tốc glossary matching ~10x

# Cài browser cho scraper (chỉ 1 lần):
playwright install chromium

# Tạo file cấu hình:
cp .env.example .env
# Mở .env → điền GEMINI_API_KEY
```

Khởi động Web UI:
```bash
python scripts/run_ui.py
```

Mở trình duyệt: **http://localhost:8501** ✅

---

## Cấu hình `.env`

```env
# ── BẮT BUỘC ──────────────────────────────────────────────────────────
GEMINI_API_KEY=AIzaSy...

# ── NHIỀU KEY — tăng quota (thêm bao nhiêu cũng được) ─────────────────
GEMINI_API_KEY_1=AIzaSy...
GEMINI_API_KEY_2=AIzaSy...
GEMINI_API_KEY_3=AIzaSy...
# Lưu ý: chỉ nhận đúng format GEMINI_API_KEY_N (N = số nguyên)
# Không nhận _DEV, _OLD, _BACKUP...

# ── CHỌN MODEL DỊCH ────────────────────────────────────────────────────
TRANSLATION_PROVIDER=gemini          # gemini (mặc định) hoặc anthropic
TRANSLATION_MODEL=gemini-2.5-flash   # để trống = dùng mặc định
# ANTHROPIC_API_KEY=sk-ant-...       # cần nếu dùng anthropic

# ── TỐC ĐỘ & ỔN ĐỊNH ───────────────────────────────────────────────────
SUCCESS_SLEEP=30       # nghỉ (giây) sau mỗi chương
RATE_LIMIT_SLEEP=60    # nghỉ khi bị 429
MAX_RETRIES=5

# ── BIBLE SYSTEM (tùy chọn) ────────────────────────────────────────────
BIBLE_MODE=false
```

> Sau khi sửa `.env`, restart pipeline để áp dụng. Hoặc vào tab **⚙️ Cài đặt** trong Web UI.

---

## Bắt đầu dùng

### Cào truyện từ web

UI → tab **🌐 Cào Truyện**

1. Nhập URL truyện + tên novel
2. Nhấn **Cào** — pipeline tự học cấu trúc site lần đầu, lưu vào `data/site_profiles.json`
3. Có thể dừng giữa chừng — resume tự động từ chương cuối cùng
4. Kết quả lưu vào `inputs/{novel_name}/`

> **Force re-learn site:** Thêm prefix `!relearn domain.com` vào URL nếu site thay đổi cấu trúc.

---

### Pipeline 1-click (web → dịch)

UI → tab **🚀 Pipeline** → mode **🌐→🇻🇳 Cào web + dịch**

1. Nhập URL + novel name → nhấn **Chạy**
2. Stage 1: Cào web → `inputs/{novel}/`
3. Stage 2: Dịch toàn bộ → `outputs/{novel}/`
4. Theo dõi tiến độ real-time trong UI

---

### Xử lý EPUB

**Nhập EPUB để dịch:**

UI → tab **🚀 Pipeline** → mode **📚 Chỉ xử lý EPUB → .md**

1. Upload file `.epub` → nhập novel name → nhấn **Chạy**
2. Output: `inputs/{novel_name}/NNNN_Title.md`
3. Sau đó dịch bình thường qua tab **📄 Dịch**

**Xuất EPUB từ bản dịch:**

UI → tab **📄 Dịch** → cuối trang → expander **📖 Xuất EPUB**

1. Nhập title/author → nhấn **🔄 Tạo EPUB** → Download

---

### Dịch thủ công

1. Đặt file chương vào `inputs/{novel_name}/` (`.txt` hoặc `.md`, đặt tên theo thứ tự)
2. UI → tab **📄 Dịch** → chọn novel → nhấn **▶ Chạy pipeline**
3. Bản dịch lưu vào `outputs/{novel_name}/*_VN.txt`
4. Xem song ngữ EN/VN trong tab **🔍 Xem chương**

---

### Dùng CLI

```bash
# Dịch tất cả chương chưa dịch
python scripts/main.py translate

# Dịch lại 1 chương cụ thể
python scripts/main.py retranslate 5
python scripts/main.py retranslate "chapter_005"

# Xem tiến độ
python scripts/main.py stats

# Quản lý data
python scripts/main.py clean glossary
python scripts/main.py clean characters --action merge
python scripts/main.py fix-names
```

---

## Tính năng chính

### 🌐 Scraper — Cào truyện từ web

- Hỗ trợ mọi site tiểu thuyết — AI học cấu trúc HTML lần đầu, các lần sau chạy thuần code
- Playwright cho site JS-heavy, curl_cffi cho site tĩnh
- Tự động resume nếu bị ngắt giữa chừng
- Profile site lưu vào `data/site_profiles.json` — không cần learn lại

### 🔒 Name Lock — Chốt tên nhất quán

Một khi tên đã được dịch (ví dụ: "Xiao Yan" → "Tiêu Viêm"), nó **chốt cứng** xuyên suốt pipeline. Vi phạm bị phát hiện và ghi log tự động.

### 💬 EPS — Theo dõi mức độ thân mật

| Mức | Tên | Ý nghĩa |
|---|---|---|
| 1 | FORMAL | Lạnh lùng — giữ kính ngữ |
| 2 | NEUTRAL | Mặc định |
| 3 | FRIENDLY | Thân thiện — câu thoải mái |
| 4 | CLOSE | Rất thân — bỏ kính ngữ |
| 5 | INTIMATE | Ngôn ngữ riêng tư |

### 🔭 Scout AI

Mỗi N chương, Scout đọc trước và:
- Ghi chú mạch truyện (flashback, alias đang dùng)
- Cập nhật trạng thái cảm xúc nhân vật
- Phát hiện thuật ngữ mới → đề xuất thêm Glossary
- Tóm tắt sự kiện → Arc Memory

### 🧹 Post-processor 14-pass

Làm sạch bản dịch bằng code (không dùng AI): dấu câu, em dash, ellipsis, tách lượt thoại, xóa lời mở đầu/kết thúc do AI tự thêm...

### 🤖 Dual-Model

| Nhiệm vụ | Model |
|---|---|
| Scout / Pre-call / Post-call | Gemini (tiết kiệm quota) |
| Dịch chính (Trans-call) | Gemini hoặc Claude |

```env
# Dùng Claude để dịch:
TRANSLATION_PROVIDER=anthropic
TRANSLATION_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Bible System

Bible xây dựng **knowledge base có cấu trúc** từ toàn bộ tác phẩm, gồm 3 tầng:

```
Tầng 1 — Database:       nhân vật, kỹ năng, địa danh, vật phẩm, tổ chức
Tầng 2 — WorldBuilding:  hệ thống tu luyện, quy luật thế giới, địa lý
Tầng 3 — Main Lore:      tóm tắt chương, plot threads, timeline
```

Khi bật `BIBLE_MODE=true`, pipeline dùng Bible thay cho các file riêng lẻ.

### Khởi động

```bash
python scripts/main.py bible scan
# Sau đó bật BIBLE_MODE=true trong .env
python scripts/main.py translate
```

### Lệnh Bible

```bash
python scripts/main.py bible scan --depth quick|standard|deep
python scripts/main.py bible query "Tiêu Viêm"
python scripts/main.py bible ask "Ai là kẻ thù chính của MC?"
python scripts/main.py bible crossref
python scripts/main.py bible export --format markdown|timeline|characters
python scripts/main.py bible consolidate
python scripts/main.py bible stats
```

| Depth | Tốc độ | Dùng khi nào |
|---|---|---|
| `quick` | Nhanh nhất | Lần đầu, muốn data nhanh |
| `standard` | Trung bình | Dùng hàng ngày ✓ |
| `deep` | Chậm nhất | Cần chất lượng cao, loại duplicate |

Quản lý Bible qua UI: tab **📖 Bible System**.

---

## Pipeline hoạt động như thế nào?

Mỗi chương đi qua **4 bước**:

```
① PRE-CALL
   Gemini đọc chương → tạo "Chapter Map":
   tên/kỹ năng nào xuất hiện, xưng hô đang active, có flashback không
        ↓
② TRANS-CALL
   Dịch với full context:
   [Hướng dẫn] + [Glossary] + [Nhân vật] + [Chapter Map]
   + [Arc Memory] + [Name Lock Table] + [Bible nếu bật]
        ↓
③ POST-PROCESSOR (14 pass, không dùng AI)
   Làm sạch: dấu câu, lời thừa, system box...
        ↓
④ POST-CALL
   Gemini review: tên sai? pronoun lệch?
   → Extract nhân vật/thuật ngữ mới
   → Lỗi nghiêm trọng → auto-fix pass → retry Trans-call nếu cần
```

**Scout AI** chạy song song mỗi N chương (mặc định N=5).

---

## Xử lý sự cố

### ❌ Thiếu GEMINI_API_KEY

```env
GEMINI_API_KEY=AIzaSy...
```

### ❌ Rate limit liên tục (429)

```env
GEMINI_API_KEY_1=AIzaSy...   # thêm key từ tài khoản khác
GEMINI_API_KEY_2=AIzaSy...
SUCCESS_SLEEP=60
RATE_LIMIT_SLEEP=120
```

### ❌ Tên nhân vật bị dịch sai

```bash
python scripts/main.py fix-names --list    # xem vi phạm
python scripts/main.py fix-names           # tự động sửa
python scripts/main.py fix-names --dry-run # xem trước
```

### ❌ Scraper không cào được — site thay đổi cấu trúc

Vào UI → tab **🌐 Cào Truyện** → thêm prefix `!relearn domain.com` vào URL.

### ❌ Bible: "Not an Aho-Corasick automaton yet"

```bash
python scripts/main.py bible scan
```

### ❌ Windows: lỗi encoding

```bash
set PYTHONUTF8=1
python scripts/run_ui.py
```

### ❌ Pipeline chậm

```bash
pip install pyahocorasick   # hoặc pip install ".[fast]"
```

---

## Tất cả tùy chọn cấu hình

### API & Model

| Biến | Mặc định | Mô tả |
|---|---|---|
| `GEMINI_API_KEY` | *(bắt buộc)* | API key Gemini chính |
| `GEMINI_API_KEY_N` | — | Key bổ sung (N = 1, 2, 3...) |
| `FALLBACK_KEY_1/2` | — | Key dự phòng legacy |
| `KEY_ROTATE_THRESHOLD` | `3` | Lỗi liên tiếp trước khi đổi key |
| `GEMINI_MODEL` | `gemini-2.0-flash-exp` | Model cho Scout/Pre/Post |
| `TRANSLATION_PROVIDER` | `gemini` | `gemini` hoặc `anthropic` |
| `TRANSLATION_MODEL` | *(tự chọn)* | Để trống = dùng mặc định |
| `ANTHROPIC_API_KEY` | — | API key Anthropic |

### Tốc độ & Ổn định

| Biến | Mặc định | Mô tả |
|---|---|---|
| `MAX_RETRIES` | `5` | Retry tối đa |
| `SUCCESS_SLEEP` | `30` | Nghỉ (giây) sau mỗi chương |
| `RATE_LIMIT_SLEEP` | `60` | Nghỉ khi bị rate limit |
| `PRE_CALL_SLEEP` | `5` | Nghỉ giữa Pre và Trans |
| `POST_CALL_SLEEP` | `5` | Nghỉ giữa Trans và Post |
| `POST_CALL_MAX_RETRIES` | `2` | Retry Trans khi Post báo lỗi |
| `TRANS_RETRY_ON_QUALITY` | `true` | Retry khi phát hiện lỗi dịch |

### Scout AI

| Biến | Mặc định | Mô tả |
|---|---|---|
| `SCOUT_REFRESH_EVERY` | `5` | Chạy Scout mỗi N chương |
| `SCOUT_LOOKBACK` | `10` | Đọc N chương gần nhất |
| `ARC_MEMORY_WINDOW` | `3` | Số arc entry đưa vào prompt |
| `SCOUT_SUGGEST_GLOSSARY` | `true` | Tự đề xuất thuật ngữ mới |
| `SCOUT_SUGGEST_MIN_CONFIDENCE` | `0.7` | Ngưỡng tin cậy tối thiểu |
| `SCOUT_SUGGEST_MAX_TERMS` | `20` | Thuật ngữ tối đa mỗi Scout |

### Bible System

| Biến | Mặc định | Mô tả |
|---|---|---|
| `BIBLE_MODE` | `false` | Dùng Bible khi dịch |
| `BIBLE_SCAN_DEPTH` | `standard` | `quick` / `standard` / `deep` |
| `BIBLE_SCAN_BATCH` | `5` | Consolidate sau N chương scan |
| `BIBLE_SCAN_SLEEP` | `10` | Nghỉ (giây) giữa các chương |
| `BIBLE_CROSS_REF` | `true` | Kiểm tra mâu thuẫn sau scan |
| `BIBLE_DIR` | `data/bible` | Thư mục lưu Bible data |

### Nhân vật & Merge

| Biến | Mặc định | Mô tả |
|---|---|---|
| `ARCHIVE_AFTER_CHAPTERS` | `60` | Archive nhân vật sau N chương vắng |
| `EMOTION_RESET_CHAPTERS` | `5` | Reset emotion state sau N chương |
| `IMMEDIATE_MERGE` | `true` | Merge staging ngay sau mỗi chương |
| `AUTO_MERGE_GLOSSARY` | `false` | Tự động clean glossary cuối pipeline |
| `AUTO_MERGE_CHARACTERS` | `false` | Tự động merge nhân vật cuối pipeline |
| `RETRY_FAILED_PASSES` | `3` | Retry các chương thất bại |
| `BUDGET_LIMIT` | `150000` | Giới hạn token (0 = tắt) |

---

## Cấu trúc thư mục

```
NovelPipeline/
│
├── inputs/{novel_name}/     ← Chương gốc (.txt / .md)
├── outputs/{novel_name}/    ← Bản dịch (*_VN.txt)
├── progress/                ← Trạng thái scraper
│
├── data/
│   ├── site_profiles.json   ← Profile cấu trúc từng site
│   ├── glossary/            ← Từ điển thuật ngữ
│   ├── characters/          ← Profile nhân vật (Active, Archive, Staging)
│   ├── skills/              ← Database kỹ năng
│   ├── memory/              ← Arc Memory + Context Notes
│   └── bible/               ← Bible System data
│
├── src/littrans/
│   ├── config/settings.py   ← Settings dataclass + key management
│   ├── llm/client.py        ← ApiKeyPool, Gemini + Claude clients
│   ├── core/pipeline.py     ← Translation orchestrator
│   ├── context/             ← Glossary, Characters, NameLock, Memory, Bible
│   ├── modules/scraper/     ← Web scraper (Playwright + curl_cffi)
│   ├── tools/
│   │   ├── epub_processor.py  ← EPUB → inputs/{novel}/*.md
│   │   └── epub_exporter.py   ← outputs/{novel}/*_VN.txt → .epub
│   └── ui/
│       ├── app.py           ← Streamlit entry point
│       ├── pipeline_page.py ← Pipeline 1-click
│       ├── scraper_page.py  ← Scraper UI
│       ├── epub_ui.py       ← EPUB processor UI
│       ├── bible_ui.py      ← Bible System UI
│       └── runner.py        ← ScrapeRunner, PipelineRunner
│
├── scripts/
│   ├── run_ui.py            ← Khởi động Web UI
│   └── main.py              ← CLI entry point
│
├── .env                     ← Cấu hình (KHÔNG commit)
└── .env.example             ← Template
```

---

## Lệnh tham khảo nhanh

```bash
# ── Khởi động ──────────────────────────────────────────────────────────
python scripts/run_ui.py              # Web UI tại http://localhost:8501
python scripts/main.py translate      # Dịch tất cả (CLI)

# ── Dịch ───────────────────────────────────────────────────────────────
python scripts/main.py retranslate 5              # Dịch lại chương 5
python scripts/main.py stats                      # Xem tiến độ

# ── Data management ────────────────────────────────────────────────────
python scripts/main.py clean glossary
python scripts/main.py clean characters --action merge
python scripts/main.py fix-names
python scripts/main.py fix-names --dry-run

# ── Bible System ───────────────────────────────────────────────────────
python scripts/main.py bible scan
python scripts/main.py bible scan --depth deep
python scripts/main.py bible stats
python scripts/main.py bible query "tên entity"
python scripts/main.py bible ask "câu hỏi về truyện"
python scripts/main.py bible crossref
python scripts/main.py bible consolidate
python scripts/main.py bible export --format markdown
```

---

*LiTTrans v5.6 — Powered by Google Gemini & Anthropic Claude*
