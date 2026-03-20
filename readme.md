# LiTTrans v4.2 — LitRPG / Tu Tiên Translation Pipeline

> Pipeline dịch tự động truyện LitRPG / Tu Tiên từ tiếng Anh sang tiếng Việt, chạy bằng **Gemini AI**.  
> Giữ nhất quán tên nhân vật, xưng hô, thuật ngữ và kỹ năng xuyên suốt hàng trăm chương.  
> Có thể dùng qua **CLI** hoặc **Web UI** (Streamlit).

---

## Mục lục

1. [Yêu cầu hệ thống](#1-yêu-cầu-hệ-thống)
2. [Cài đặt](#2-cài-đặt)
3. [Cấu hình `.env`](#3-cấu-hình-env)
4. [Cách dùng — Web UI](#4-cách-dùng--web-ui)
5. [Cách dùng — CLI](#5-cách-dùng--cli)
6. [Cấu trúc thư mục](#6-cấu-trúc-thư-mục)
7. [Pipeline chi tiết](#7-pipeline-chi-tiết)
8. [Data layer](#8-data-layer)
9. [Scout AI & Memory](#9-scout-ai--memory)
10. [Name Lock & Quality Guard](#10-name-lock--quality-guard)
11. [Điểm mạnh & hạn chế](#11-điểm-mạnh--hạn-chế)

---

## 1. Yêu cầu hệ thống

| Thành phần | Yêu cầu tối thiểu |
|---|---|
| Python | **3.11** trở lên |
| Gemini API key | Bắt buộc — lấy tại [aistudio.google.com](https://aistudio.google.com) |
| RAM | 512 MB (không load model local) |
| Hệ điều hành | Windows / macOS / Linux |

---

## 2. Cài đặt

```bash
# 1. Clone hoặc giải nén project
git clone <repo-url>
cd littrans

# 2. (Khuyến nghị) Tạo virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows

# 3. Cài dependencies cốt lõi (CLI)
pip install -e .

# 4. Cài Aho-Corasick để filter glossary nhanh ~10x (khuyến nghị)
pip install ".[fast]"

# 5. Cài thêm nếu muốn dùng Web UI
pip install streamlit pandas
```

> **Windows:** nếu gặp lỗi encoding khi chạy, thêm `set PYTHONUTF8=1` trước lệnh.

---

## 3. Cấu hình `.env`

Sao chép file mẫu rồi điền thông tin:

```bash
cp .env.example .env
```

Mở `.env` và chỉnh các giá trị sau:

```env
# ── BẮT BUỘC ──────────────────────────────────────────────────────
GEMINI_API_KEY=AIzaSy...          # API key chính

# ── TÙY CHỌN — Key dự phòng (rotate khi primary bị rate limit) ───
FALLBACK_KEY_1=                   # Key dự phòng 1
FALLBACK_KEY_2=                   # Key dự phòng 2
KEY_ROTATE_THRESHOLD=3            # Số lỗi liên tiếp trước khi chuyển key

# ── MODEL ─────────────────────────────────────────────────────────
GEMINI_MODEL=gemini-2.5-flash     # Khuyến nghị: flash (nhanh, rẻ) hoặc pro (chất lượng cao)

# ── PIPELINE ──────────────────────────────────────────────────────
USE_THREE_CALL=true               # true = Pre+Trans+Post call | false = 1-call legacy
MAX_RETRIES=5
SUCCESS_SLEEP=30                  # Nghỉ (giây) sau mỗi chương thành công
RATE_LIMIT_SLEEP=60               # Nghỉ (giây) khi bị rate limit 429

# ── SCOUT AI ──────────────────────────────────────────────────────
SCOUT_REFRESH_EVERY=5             # Chạy Scout mỗi N chương
SCOUT_LOOKBACK=10                 # Đọc N chương gần nhất
ARC_MEMORY_WINDOW=3               # Số arc entry đưa vào prompt

# ── TOKEN BUDGET ──────────────────────────────────────────────────
BUDGET_LIMIT=150000               # 0 = tắt giới hạn

# ── ĐƯỜNG DẪN (thường không cần đổi) ─────────────────────────────
INPUT_DIR=inputs
OUTPUT_DIR=outputs
DATA_DIR=data
```

> **Tip:** Nếu dùng Web UI, tất cả các tham số trên đều có thể chỉnh trực tiếp trong tab **Cài đặt** mà không cần sửa file `.env` thủ công.

---

## 4. Cách dùng — Web UI

Web UI là cách dùng được khuyến nghị cho người không quen CLI.

### Khởi động

```bash
python run_ui.py
```

Mở trình duyệt và truy cập: **http://localhost:8501**

```bash
# Đổi port nếu 8501 đã bị dùng
python run_ui.py --port 8502

# Mở cho máy khác trong cùng mạng LAN truy cập
python run_ui.py --host 0.0.0.0 --port 8501
```

---

### Lần đầu sử dụng (Web UI)

#### Bước 1 — Cài API key

Mở tab **⚙️ Cài đặt → 🔑 API**, điền `GEMINI_API_KEY`, nhấn **💾 Lưu .env**.

#### Bước 2 — Upload file chương

Mở tab **📄 Dịch**, kéo thả file `.txt` hoặc `.md` vào ô upload.  
File sẽ được lưu vào thư mục `inputs/` tự động.

> **Định dạng file:** Mỗi file = một chương. Đặt tên theo thứ tự để pipeline sắp xếp đúng.  
> Ví dụ: `chapter_001.txt`, `chapter_002.txt`, ...

#### Bước 3 — Chạy pipeline

Nhấn **▶ Chạy pipeline**. Log sẽ stream theo thời gian thực, hiển thị từng bước:
- Scout AI phân tích context
- Pre-call xác định tên / skill / xưng hô
- Trans-call dịch nội dung
- Post-call kiểm tra chất lượng + extract metadata

#### Bước 4 — Xem kết quả

Mở tab **🔍 Xem chương**:
- Click tên chương bên trái để xem chi tiết
- Tab **Song song**: EN trái / VN phải, cuộn đồng bộ
- Tab **Bản dịch**: xem toàn văn + nút tải xuống
- Tab **Diff**: highlight đoạn mới / thay đổi so với gốc

---

### Các tính năng Web UI

| Tab | Chức năng chính |
|---|---|
| 📄 **Dịch** | Upload file, xem trạng thái từng chương, chạy pipeline, xem log real-time |
| 🔍 **Xem chương** | Song song EN/VN, diff, xem raw, tải xuống, **dịch lại** |
| 👤 **Nhân vật** | Card profile, pronoun pairs strong/weak, emotion state |
| 📚 **Từ điển** | Xem/tìm kiếm glossary theo category, clean staging terms |
| 📊 **Thống kê** | Tiến độ, tokens, name lock violations, biểu đồ glossary |
| ⚙️ **Cài đặt** | 7 nhóm tham số: API, Pipeline, Scout AI, Nhân vật, Token Budget, Merge & Retry, Đường dẫn |

---

### Dịch lại một chương (Web UI)

1. Mở tab **🔍 Xem chương**
2. Click chương cần dịch lại
3. Nhấn **↺ Dịch lại…** ở cuối trang
4. Chọn tuỳ chọn:
   - ☑ **Cập nhật data** — cập nhật Glossary / Characters / Skills sau khi dịch lại
   - ☑ **Chạy Scout AI trước** — phân tích lại context trước khi dịch
5. Nhấn **⚡ Xác nhận dịch lại**

> ⚠️ Bản dịch cũ sẽ bị ghi đè.

---

## 5. Cách dùng — CLI

CLI phù hợp cho chạy batch, automation, hoặc server không có giao diện đồ hoạ.

### Workflow cơ bản

```bash
# 1. Đặt file chương vào inputs/
#    (mỗi file .txt hoặc .md = một chương)

# 2. Dịch tất cả chương chưa dịch
python main.py translate

# 3. Sau khi dịch xong — phân loại thuật ngữ mới
python main.py clean glossary

# 4. Merge nhân vật mới vào Active
python main.py clean characters --action merge

# 5. Sửa vi phạm Name Lock (nếu có)
python main.py fix-names
```

---

### Tất cả lệnh CLI

#### `translate` — Dịch hàng loạt

```bash
python main.py translate
```

Dịch tất cả chương trong `inputs/` chưa có bản dịch tương ứng trong `outputs/`.  
Pipeline tự động bỏ qua chương đã dịch, chạy Scout AI theo chu kỳ, và retry khi lỗi.

---

#### `retranslate` — Dịch lại một chương

```bash
# Chọn theo số thứ tự
python main.py retranslate 42

# Chọn theo keyword trong tên file
python main.py retranslate "chapter_100"

# Xem danh sách tất cả chương trước khi chọn
python main.py retranslate --list

# Dịch lại và cập nhật Glossary / Characters / Skills
python main.py retranslate 42 --update-data
```

---

#### `clean glossary` — Phân loại thuật ngữ

```bash
python main.py clean glossary
```

Đọc `Staging_Terms.md` + section "Mới" trong các Glossary file → dùng Gemini phân loại vào 5 category → append vào đúng file, backup file cũ.

---

#### `clean characters` — Quản lý nhân vật

```bash
# Xem toàn bộ profile đang active
python main.py clean characters --action review

# Merge Staging_Characters.json → Characters_Active.json
python main.py clean characters --action merge

# Tự động sửa lỗi nhỏ (archetype sai, field thiếu...)
python main.py clean characters --action fix

# Xuất báo cáo Markdown vào Reports/
python main.py clean characters --action export

# Kiểm tra schema, cảnh báo profile thiếu thông tin
python main.py clean characters --action validate

# Xem nhân vật trong Archive
python main.py clean characters --action archive
```

---

#### `fix-names` — Sửa vi phạm Name Lock

```bash
# Xem danh sách vi phạm
python main.py fix-names --list

# Xem trước thay đổi (không ghi file)
python main.py fix-names --dry-run

# Sửa thật (chỉ các chương có vi phạm)
python main.py fix-names

# Sửa toàn bộ tất cả chương
python main.py fix-names --all-chapters

# Xóa toàn bộ name_fixes.json
python main.py fix-names --clear
```

---

#### `stats` — Thống kê nhanh

```bash
python main.py stats
```

In bảng: số nhân vật Active / Archive / Staging, số thuật ngữ theo category, kỹ năng, Name Lock entries, trạng thái API keys.

---

### Workflow nâng cao (CLI)

```bash
# Kiểm tra chất lượng data trước khi dịch tiếp
python main.py clean characters --action validate
python main.py stats
python main.py fix-names --list

# Dịch lại chương có vấn đề và cập nhật data
python main.py retranslate 55 --update-data

# Xem nhân vật đã archive (lâu không xuất hiện)
python main.py clean characters --action archive

# Xuất báo cáo nhân vật ra file Markdown
python main.py clean characters --action export
# → Reports/character_report_YYYYMMDD_HHMM.md
```

---

## 6. Cấu trúc thư mục

```
littrans/
├── main.py                          # Entry point CLI
├── run_ui.py                        # Entry point Web UI  ← MỚI
├── .env                             # Cấu hình (tạo từ .env.example)
├── .env.example                     # Template cấu hình
├── pyproject.toml
├── requirements.txt
│
├── src/littrans/
│   ├── cli.py                       # Typer CLI — tất cả commands
│   ├── config/
│   │   └── settings.py              # Singleton Settings (dataclass + dotenv)
│   │
│   ├── engine/
│   │   ├── pipeline.py              # Orchestrator chính
│   │   ├── scout.py                 # Scout AI (context notes, arc, emotion)
│   │   ├── prompt_builder.py        # Xây system prompt 8 sections
│   │   ├── pre_processor.py         # Pre-call: chapter map
│   │   ├── post_analyzer.py         # Post-call: quality review + metadata
│   │   └── quality_guard.py         # Kiểm tra cơ học bản dịch
│   │
│   ├── managers/
│   │   ├── glossary.py              # Glossary filter + Aho-Corasick + write
│   │   ├── characters.py            # Character tiers + emotion + relationships
│   │   ├── skills.py                # Skills.json + evolution chain
│   │   ├── name_lock.py             # Name Lock table + validation
│   │   └── memory.py                # Arc Memory + Context Notes
│   │
│   ├── llm/
│   │   ├── client.py                # ApiKeyPool + call_gemini*
│   │   ├── schemas.py               # Pydantic schemas + GEMINI_SCHEMA
│   │   └── token_budget.py          # Smart context truncation
│   │
│   ├── tools/
│   │   ├── clean_glossary.py        # AI categorization + merge
│   │   ├── clean_characters.py      # review/merge/fix/export/validate
│   │   └── fix_names.py             # Sửa vi phạm Name Lock hàng loạt
│   │
│   ├── ui/                          # ← MỚI — Web UI package
│   │   ├── __init__.py
│   │   ├── app.py                   # Streamlit app — 6 trang
│   │   └── runner.py                # Background thread + stdout capture
│   │
│   └── utils/
│       ├── io_utils.py              # load_text, load_json, atomic_write
│       ├── data_versioning.py       # backup + restore + prune
│       ├── text_normalizer.py       # Chuẩn hoá raw EN text
│       └── logger.py                # get_logger, log_error, log_warning
│
├── prompts/
│   ├── system_agent.md              # Hướng dẫn dịch chính (XML structured)
│   └── character_profile.md         # Hướng dẫn lập profile nhân vật
│
├── inputs/                          # ← Đặt file chương gốc (.txt / .md) vào đây
├── outputs/                         # Bản dịch (*_VN.txt) — tự sinh
├── data/
│   ├── glossary/
│   │   ├── Glossary_Pathways.md
│   │   ├── Glossary_Organizations.md
│   │   ├── Glossary_Items.md
│   │   ├── Glossary_Locations.md
│   │   ├── Glossary_General.md
│   │   └── Staging_Terms.md         # Buffer chờ phân loại
│   ├── characters/
│   │   ├── Characters_Active.json
│   │   ├── Characters_Archive.json
│   │   └── Staging_Characters.json
│   ├── skills/
│   │   └── Skills.json
│   ├── memory/
│   │   ├── Arc_Memory.md
│   │   └── Context_Notes.md
│   └── name_fixes.json              # Vi phạm Name Lock chờ sửa
├── logs/
│   └── pipeline.log
└── Reports/                         # Báo cáo từ clean characters --export
```

---

## 7. Pipeline chi tiết

### Luồng xử lý mỗi chương (3-call mode)

```
Input file
  ↓
[Scout AI — mỗi N chương]
  → Xoá Context_Notes.md cũ, sinh mới (4 mục)
  → Append Arc_Memory.md (chống trùng lặp)
  → Cập nhật emotional_state nhân vật
  ↓
Build context
  → filter_glossary()    — Aho-Corasick, chỉ lấy term xuất hiện trong chương
  → filter_characters()  — chỉ lấy nhân vật liên quan
  → load_skills_for_chapter()
  → build_name_lock_table()
  ↓
Pre-call (Gemini)
  → Xác định tên / skill / pronoun pair đang active
  → Phát hiện alias, scene bất thường
  → Output: ChapterMap
  ↓
Trans-call (Gemini)
  → System prompt 8 sections + ChapterMap
  → Output: plain text bản dịch
  ↓
Quality Guard (mechanical)
  → 7 tiêu chí: dính dòng, thiếu dòng trống, mất đoạn, dòng chưa dịch, system box...
  → Retry nếu fail (tối đa MAX_RETRIES)
  ↓
Post-call (Gemini)
  → Review chất lượng dịch thuật (name leak, pronoun sai, đoạn mất)
  → Auto-fix lỗi trình bày (plain-text call riêng)
  → Extract metadata: new_terms, new_characters, relationship_updates, skill_updates
  → Retry Trans-call nếu có lỗi retry_required
  ↓
Name Lock validate
  → Quét bản dịch, ghi vi phạm vào data/name_fixes.json
  ↓
atomic_write() → outputs/*_VN.txt
  ↓
Update data
  → add_new_terms()         → Glossary (immediate hoặc Staging)
  → add_skill_updates()     → Skills.json
  → update_from_response()  → Characters (immediate hoặc Staging)
```

### Token Budget — Thứ tự cắt khi vượt ngưỡng

| Ưu tiên | Thành phần | Hành động |
|---|---|---|
| Không bao giờ cắt | Name Lock + Instructions | — |
| 1 | Arc Memory | Giảm xuống 1 entry gần nhất |
| 2 | Staging glossary | Bỏ hoàn toàn |
| 3 | Character profiles phụ | Giữ top 5 liên quan nhất |
| 4 (last resort) | Toàn bộ Arc Memory | Bỏ hoàn toàn |

---

## 8. Data layer

### Glossary

5 file category + 1 staging. Format mỗi dòng: `- English term: Bản dịch tiếng Việt`

| File | Nội dung |
|---|---|
| `Glossary_Pathways.md` | Hệ thống tu luyện, Sequence, cảnh giới |
| `Glossary_Organizations.md` | Tổ chức, hội phái, bang nhóm |
| `Glossary_Items.md` | Vật phẩm, vũ khí, đan dược, artifact |
| `Glossary_Locations.md` | Địa danh, thành phố, cõi giới, dungeon |
| `Glossary_General.md` | Thuật ngữ chung, tên nhân vật |
| `Staging_Terms.md` | Buffer chờ phân loại (tự động thêm vào đây) |

### Characters

3 tầng JSON:

- **Active** — nhân vật xuất hiện gần đây, full profile
- **Archive** — tự động rotate sau `ARCHIVE_AFTER_CHAPTERS` chương không thấy
- **Staging** — mới extract từ AI, chờ merge

Mỗi profile gồm: `identity`, `power`, `speech` (pronoun_self, formality, how_refers_to_others, quirks), `habitual_behaviors` (confidence ≥ 0.65), `relationships` (pronoun_status: weak/strong), `arc_status`, `emotional_state`.

### Skills

`Skills.json` lưu kỹ năng với evolution chain:

```json
{
  "skills": {
    "Fireball": {
      "vietnamese": "[Hỏa Cầu]",
      "owner": "Arthur",
      "evolved_from": "",
      "evolution_chain": ["[Hỏa Cầu]"],
      "first_seen": "chapter_001.txt"
    }
  }
}
```

### Name Lock

Tự build từ `canonical_name` + `alias_canonical_map` trong Characters, và `Glossary_Organizations/Locations/General`. Đặt ở **Phần 8** (cuối) system prompt để có attention cao nhất.

---

## 9. Scout AI & Memory

### Context Notes (ngắn hạn)

Xoá và tạo mới `Context_Notes.md` mỗi `SCOUT_REFRESH_EVERY` chương. Gồm 4 mục:

1. Mạch truyện đặc biệt (flashback, hồi ký, giấc mơ)
2. Khoá xưng hô đang active (từng cặp nhân vật)
3. Diễn biến gần nhất (3–5 sự kiện)
4. Cảnh báo cho AI dịch

### Arc Memory (dài hạn)

`Arc_Memory.md` chỉ **APPEND**, không bao giờ xoá. Chống trùng lặp bằng cách extract data đã có → truyền vào prompt AI ("đã biết — KHÔNG ghi lại") → post-process loại dòng trùng (exact + fuzzy 75%).

### Emotion Tracker

Scout phân tích cảm xúc nhân vật cuối mỗi window: `normal` / `angry` / `hurt` / `changed`. Prompt hiển thị cảnh báo nổi bật khi state ≠ normal. Auto-reset về normal sau `EMOTION_RESET_CHAPTERS` chương.

---

## 10. Name Lock & Quality Guard

### Name Lock

Quy tắc cứng — không ngoại lệ:
- Tên có trong bảng → **bắt buộc** dùng bản chuẩn, không dùng tên gốc EN
- Tên không có trong bảng → giữ nguyên EN, ghi vào `new_terms`
- Conflict → giữ bản lock đầu tiên, log cảnh báo

Sau khi dịch, pipeline tự validate và ghi vi phạm vào `data/name_fixes.json`. Dùng `fix-names` để sửa hàng loạt.

### Quality Guard — 7 tiêu chí

| # | Tiêu chí | Ngưỡng |
|---|---|---|
| 1 | Dòng quá dài (dính dòng nghiêm trọng) | > 1000 ký tự |
| 2 | Quá ít dòng | < 10 dòng không rỗng |
| 3 | Mất dòng so với bản gốc | > 50% |
| 4 | Thiếu dòng trống | blank ratio < 20% |
| 5 | Bản dịch quá ngắn | < 45% độ dài bản gốc |
| 6 | Còn dòng tiếng Anh chưa dịch | > 15% dòng |
| 7 | System box có dòng trống thừa bên trong | ≥ 3 chỗ |

---

## 11. Điểm mạnh & hạn chế

### Điểm mạnh

**Nhất quán xuyên suốt** — Name Lock + relationship `pronoun_status` (weak/strong) + priority chain 4 tầng đảm bảo xưng hô không dao động qua hàng trăm chương.

**Context thông minh** — Filter glossary/character/skills chỉ lấy nội dung liên quan. Token Budget tự cắt theo thứ tự ưu tiên khi vượt ngưỡng.

**Bộ nhớ dài hạn** — Arc Memory append-only chống trùng lặp. Context Notes ngắn hạn cung cấp thông tin tức thì.

**Độ bền** — Atomic write, multi-key pool với auto-rotate, retry với exponential backoff, retry pass cuối pipeline.

**Hai giao diện** — CLI cho automation/server, Web UI với live log và split view cho người dùng thông thường.

### Hạn chế hiện tại

**Chỉ hỗ trợ Gemini** — `client.py` gắn cứng với `google-genai`. Không có abstraction cho OpenAI / Claude / local models.

**Không chunking** — Chương rất dài (> 100K ký tự) không được chia nhỏ trước khi gửi. Có thể vượt context window.

**File-based, single-user** — Data dùng chung 1 bộ `inputs/outputs/data/`. Không phù hợp multi-user đồng thời mà không có project isolation.

**Scout tuần tự** — Scout phải chờ trước khi dịch chương tiếp theo. Không có pipeline parallel.

---

## Lệnh tham khảo nhanh

```bash
# ── Khởi động Web UI ──────────────────────────────────────
python run_ui.py
python run_ui.py --port 8502

# ── Workflow CLI cơ bản ───────────────────────────────────
python main.py translate
python main.py clean glossary
python main.py clean characters --action merge
python main.py fix-names
python main.py stats

# ── Xử lý sự cố ──────────────────────────────────────────
python main.py retranslate 55 --update-data
python main.py fix-names --dry-run
python main.py fix-names --list
python main.py clean characters --action validate

# ── Xuất báo cáo ─────────────────────────────────────────
python main.py clean characters --action export
# → Reports/character_report_YYYYMMDD_HHMM.md
```

---

*LiTTrans v4.2 — Powered by Google Gemini*