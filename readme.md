# LiTTrans v4.1 — LitRPG / Tu Tiên Translation Pipeline

> Pipeline dịch tự động truyện LitRPG / Tu Tiên từ tiếng Anh sang tiếng Việt, chạy bằng **Gemini AI**. Giữ nhất quán tên nhân vật, xưng hô, thuật ngữ và kỹ năng xuyên suốt hàng trăm chương.

---

## Mục lục

1. [Tổng quan kiến trúc](#1-tổng-quan-kiến-trúc)
2. [Cài đặt](#2-cài-đặt)
3. [Cấu hình `.env`](#3-cấu-hình-env)
4. [Cách dùng (CLI)](#4-cách-dùng-cli)
5. [Pipeline chi tiết](#5-pipeline-chi-tiết)
6. [Data layer](#6-data-layer)
7. [Scout AI & Memory](#7-scout-ai--memory)
8. [Name Lock & Quality Guard](#8-name-lock--quality-guard)
9. [Cấu trúc thư mục](#9-cấu-trúc-thư-mục)
10. [Đánh giá & điểm mạnh / hạn chế](#10-đánh-giá--điểm-mạnh--hạn-chế)

---

## 1. Tổng quan kiến trúc

```
inputs/          →  Pipeline  →  outputs/
(*.txt / *.md)      (Gemini)     (*_VN.txt)
                        ↕
                   data/
                   ├── glossary/        (5 category files + staging)
                   ├── characters/      (Active / Archive / Staging JSON)
                   ├── skills/          (Skills.json — evolution chain)
                   └── memory/          (Arc_Memory.md + Context_Notes.md)
```

**Luồng xử lý mỗi chương:**

```
Input file
  → [Scout AI mỗi N chương]  → Context_Notes.md, Arc_Memory.md
  → Build context             → filter glossary, chars, name lock, skills
  → Prompt builder            → 8-section system prompt + token budget
  → Gemini API call           → TranslationResult (JSON structured output)
  → Quality guard             → retry nếu dính dòng / mất đoạn
  → Write output              → atomic write → outputs/*_VN.txt
  → Update data               → new_terms, new_characters, skill_updates
  → [Loop / Final merge]
```

---

## 2. Cài đặt

**Yêu cầu:** Python ≥ 3.11

```bash
# Clone repo
git clone <repo-url>
cd littrans

# Cài dependencies
pip install -e .

# Cài thêm Aho-Corasick để filter glossary nhanh hơn ~10x (khuyến nghị)
pip install ".[fast]"

# Tạo file cấu hình
cp .env.example .env
# → Điền GEMINI_API_KEY vào .env
```

---

## 3. Cấu hình `.env`

```env
# ── API ──────────────────────────────────────────────
GEMINI_API_KEY=AIza...          # Bắt buộc
FALLBACK_KEY_1=                  # Key dự phòng 1 (optional)
FALLBACK_KEY_2=                  # Key dự phòng 2 (optional)
KEY_ROTATE_THRESHOLD=3           # Số lỗi liên tiếp trước khi rotate key
GEMINI_MODEL=gemini-2.5-flash    # Model sử dụng

# ── Pipeline ─────────────────────────────────────────
MAX_RETRIES=5                    # Số lần retry mỗi chương khi lỗi API
SUCCESS_SLEEP=30                 # Nghỉ (giây) sau mỗi chương thành công
RATE_LIMIT_SLEEP=60              # Nghỉ (giây) khi bị rate limit
MIN_CHARS_PER_CHAPTER=500        # Cảnh báo nếu chương quá ngắn

# ── Scout AI ─────────────────────────────────────────
SCOUT_LOOKBACK=10                # Đọc N chương trước để phân tích
SCOUT_REFRESH_EVERY=5            # Chạy Scout mỗi N chương
ARC_MEMORY_WINDOW=3              # Hiển thị N arc entry gần nhất trong prompt

# ── Characters ───────────────────────────────────────
ARCHIVE_AFTER_CHAPTERS=60        # Archive nhân vật sau N chương không thấy
EMOTION_RESET_CHAPTERS=5         # Reset cảm xúc về "normal" sau N chương

# ── Merge & Retry ────────────────────────────────────
IMMEDIATE_MERGE=true             # Merge staging → active sau mỗi chương
AUTO_MERGE_GLOSSARY=false        # Tự động clean glossary sau pipeline
AUTO_MERGE_CHARACTERS=false      # Tự động merge characters sau pipeline
RETRY_FAILED_PASSES=3            # Số lần retry pass cho chương thất bại

# ── Token Budget (0 = tắt) ───────────────────────────
BUDGET_LIMIT=150000              # Giới hạn token prompt (0 = không giới hạn)

# ── Paths ─────────────────────────────────────────────
INPUT_DIR=inputs
OUTPUT_DIR=outputs
DATA_DIR=data
LOG_DIR=logs
PROMPTS_DIR=prompts
```

---

## 4. Cách dùng (CLI)

```bash
# Dịch tất cả chương chưa dịch
python main.py translate

# Dịch lại một chương cụ thể (chọn theo số thứ tự)
python main.py retranslate 42
python main.py retranslate "chapter_100"     # tìm theo keyword
python main.py retranslate --list            # xem danh sách

# Dịch lại và cập nhật data (glossary, characters, skills)
python main.py retranslate 42 --update-data

# Quản lý glossary
python main.py clean glossary               # phân loại và merge staging terms

# Quản lý characters
python main.py clean characters --action review     # xem toàn bộ profile
python main.py clean characters --action merge      # merge staging → active
python main.py clean characters --action fix        # tự sửa lỗi nhỏ
python main.py clean characters --action export     # xuất báo cáo Markdown
python main.py clean characters --action validate   # kiểm tra schema

# Sửa vi phạm Name Lock
python main.py fix-names --list             # xem vi phạm
python main.py fix-names --dry-run          # xem trước không ghi
python main.py fix-names                    # sửa thật
python main.py fix-names --all-chapters     # sửa toàn bộ chương

# Thống kê nhanh
python main.py stats
```

---

## 5. Pipeline chi tiết

### Bước 1 — Input

`Pipeline.sorted_inputs()` đọc tất cả file `.txt` / `.md` trong `inputs/`, sort theo natural order (chương 1, 2, ..., 10, 11 chứ không phải 1, 10, 11, 2). `_get_pending()` lọc ra những file chưa có bản dịch tương ứng trong `outputs/`.

### Bước 2 — Scout AI (conditional)

Chạy mỗi `SCOUT_REFRESH_EVERY` chương. Scout đọc `SCOUT_LOOKBACK` chương gần nhất và thực hiện 3 việc:

**a. Context Notes** — Xóa `Context_Notes.md` cũ, sinh mới với 4 mục: mạch truyện đặc biệt, khoá xưng hô đang active, diễn biến gần nhất, cảnh báo cho AI dịch.

**b. Arc Memory** — Append-only tóm tắt vào `Arc_Memory.md`. Có cơ chế chống trùng lặp: extract dữ liệu đã có → truyền vào prompt AI → post-process loại dòng trùng.

**c. Emotion Tracker** — Phân tích trạng thái cảm xúc nhân vật chính (normal / angry / hurt / changed), cập nhật vào `Characters_Active.json`. Emotion được hiển thị trong prompt với cảnh báo nổi bật.

### Bước 3 — Build context

`filter_glossary()` dùng Aho-Corasick (nếu cài) hoặc regex để chỉ lấy thuật ngữ XUẤT HIỆN trong chương → giảm kích thước prompt. Tương tự, `filter_characters()` và `load_skills_for_chapter()` chỉ lấy nhân vật/kỹ năng liên quan.

### Bước 4 — Prompt builder (8 sections)

```
PHẦN 1 — Hướng dẫn dịch (prompts/system_agent.md)
PHẦN 2 — Từ điển thuật ngữ (glossary filter + skills đã biết)
PHẦN 3 — Profile nhân vật (emotion warning + xưng hô ưu tiên)
PHẦN 4 — Hướng dẫn lập profile (prompts/character_profile.md)
PHẦN 5 — Yêu cầu đầu ra JSON (5 trường bắt buộc)
PHẦN 6 — Bộ nhớ arc (N entry gần nhất từ Arc_Memory.md)
PHẦN 7 — Ghi chú tức thì (Context_Notes.md từ Scout)
PHẦN 8 — Name Lock Table (ràng buộc CỨNG nhất — đặt cuối)
```

**Token Budget** (`token_budget.py`): nếu prompt vượt `BUDGET_LIMIT × 0.8`, pipeline tự cắt theo thứ tự ưu tiên thấp → cao: arc memory entries → staging glossary → character profiles phụ → toàn bộ arc memory.

### Bước 5 — Gemini API call

`call_gemini()` gọi Gemini với `response_mime_type="application/json"` và `response_schema=GEMINI_SCHEMA` (Pydantic → JSON Schema đã strip `additionalProperties`). Kết quả parse thành `TranslationResult` với 5 trường: `translation`, `new_terms`, `new_characters`, `relationship_updates`, `skill_updates`.

**Multi-key pool**: `ApiKeyPool` quản lý primary key + tối đa 2 fallback. Khi một key bị rate-limit `KEY_ROTATE_THRESHOLD` lần liên tiếp → rotate sang key tiếp theo. Nếu tất cả dead → `AllKeysExhaustedError`.

### Bước 6 — Quality guard

4 tiêu chí kiểm tra:

| Tiêu chí | Ngưỡng | Mô tả |
|----------|--------|-------|
| Dòng quá dài | > 1000 ký tự | Dính dòng nghiêm trọng |
| Quá ít dòng | < 10 dòng không rỗng | Nhiều đoạn bị gộp |
| Mất dòng so với gốc | > 75% | So sánh với source |
| Thiếu dòng trống | blank_ratio < 20% | Thiếu phân đoạn |

Nếu fail → `build_retry_prompt()` tạo input có cảnh báo cụ thể → retry (tối đa `MAX_RETRIES`).

### Bước 7 — Write output

`atomic_write()`: ghi vào file `.tmp` → `os.replace()` → không bao giờ để file ở trạng thái không hoàn chỉnh khi bị kill giữa chừng.

### Bước 8 — Update data

Sau khi dịch thành công (nếu không phải `retranslate` với `skip_data_update`):

- `add_new_terms()` → Staging_Terms.md hoặc thẳng vào glossary file (tùy `IMMEDIATE_MERGE`)
- `add_skill_updates()` → Skills.json (evolution chain tracking)
- `update_from_response()` → Staging_Characters.json hoặc Characters_Active.json
- `validate_translation()` → ghi vi phạm Name Lock vào `data/name_fixes.json`

### Bước 9 — Final merge & retry pass

Sau khi xử lý tất cả chương:
- Retry pass (`RETRY_FAILED_PASSES` vòng) cho các chương thất bại
- `_final_merge()`: auto-merge glossary và characters nếu bật
- In summary: số chương thành công / thất bại / key stats

---

## 6. Data layer

### Glossary (`data/glossary/`)

5 file category + 1 staging:

```
Glossary_Pathways.md      — Hệ thống tu luyện, Sequence, cảnh giới
Glossary_Organizations.md — Tổ chức, hội phái, bang nhóm
Glossary_Items.md         — Vật phẩm, vũ khí, đan dược, artifact
Glossary_Locations.md     — Địa danh, thành phố, cõi giới, dungeon
Glossary_General.md       — Thuật ngữ chung, tên nhân vật
Staging_Terms.md          — Buffer chờ phân loại
```

Format mỗi dòng: `- English term: Bản dịch tiếng Việt`

Filter dùng **Aho-Corasick** (nếu cài `pyahocorasick`) hoặc regex. Cache automaton kèm mtime — tự invalidate khi file thay đổi.

`clean glossary` command gọi Gemini để phân loại staging terms vào đúng category, backup file cũ trước khi ghi.

### Characters (`data/characters/`)

Schema v3.0. Cấu trúc 3 tầng:

```
Characters_Active.json    — Nhân vật xuất hiện gần đây (full profile)
Characters_Archive.json   — Lâu không thấy (rotate sau ARCHIVE_AFTER_CHAPTERS)
Staging_Characters.json   — Mới từ AI, chờ merge
```

Mỗi profile gồm: `identity`, `power`, `canonical_name`, `alias_canonical_map`, `speech` (pronoun_self, formality, how_refers_to_others, quirks), `habitual_behaviors` (với confidence ≥ 0.65), `relationships` (với `pronoun_status`: weak/strong), `arc_status`, `emotional_state`.

**Emotion Tracker**: Scout cập nhật `emotional_state.current` (normal / angry / hurt / changed). Prompt hiển thị cảnh báo nổi bật khi state ≠ normal. Auto-reset về normal sau `EMOTION_RESET_CHAPTERS` chương không thấy.

### Skills (`data/skills/Skills.json`)

```json
{
  "skills": {
    "Fireball": {
      "vietnamese": "[Hỏa Cầu]",
      "owner": "Arthur",
      "skill_type": "active",
      "evolved_from": "",
      "evolution_chain": ["[Hỏa Cầu]"],
      "first_seen": "chapter_001.txt"
    }
  }
}
```

Filter: chỉ đưa vào prompt kỹ năng XUẤT HIỆN trong chương (regex scan cả EN lẫn VN name).

### Name Lock (`managers/name_lock.py`)

Tự động build từ:
1. `Characters_Active` + `Archive` → `canonical_name` + `alias_canonical_map`
2. `Glossary_Organizations` → tên tổ chức
3. `Glossary_Locations` → địa danh
4. `Glossary_General` → tên riêng khác

Quy tắc: tên giữ nguyên EN (canonical == tên gốc) → KHÔNG đưa vào bảng. Conflict → giữ bản lock đầu tiên, log cảnh báo.

`validate_translation()` quét bản dịch để phát hiện tên EN còn sót. Vi phạm được ghi vào `data/name_fixes.json` → lệnh `fix-names` sửa hàng loạt.

---

## 7. Scout AI & Memory

### Context Notes (ngắn hạn)

Scout xóa và tạo mới `Context_Notes.md` mỗi `SCOUT_REFRESH_EVERY` chương. 4 mục:

1. Mạch truyện đặc biệt (flashback, hồi ký, giấc mơ...)
2. Khoá xưng hô đang active (từng cặp nhân vật)
3. Diễn biến gần nhất (3–5 sự kiện quan trọng)
4. Cảnh báo cho AI dịch

### Arc Memory (dài hạn)

`Arc_Memory.md` chỉ APPEND, không bao giờ xóa. Mỗi entry gồm:
- Sự kiện lớn
- Thay đổi thế giới
- Danh tính active
- Xưng hô đã chốt

Cơ chế **chống trùng lặp**: extract data đã có → truyền vào prompt AI ("đã biết — KHÔNG ghi lại") → post-process loại dòng trùng (exact match + fuzzy 75%).

Khi load vào prompt: chỉ lấy `ARC_MEMORY_WINDOW` entry gần nhất.

---

## 8. Name Lock & Quality Guard

### Name Lock — Ràng buộc cứng

Đặt ở **PHẦN 8** (cuối cùng) của system prompt — vị trí có attention cao nhất. Format bảng ASCII rõ ràng. Prompt AI tự kiểm tra sau dịch.

Pipeline cũng tự validate sau khi nhận kết quả: dùng `re.search(rf"\b{re.escape(eng)}\b")` để tìm tên EN còn sót.

### Quality Guard — 4 tiêu chí

Vấn đề thường gặp khi Gemini trả về: gộp nhiều đoạn văn vào một dòng ("dính dòng"). Quality guard phát hiện và yêu cầu retry với cảnh báo cụ thể trong input.

---

## 9. Cấu trúc thư mục

```
littrans/
├── main.py                          # Entry point
├── .env                             # Cấu hình (từ .env.example)
├── pyproject.toml
├── requirements.txt
│
├── src/littrans/
│   ├── cli.py                       # Typer CLI — tất cả commands
│   ├── config/settings.py           # Singleton Settings (dataclass + dotenv)
│   │
│   ├── engine/
│   │   ├── pipeline.py              # Orchestrator chính
│   │   ├── scout.py                 # Scout AI (context notes, arc, emotion)
│   │   ├── prompt_builder.py        # Xây system prompt 8 sections
│   │   └── quality_guard.py         # Kiểm tra chất lượng bản dịch
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
│   └── utils/
│       ├── io_utils.py              # load_text, load_json, atomic_write
│       ├── data_versioning.py       # backup + restore + prune
│       └── logger.py                # get_logger, log_error, log_warning
│
├── prompts/
│   ├── system_agent.md              # Hướng dẫn dịch chính (XML structured)
│   └── character_profile.md         # Hướng dẫn lập profile nhân vật
│
├── inputs/                          # File gốc tiếng Anh (*.txt / *.md)
├── outputs/                         # Bản dịch (*_VN.txt)
├── data/
│   ├── glossary/                    # 5 Glossary_*.md + Staging_Terms.md
│   ├── characters/                  # Characters_Active/Archive/Staging.json
│   ├── skills/Skills.json
│   ├── memory/                      # Arc_Memory.md + Context_Notes.md
│   └── name_fixes.json              # Vi phạm Name Lock chờ sửa
├── logs/pipeline.log
└── Reports/                         # Báo cáo xuất từ clean characters --export
```

---

## 10. Đánh giá & điểm mạnh / hạn chế

### Điểm mạnh

**Nhất quán tên & xưng hô** — Name Lock table + relationship `pronoun_status` (weak/strong) + priority chain (4 tầng) đảm bảo xưng hô không dao động. Vi phạm được log và sửa hàng loạt bằng `fix-names`.

**Context thông minh** — Filter glossary/character/skills chỉ lấy nội dung liên quan đến chương hiện tại. Token Budget tự cắt context khi vượt ngưỡng theo thứ tự ưu tiên đã định sẵn.

**Bộ nhớ dài hạn** — Arc Memory append-only với chống trùng lặp. Context Notes ngắn hạn cung cấp thông tin tức thì (xưng hô đang active, cảnh báo mạch truyện).

**Độ bền** — Atomic write, multi-key pool với auto-rotate, retry với exponential backoff, retry pass cuối pipeline.

**Emotion Tracker** — Scout phân tích cảm xúc nhân vật sau mỗi batch chương. Prompt hiển thị cảnh báo khi nhân vật ở trạng thái đặc biệt (angry/hurt/changed).

**Tooling đầy đủ** — `clean glossary` (AI categorization), `clean characters` (review/merge/fix/export/validate), `fix-names` (batch fix Name Lock), `stats`.

### Hạn chế hiện tại

**Chỉ hỗ trợ Gemini** — Toàn bộ client layer (`client.py`) gắn cứng với `google-genai`. Không có abstraction cho OpenAI / Claude / local models.

**Không có chunking** — Chương rất dài (> 100K ký tự) không được chia nhỏ trước khi gửi. Có thể vượt context window của model.

**Scout chạy tuần tự** — Scout phải chờ trước khi dịch chương tiếp theo. Không có pipeline parallel giữa Scout và dịch.

**Glossary filter có thể bỏ sót** — Aho-Corasick match word boundary bằng `isalnum()` check — có thể bỏ sót các thuật ngữ kết hợp với dấu câu đặc biệt.

**Characters tiếng Trung** — Quy tắc Pinyin → Hán Việt trong `system_agent.md` nhưng không có bảng tra cứu tự động. AI phải tự chuyển đổi, có thể không nhất quán.

---

## Lệnh thường dùng

```bash
# Workflow cơ bản
python main.py translate

# Sau khi dịch xong
python main.py clean glossary
python main.py clean characters --action merge
python main.py fix-names

# Kiểm tra chất lượng data
python main.py clean characters --action validate
python main.py stats
python main.py fix-names --list

# Dịch lại một chương có vấn đề
python main.py retranslate 55 --update-data
```

---

*LiTTrans v4.1 — Powered by Google Gemini*