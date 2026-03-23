# LiTTrans v5.3

**Pipeline dịch tự động truyện LitRPG / Tu Tiên** — từ tiếng Anh sang tiếng Việt, nhất quán từ chương 1 đến chương 1000.

> Dùng **Gemini AI** (miễn phí) hoặc **Claude (Anthropic)** làm engine dịch.  
> Giữ nhất quán tên nhân vật, xưng hô, kỹ năng và thuật ngữ xuyên suốt toàn bộ tác phẩm.

---

## Mục lục

- [LiTTrans làm được gì?](#littrans-làm-được-gì)
- [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
- [Lấy API Key (bắt buộc)](#lấy-api-key-bắt-buộc)
- [Cài đặt nhanh](#cài-đặt-nhanh)
  - [Cách 1 — Docker (khuyến nghị cho người mới)](#cách-1--docker-khuyến-nghị-cho-người-mới)
  - [Cách 2 — Chạy trực tiếp trên máy](#cách-2--chạy-trực-tiếp-trên-máy)
- [Cấu hình `.env`](#cấu-hình-env)
- [Bắt đầu dịch](#bắt-đầu-dịch)
  - [Dùng Web UI (dễ nhất)](#dùng-web-ui-dễ-nhất)
  - [Dùng CLI (nâng cao)](#dùng-cli-nâng-cao)
- [Tính năng chính](#tính-năng-chính)
- [Bible System — Knowledge Base toàn tác phẩm](#bible-system--knowledge-base-toàn-tác-phẩm)
- [Pipeline hoạt động như thế nào?](#pipeline-hoạt-động-như-thế-nào)
- [Xử lý sự cố thường gặp](#xử-lý-sự-cố-thường-gặp)
- [Tất cả tùy chọn cấu hình](#tất-cả-tùy-chọn-cấu-hình)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)

---

## LiTTrans làm được gì?

Khi dịch truyện dài hàng trăm chương bằng AI thông thường, bạn sẽ gặp vấn đề: **nhân vật bị gọi bằng 5 cái tên khác nhau, xưng hô loạn xạ, kỹ năng dịch mỗi chương một kiểu**. LiTTrans giải quyết điều này bằng cách xây dựng "bộ nhớ" cho toàn bộ quá trình dịch.

| Vấn đề thường gặp | LiTTrans giải quyết như thế nào |
|---|---|
| Tên nhân vật bị dịch khác nhau | **Name Lock** — chốt cứng một bản dịch duy nhất |
| Xưng hô "anh/em" → "ta/ngươi" loạn | **EPS** — theo dõi mức độ thân mật từng cặp nhân vật |
| Kỹ năng dịch mỗi chương một kiểu | **Skills DB** — lưu và tái sử dụng tên kỹ năng |
| AI quên bối cảnh chương trước | **Arc Memory + Scout AI** — tóm tắt và nhắc bối cảnh |
| Phải ngồi canh từng chương | **Batch pipeline** — tự động chạy hết queue, có retry |

---

## Yêu cầu hệ thống

**Cách Docker:** Chỉ cần cài [Docker Desktop](https://www.docker.com/products/docker-desktop/). Không cần Python.

**Cách chạy trực tiếp:** Python 3.11 trở lên.

```bash
# Kiểm tra phiên bản Python
python --version
# Phải hiện: Python 3.11.x hoặc cao hơn

# Kiểm tra Docker
docker --version
```

---

## Lấy API Key (bắt buộc)

### Gemini API Key — **bắt buộc, miễn phí**

1. Truy cập [aistudio.google.com](https://aistudio.google.com) và đăng nhập bằng tài khoản Google
2. Nhấn **"Get API key"** → **"Create API key"**
3. Copy key (dạng `AIzaSy...`)

> **Gói miễn phí:** Gemini Flash cho phép khoảng 1.000 request/ngày. Đủ để dịch 30–50 chương/ngày.  
> **Mẹo:** Tạo 2–3 key từ các tài khoản khác nhau để dùng làm fallback (`FALLBACK_KEY_1`, `FALLBACK_KEY_2`).

### Anthropic API Key — tùy chọn (Dual-Model)

Nếu muốn dùng Claude làm engine dịch chính thay vì Gemini:

1. Truy cập [console.anthropic.com](https://console.anthropic.com) → **API Keys** → **Create Key**
2. Copy key (dạng `sk-ant-...`) và thêm vào `.env`

---

## Cài đặt nhanh

### Cách 1 — Docker (khuyến nghị cho người mới)

> Không cần cài Python, không lo lỗi thư viện, chạy được ngay.

**Bước 1: Clone project**
```bash
git clone <repo-url>
cd littrans
```

**Bước 2: Tạo thư mục và file cấu hình**
```bash
make init
```
Lệnh này tạo tất cả thư mục cần thiết và file `.env` từ template.

**Bước 3: Điền API Key**

Mở file `.env` vừa tạo và điền vào:
```env
GEMINI_API_KEY=AIzaSy...   # ← thay bằng key của bạn
```

**Bước 4: Build Docker image** (chỉ cần làm 1 lần, mất 3–5 phút)
```bash
make build
```

**Bước 5: Khởi động**
```bash
make ui
```

Mở trình duyệt: **http://localhost:8501** ✅

---

### Cách 2 — Chạy trực tiếp trên máy

**Bước 1: Clone và tạo môi trường ảo**
```bash
git clone <repo-url>
cd littrans

python -m venv .venv

# macOS / Linux:
source .venv/bin/activate

# Windows PowerShell:
# .venv\Scripts\activate
```

**Bước 2: Cài thư viện**
```bash
pip install -e .
pip install ".[fast]"        # pyahocorasick — tăng tốc filter glossary 10x (khuyến nghị)
pip install streamlit pandas  # nếu dùng Web UI
pip install anthropic          # nếu muốn dùng Claude
```

**Bước 3: Tạo file cấu hình**
```bash
cp .env.example .env
# Mở .env và điền GEMINI_API_KEY
```

**Bước 4: Khởi động Web UI**
```bash
python scripts/run_ui.py
```

Mở trình duyệt: **http://localhost:8501** ✅

---

## Cấu hình `.env`

File `.env` là nơi bạn điều chỉnh toàn bộ hoạt động của pipeline. Dưới đây là các thiết lập quan trọng nhất:

```env
# ── BẮT BUỘC ──────────────────────────────────────────────────────
GEMINI_API_KEY=AIzaSy...

# ── NÊN CÓ (giảm downtime khi bị rate limit) ─────────────────────
FALLBACK_KEY_1=AIzaSy...    # key dự phòng 1 (tài khoản Google khác)
FALLBACK_KEY_2=AIzaSy...    # key dự phòng 2

# ── CHỌN MODEL DỊCH ───────────────────────────────────────────────
TRANSLATION_PROVIDER=gemini          # gemini (mặc định) hoặc anthropic
TRANSLATION_MODEL=gemini-2.5-flash   # để trống = dùng mặc định
# ANTHROPIC_API_KEY=sk-ant-...       # cần nếu dùng anthropic

# ── TỐC ĐỘ & ỔN ĐỊNH ──────────────────────────────────────────────
SUCCESS_SLEEP=30       # nghỉ 30s sau mỗi chương (tránh rate limit)
RATE_LIMIT_SLEEP=60    # nghỉ 60s khi bị 429
MAX_RETRIES=5          # thử lại tối đa 5 lần

# ── BIBLE SYSTEM (tùy chọn) ───────────────────────────────────────
BIBLE_MODE=false       # bật lên khi muốn dùng knowledge base
```

> **Sau khi thay đổi `.env`:** Khởi động lại pipeline để áp dụng. Nếu dùng Web UI, vào tab **⚙️ Cài đặt** để chỉnh trực tiếp không cần sửa file.

---

## Bắt đầu dịch

### Dùng Web UI (dễ nhất)

**Bước 1: Đặt file chương vào thư mục `inputs/`**

Mỗi chương là một file `.txt` hoặc `.md`. Đặt tên file theo thứ tự để pipeline dịch đúng thứ tự:
```
inputs/
  chapter_001.txt
  chapter_002.txt
  chapter_003.txt
  ...
```

Bạn cũng có thể upload trực tiếp qua tab **📄 Dịch** trong Web UI.

**Bước 2: Nhấn "▶ Chạy pipeline"**

Pipeline sẽ tự động dịch tất cả chương chưa có bản dịch. Bản dịch được lưu vào `outputs/` với tên `chapter_001_VN.txt`.

**Bước 3: Xem kết quả trong tab "🔍 Xem chương"**

Giao diện hiển thị song song EN/VN, có thể tải xuống hoặc dịch lại từng chương.

---

### Dùng CLI (nâng cao)

```bash
# Dịch tất cả chương chưa dịch
python scripts/main.py translate

# Dịch lại 1 chương cụ thể (theo số thứ tự hoặc tên file)
python scripts/main.py retranslate 5
python scripts/main.py retranslate "chapter_005"

# Xem tiến độ và thống kê
python scripts/main.py stats

# Xác nhận thuật ngữ mới do Scout đề xuất
python scripts/main.py clean glossary

# Merge nhân vật mới vào database
python scripts/main.py clean characters --action merge

# Sửa lỗi tên vi phạm Name Lock
python scripts/main.py fix-names
```

**Dùng qua Docker (Makefile):**
```bash
make translate              # dịch tất cả
make CHAPTER=5 retranslate  # dịch lại chương 5
make stats                  # xem thống kê
make clean-glossary         # xác nhận thuật ngữ
make merge-chars            # merge nhân vật
make shell                  # mở shell debug trong container
```

---

## Tính năng chính

### 🔒 Name Lock — Chốt tên nhất quán

Một khi tên đã được dịch (ví dụ: "Xiao Yan" → "Tiêu Viêm"), nó sẽ được **chốt cứng** trong toàn bộ pipeline. Mọi lần xuất hiện sau đó đều bắt buộc dùng bản dịch này — kể cả khi AI "nghĩ" một cách khác. Vi phạm sẽ bị phát hiện và ghi log tự động.

### 💬 EPS — Theo dõi mức độ thân mật

Xưng hô trong truyện Việt phụ thuộc rất nhiều vào quan hệ nhân vật. LiTTrans theo dõi **5 mức độ thân mật (EPS 1–5)** cho từng cặp nhân vật:

| Mức | Tên | Ý nghĩa thực tế |
|---|---|---|
| 1 | FORMAL | Lạnh lùng, xa cách — giữ kính ngữ |
| 2 | NEUTRAL | Mặc định — theo dynamic đã chốt |
| 3 | FRIENDLY | Thân thiện — câu ngắn hơn, thoải mái |
| 4 | CLOSE | Rất thân — bỏ kính ngữ, có thể dùng nickname |
| 5 | INTIMATE | Ngôn ngữ riêng tư — yêu/gia đình gần gũi |

### 🔭 Scout AI — Đọc trước, ghi nhớ bối cảnh

Trước mỗi N chương, Scout AI sẽ:
- Ghi chú mạch truyện đặc biệt (flashback, hồi ký, alias đang dùng)
- Cập nhật trạng thái cảm xúc nhân vật (angry/hurt/changed)
- Phát hiện thuật ngữ mới và đề xuất thêm vào Glossary
- Tóm tắt sự kiện vào Arc Memory để không mất bối cảnh dài hạn

### 🧹 Post-processor 14-pass

Sau mỗi lần dịch, bản dịch được tự động làm sạch bằng 14 bước xử lý thuần code (không dùng AI):
- Chuẩn hóa dấu câu, em dash, ellipsis
- Tách lượt thoại bị gộp nhầm
- Xóa dòng trống thừa trong system box
- Xóa lời mở đầu/kết thúc do AI tự thêm vào
- ...và 9 bước khác

### 🤖 Dual-Model

Sử dụng **hai model AI khác nhau** cho hai mục đích khác nhau:

| Nhiệm vụ | Model | Lý do |
|---|---|---|
| Scout / Pre-call / Post-call | Gemini (miễn phí) | Phân tích ngắn, ít tốn quota |
| Dịch chính (Trans-call) | Gemini hoặc Claude | Cần chất lượng cao nhất |

```env
# Dùng Claude để dịch, Gemini cho các bước còn lại:
TRANSLATION_PROVIDER=anthropic
TRANSLATION_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Bible System — Knowledge Base toàn tác phẩm

Bible System xây dựng một **knowledge base có cấu trúc** từ toàn bộ tác phẩm, gồm 3 tầng:

```
Tầng 1 — Database:   nhân vật, kỹ năng, địa danh, vật phẩm, tổ chức, khái niệm
Tầng 2 — WorldBuilding:  hệ thống tu luyện, quy luật thế giới, địa lý, vũ trụ quan
Tầng 3 — Main Lore:  tóm tắt chương, plot threads, revelations, timeline sự kiện
```

Khi bật `BIBLE_MODE=true`, pipeline dùng Bible thay cho các file riêng lẻ — cho phép dịch với ngữ cảnh phong phú hơn nhiều.

### Khởi động Bible System

```bash
# Bước 1: Scan toàn bộ chương vào Bible
python scripts/main.py bible scan

# Bước 2: Bật Bible Mode trong .env
# BIBLE_MODE=true

# Bước 3: Dịch như thường — pipeline tự dùng Bible
python scripts/main.py translate
```

### Các lệnh Bible

```bash
# Scan với độ sâu khác nhau
python scripts/main.py bible scan --depth quick     # nhanh, chỉ entities
python scripts/main.py bible scan --depth standard  # đầy đủ (mặc định)
python scripts/main.py bible scan --depth deep      # kỹ nhất + loại trùng

# Tìm kiếm entity
python scripts/main.py bible query "Tiêu Viêm"
python scripts/main.py bible query "Arthur" --type character

# Hỏi AI về nội dung truyện
python scripts/main.py bible ask "Ai là kẻ thù chính của MC?"

# Kiểm tra mâu thuẫn cốt truyện
python scripts/main.py bible crossref

# Xuất báo cáo
python scripts/main.py bible export --format markdown
python scripts/main.py bible export --format timeline
python scripts/main.py bible export --format characters
```

| Depth | Tốc độ | Nội dung | Dùng khi nào |
|---|---|---|---|
| `quick` | Nhanh nhất | Chỉ entities | Lần đầu, muốn có data nhanh |
| `standard` | Trung bình | Đầy đủ 3 tầng | Dùng hàng ngày ✓ |
| `deep` | Chậm nhất | Standard + loại duplicate | Cần data chất lượng cao |

---

## Pipeline hoạt động như thế nào?

Mỗi chương đi qua **4 bước** theo thứ tự:

```
① PRE-CALL
   Gemini đọc chương, tạo "Chapter Map":
   - Tên/kỹ năng nào xuất hiện? Đã lock chưa?
   - Xưng hô đang active giữa các cặp nhân vật?
   - Có flashback, alias đặc biệt không?
        ↓
② TRANS-CALL
   Dịch với full context:
   [Hướng dẫn] + [Glossary] + [Profile nhân vật] + [Chapter Map]
   + [Arc Memory] + [Name Lock Table] + [Bible data nếu bật]
        ↓
③ POST-PROCESSOR (14 pass, không dùng AI)
   Làm sạch: dấu câu, dòng trống, lời mở đầu thừa, system box...
        ↓
④ POST-CALL
   Gemini review chất lượng:
   - Có tên bị sai không? Pronoun bị lệch không?
   - Extract nhân vật mới, thuật ngữ mới, thay đổi quan hệ
   → Nếu phát hiện lỗi nghiêm trọng: quay lại ② retry
```

**Scout AI** chạy song song, mỗi N chương (mặc định N=5):
```
Scout đọc N chương gần nhất
→ Cập nhật Context Notes (mạch truyện, xưng hô active)
→ Append Arc Memory (tóm tắt sự kiện dài hạn)
→ Cập nhật Emotion State nhân vật
→ Đề xuất thuật ngữ mới vào Staging
```

---

## Xử lý sự cố thường gặp

### ❌ "Thiếu GEMINI_API_KEY"

```
❌ Thiếu GEMINI_API_KEY trong .env
```

Mở file `.env` và điền key:
```env
GEMINI_API_KEY=AIzaSy...
```

---

### ❌ Bị rate limit liên tục (lỗi 429)

Pipeline tự xử lý rate limit và retry. Nếu vẫn bị:

```env
# Thêm key dự phòng
FALLBACK_KEY_1=AIzaSy...
FALLBACK_KEY_2=AIzaSy...

# Tăng thời gian nghỉ
SUCCESS_SLEEP=60
RATE_LIMIT_SLEEP=120
```

---

### ❌ Tên nhân vật bị dịch sai

```bash
# Xem danh sách vi phạm
python scripts/main.py fix-names --list

# Tự động sửa trong tất cả file đã dịch
python scripts/main.py fix-names

# Xem trước không ghi file (dry run)
python scripts/main.py fix-names --dry-run
```

---

### ❌ Lỗi khi dùng Bible: "Not an Aho-Corasick automaton yet"

Xảy ra khi database rỗng. Chạy scan trước:

```bash
python scripts/main.py bible scan
```

---

### ❌ Staging tích tụ, không được xóa

Nếu quá trình consolidation bị gián đoạn, staging được giữ lại để không mất data. Chạy thủ công:

```bash
python scripts/main.py bible consolidate
```

---

### ❌ Docker: port 8501 bị chiếm

Sửa port trong `deployments/docker-compose.yml`:
```yaml
ports:
  - "8502:8501"   # ← đổi 8501 thành 8502
```

---

### ❌ Windows: lỗi encoding

```bash
set PYTHONUTF8=1
python scripts/main.py translate
```

---

### ❌ Pipeline rất chậm

Cài `pyahocorasick` để tăng tốc glossary matching ~10x:
```bash
pip install pyahocorasick
# hoặc
pip install ".[fast]"
```

---

## Tất cả tùy chọn cấu hình

### API & Model

| Biến | Mặc định | Mô tả |
|---|---|---|
| `GEMINI_API_KEY` | *(bắt buộc)* | API key Gemini chính |
| `FALLBACK_KEY_1` | — | Key dự phòng 1 |
| `FALLBACK_KEY_2` | — | Key dự phòng 2 |
| `KEY_ROTATE_THRESHOLD` | `3` | Lỗi liên tiếp trước khi đổi key |
| `GEMINI_MODEL` | `gemini-2.0-flash-exp` | Model Gemini cho Scout/Pre/Post |
| `TRANSLATION_PROVIDER` | `gemini` | `gemini` hoặc `anthropic` |
| `TRANSLATION_MODEL` | *(tự chọn)* | Để trống = dùng mặc định theo provider |
| `ANTHROPIC_API_KEY` | — | API key Anthropic (nếu dùng Claude) |

### Tốc độ & Ổn định

| Biến | Mặc định | Mô tả |
|---|---|---|
| `MAX_RETRIES` | `5` | Số lần retry tối đa |
| `SUCCESS_SLEEP` | `30` | Nghỉ (giây) sau mỗi chương thành công |
| `RATE_LIMIT_SLEEP` | `60` | Nghỉ (giây) khi bị rate limit |
| `PRE_CALL_SLEEP` | `5` | Nghỉ giữa Pre-call và Trans-call |
| `POST_CALL_SLEEP` | `5` | Nghỉ giữa Trans-call và Post-call |
| `POST_CALL_MAX_RETRIES` | `2` | Retry Trans-call khi Post báo lỗi |
| `TRANS_RETRY_ON_QUALITY` | `true` | Có retry khi phát hiện lỗi dịch thuật |

### Scout AI

| Biến | Mặc định | Mô tả |
|---|---|---|
| `SCOUT_REFRESH_EVERY` | `5` | Chạy Scout mỗi N chương |
| `SCOUT_LOOKBACK` | `10` | Đọc N chương gần nhất |
| `ARC_MEMORY_WINDOW` | `3` | Số arc entry đưa vào prompt |
| `SCOUT_SUGGEST_GLOSSARY` | `true` | Tự động đề xuất thuật ngữ mới |
| `SCOUT_SUGGEST_MIN_CONFIDENCE` | `0.7` | Ngưỡng tin cậy tối thiểu |
| `SCOUT_SUGGEST_MAX_TERMS` | `20` | Thuật ngữ tối đa mỗi lần Scout |

### Bible System

| Biến | Mặc định | Mô tả |
|---|---|---|
| `BIBLE_MODE` | `false` | Dùng Bible khi dịch |
| `BIBLE_SCAN_DEPTH` | `standard` | `quick` / `standard` / `deep` |
| `BIBLE_SCAN_BATCH` | `5` | Consolidate sau mỗi N chương scan |
| `BIBLE_SCAN_SLEEP` | `10` | Nghỉ (giây) giữa các chương khi scan |
| `BIBLE_CROSS_REF` | `true` | Kiểm tra mâu thuẫn sau scan |
| `BIBLE_DIR` | `data/bible` | Thư mục lưu Bible data |

### Nhân vật & Merge

| Biến | Mặc định | Mô tả |
|---|---|---|
| `ARCHIVE_AFTER_CHAPTERS` | `60` | Archive nhân vật sau N chương vắng mặt |
| `EMOTION_RESET_CHAPTERS` | `5` | Reset emotion state sau N chương |
| `IMMEDIATE_MERGE` | `true` | Merge staging ngay sau mỗi chương |
| `AUTO_MERGE_GLOSSARY` | `false` | Tự động clean glossary cuối pipeline |
| `AUTO_MERGE_CHARACTERS` | `false` | Tự động merge nhân vật cuối pipeline |
| `RETRY_FAILED_PASSES` | `3` | Số vòng retry các chương thất bại |
| `BUDGET_LIMIT` | `150000` | Giới hạn token (0 = tắt) |

---

## Cấu trúc thư mục

```
littrans/
│
├── inputs/          ← Đặt file chương gốc (.txt / .md) vào đây
├── outputs/         ← Bản dịch được lưu tại đây (*_VN.txt)
├── data/
│   ├── glossary/    ← Từ điển thuật ngữ (Pathways, Locations, Items...)
│   ├── characters/  ← Profile nhân vật (Active, Archive, Staging)
│   ├── skills/      ← Database kỹ năng
│   ├── memory/      ← Arc Memory + Context Notes
│   └── bible/       ← Bible System (database, worldbuilding, main_lore)
│
├── prompts/
│   ├── system_agent.md        ← Hướng dẫn dịch cho AI
│   ├── character_profile.md   ← Hướng dẫn lập profile nhân vật
│   └── bible_scan.md          ← Prompt cho Bible Scanner
│
├── src/littrans/
│   ├── core/        ← Pipeline, Scout, Prompt Builder, Quality Guard
│   ├── context/     ← Glossary, Characters, Skills, Memory, Bible
│   ├── llm/         ← Gemini + Anthropic client
│   ├── cli/         ← CLI commands
│   └── ui/          ← Web UI (Streamlit)
│
├── scripts/
│   ├── main.py      ← Entry point CLI
│   ├── run_ui.py    ← Entry point Web UI
│   └── reset.py     ← Dọn dẹp data
│
├── .env             ← Cấu hình của bạn (KHÔNG commit lên git)
├── .env.example     ← Template cấu hình
└── Makefile         ← Shortcuts cho Docker
```

---

## Lệnh tham khảo nhanh

```bash
# ── Cài đặt ───────────────────────────────────────────────────────
make init && make build          # Docker: setup lần đầu
python -m venv .venv && pip install -e ".[fast]"  # Local: setup

# ── Dịch ──────────────────────────────────────────────────────────
make ui                          # Khởi động Web UI (Docker)
python scripts/run_ui.py         # Khởi động Web UI (Local)
python scripts/main.py translate # Dịch tất cả (CLI)
make CHAPTER=5 retranslate       # Dịch lại chương 5 (Docker)

# ── Data management ───────────────────────────────────────────────
python scripts/main.py clean glossary              # Xác nhận thuật ngữ mới
python scripts/main.py clean characters --action merge  # Merge nhân vật
python scripts/main.py fix-names                   # Sửa lỗi tên
python scripts/main.py stats                       # Thống kê

# ── Bible System ──────────────────────────────────────────────────
python scripts/main.py bible scan                  # Scan chương mới
python scripts/main.py bible stats                 # Thống kê Bible
python scripts/main.py bible query "tên"           # Tìm entity
python scripts/main.py bible ask "câu hỏi"         # Hỏi AI về truyện
python scripts/main.py bible consolidate           # Consolidate thủ công
python scripts/main.py bible crossref              # Kiểm tra mâu thuẫn
python scripts/main.py bible export --format markdown

# ── Debug & Reset ─────────────────────────────────────────────────
make shell                       # Mở shell trong Docker container
make logs                        # Xem log Web UI realtime
python scripts/reset.py          # Xóa outputs + staging (giữ data)
python scripts/reset.py --full   # Xóa toàn bộ (không thể phục hồi!)
```

---

*LiTTrans v5.3 — Powered by Google Gemini & Anthropic Claude*