# LiTTrans v4.5 — Pipeline Dịch Truyện LitRPG / Tu Tiên

Dịch tự động truyện LitRPG / Tu Tiên từ tiếng Anh sang tiếng Việt bằng **Gemini AI** hoặc **Claude (Anthropic)**.  
Giữ nhất quán tên nhân vật, xưng hô, thuật ngữ và kỹ năng xuyên suốt hàng trăm chương.

Có hai cách dùng: **Web UI** (giao diện trình duyệt, dễ dùng hơn) và **CLI** (dòng lệnh).

---

## Mục lục

1. [Trước khi bắt đầu](#1-trước-khi-bắt-đầu)
2. [Lấy API Key](#2-lấy-api-key)
3. [Cài đặt — Cách 1: Chạy trực tiếp](#3-cài-đặt--cách-1-chạy-trực-tiếp-trên-máy)
4. [Cài đặt — Cách 2: Docker](#4-cài-đặt--cách-2-docker-khuyến-nghị-cho-người-mới)
5. [Cấu hình .env](#5-cấu-hình-env)
6. [Sử dụng Web UI](#6-sử-dụng-web-ui)
7. [Sử dụng CLI](#7-sử-dụng-cli)
8. [Tính năng nổi bật v4.5](#8-tính-năng-nổi-bật-v45)
9. [Cấu trúc thư mục](#9-cấu-trúc-thư-mục)
10. [Pipeline hoạt động như thế nào](#10-pipeline-hoạt-động-như-thế-nào)
11. [Xử lý sự cố thường gặp](#11-xử-lý-sự-cố-thường-gặp)
12. [Tất cả tùy chọn cấu hình](#12-tất-cả-tùy-chọn-cấu-hình)

---

## 1. Trước khi bắt đầu

### Bạn cần cài gì?

**Cách 1 — Chạy trực tiếp:** Cần Python 3.11 trở lên.

**Cách 2 — Docker:** Cần Docker Desktop. Không cần cài Python.

> **Nếu bạn không chắc nên chọn cách nào:** Hãy dùng Docker. Bạn chỉ cần cài một thứ duy nhất, không lo xung đột phiên bản, và các lệnh đều ngắn gọn.

### Kiểm tra đã có Python chưa (Cách 1)

```bash
python --version
```

Nếu thấy `Python 3.11.x` hoặc cao hơn → OK.  
Nếu thấy `Python 3.9` hoặc báo lỗi → Tải Python tại [python.org](https://www.python.org/downloads/).

### Kiểm tra đã có Docker chưa (Cách 2)

```bash
docker --version
```

Nếu báo lỗi → Tải Docker Desktop tại [docker.com](https://www.docker.com/products/docker-desktop/).  
Sau khi cài xong, khởi động Docker Desktop trước khi làm bước tiếp theo.

---

## 2. Lấy API Key

### Gemini API Key (bắt buộc)

Pipeline dùng Gemini cho Scout AI, Pre-call, và Post-call. Bạn cần ít nhất một Gemini API key.

**Bước 1:** Truy cập [aistudio.google.com](https://aistudio.google.com)

**Bước 2:** Đăng nhập bằng tài khoản Google

**Bước 3:** Click **"Get API key"** → **"Create API key"**

**Bước 4:** Copy key vừa tạo (dạng `AIzaSy...`) — giữ key này bí mật

> **Giới hạn miễn phí:** Gemini Flash cho phép khoảng 1.000 request/ngày miễn phí. Nếu dịch số lượng lớn, bạn có thể thêm key dự phòng hoặc nâng cấp tài khoản.

### Anthropic API Key (tùy chọn — cho Dual-Model)

Nếu muốn dùng **Claude** (Anthropic) làm model dịch thuật chính:

**Bước 1:** Truy cập [console.anthropic.com](https://console.anthropic.com)

**Bước 2:** Đăng nhập / đăng ký tài khoản

**Bước 3:** Vào **API Keys** → **Create Key**

**Bước 4:** Copy key (dạng `sk-ant-...`) và thêm vào `.env`

> Anthropic key chỉ cần khi đặt `TRANSLATION_PROVIDER=anthropic`. Nếu dùng Gemini hoàn toàn thì không cần.

---

## 3. Cài đặt — Cách 1: Chạy trực tiếp trên máy

### Bước 1: Tải source code

```bash
git clone <repo-url>
cd littrans
```

Hoặc tải file ZIP từ GitHub → giải nén → mở Terminal trong thư mục vừa giải nén.

### Bước 2: Tạo môi trường ảo (khuyến nghị)

```bash
# macOS / Linux
python -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\activate
```

Bạn biết đang trong môi trường ảo khi thấy `(.venv)` xuất hiện ở đầu dòng lệnh.

### Bước 3: Cài thư viện

```bash
# Cài đặt cơ bản (Gemini)
pip install -e .

# Cài thêm pyahocorasick để filter glossary nhanh hơn ~10 lần (khuyến nghị)
pip install ".[fast]"

# Cài thêm nếu muốn dùng Claude (Anthropic)
pip install anthropic

# Cài thêm nếu muốn dùng Web UI
pip install streamlit pandas
```

### Bước 4: Tạo file cấu hình

```bash
cp .env.example .env
```

Mở file `.env` bằng bất kỳ text editor nào và điền API key:

```env
GEMINI_API_KEY=AIzaSy...   ← dán key Gemini của bạn vào đây
```

Nếu dùng Claude thêm:

```env
TRANSLATION_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

### Bước 5: Chạy thử

```bash
# Web UI
python run_ui.py

# Hoặc CLI
python main.py --help
```

---

## 4. Cài đặt — Cách 2: Docker (khuyến nghị cho người mới)

Docker đóng gói toàn bộ môi trường vào một "hộp" — bạn không cần cài Python, không lo xung đột phiên bản.

### Bước 1: Tải source code

```bash
git clone <repo-url>
cd littrans
```

### Bước 2: Khởi tạo thư mục và file cấu hình

```bash
# macOS / Linux
make init

# Windows (nếu chưa có make, chạy thủ công)
mkdir inputs outputs logs
mkdir data\glossary data\characters data\skills data\memory
copy .env.example .env
```

### Bước 3: Điền API key vào .env

Mở file `.env` và sửa dòng đầu tiên:

```env
GEMINI_API_KEY=AIzaSy...   ← dán key của bạn vào đây
```

### Bước 4: Build image Docker

```bash
make build

# Nếu không có make:
docker compose build
```

Lần đầu mất **3–5 phút** do cần tải và compile thư viện. Các lần sau nhanh hơn nhiều.

### Bước 5: Chạy Web UI

```bash
make ui

# Nếu không có make:
docker compose up ui
```

Mở trình duyệt: **http://localhost:8501**

---

## 5. Cấu hình .env

File `.env` chứa toàn bộ cấu hình. Những thứ quan trọng nhất:

```env
# ── BẮT BUỘC ──────────────────────────────────────────────────────
GEMINI_API_KEY=AIzaSy...          # API key Gemini — luôn cần (Scout/Pre/Post)

# ── KEY DỰ PHÒNG (tùy chọn, khuyến nghị nếu dịch nhiều) ──────────
FALLBACK_KEY_1=AIzaSy...
FALLBACK_KEY_2=AIzaSy...

# ── CHỌN MODEL DỊCH THUẬT (Dual-Model v4.5) ──────────────────────
# Mặc định: dùng Gemini cho tất cả (không cần thay đổi)
TRANSLATION_PROVIDER=gemini
TRANSLATION_MODEL=                # để trống = dùng mặc định theo provider

# Nếu muốn dùng Claude làm model dịch:
# TRANSLATION_PROVIDER=anthropic
# TRANSLATION_MODEL=claude-sonnet-4-6
# ANTHROPIC_API_KEY=sk-ant-...

# ── GEMINI MODEL (Scout/Pre/Post + fallback Trans) ────────────────
GEMINI_MODEL=gemini-2.5-flash     # nhanh, rẻ, chất lượng tốt (khuyến nghị)
# GEMINI_MODEL=gemini-2.5-pro     # chậm hơn, đắt hơn, chất lượng cao nhất

# ── TỐC ĐỘ (điều chỉnh nếu bị rate limit) ────────────────────────
SUCCESS_SLEEP=30        # Nghỉ 30 giây giữa các chương
RATE_LIMIT_SLEEP=60     # Nghỉ 60 giây khi bị giới hạn tốc độ
```

> **Web UI:** Bạn có thể chỉnh tất cả cấu hình này trong tab **⚙️ Cài đặt** mà không cần sửa file `.env` thủ công.

---

## 6. Sử dụng Web UI

### Khởi động

```bash
# Cách 1: Chạy trực tiếp
python run_ui.py

# Cách 2: Docker
make ui
```

Mở trình duyệt: **http://localhost:8501**

---

### Lần đầu sử dụng — làm theo 4 bước này

#### Bước 1 — Kiểm tra API key

Mở tab **⚙️ Cài đặt** → mục **🔑 API** → xác nhận đã có `GEMINI_API_KEY`.  
Nếu chưa có → điền vào ô rồi nhấn **💾 Lưu .env**.

#### Bước 2 — Upload file chương

Mở tab **📄 Dịch** → kéo thả file `.txt` hoặc `.md` vào ô **Upload file chương**.

**Quy tắc đặt tên file:**
- Mỗi file = một chương
- Đặt tên có số thứ tự để pipeline sắp xếp đúng
- Ví dụ: `chapter_001.txt`, `chapter_002.txt`, ...

#### Bước 3 — Chạy pipeline

Nhấn nút **▶ Chạy pipeline**. Log hiện theo thời gian thực:

```
▶  [1] Dịch: chapter_001.txt
  🔭 Scout AI (khởi động)...
  📖 Glossary Suggest: +5 thuật ngữ → Staging
  🔍 Pre-call...
  ✅ Chapter map: 12 tên · 3 skill · 8 pronoun pair
  ⚙️  Trans-call 1/5 | gemini-2.5-flash (gemini)
  🔎 Post-call 1/3...
  ✅ Dịch xong: chapter_001.txt
```

#### Bước 4 — Xem kết quả

Mở tab **🔍 Xem chương** → click tên chương → chọn tab:

- **🔀 Song song**: EN bên trái, VN bên phải, cuộn đồng bộ
- **🇻🇳 Bản dịch**: xem toàn văn + nút tải xuống
- **⚡ Diff**: highlight đoạn mới/thay đổi

---

### Các tab trong Web UI

| Tab | Chức năng |
|---|---|
| **📄 Dịch** | Upload file, xem trạng thái, chạy pipeline, xem log real-time |
| **🔍 Xem chương** | Đọc song song EN/VN, tải xuống, dịch lại chương cụ thể |
| **👤 Nhân vật** | Xem profile, xưng hô strong/weak, EPS, emotion state |
| **📚 Từ điển** | Xem/tìm kiếm glossary, xác nhận thuật ngữ Scout đề xuất |
| **📊 Thống kê** | Tiến độ dịch, biểu đồ, số thuật ngữ, nhân vật |
| **⚙️ Cài đặt** | Toàn bộ cấu hình pipeline, Dual-Model, lưu vào .env |

---

### Dịch lại một chương

1. Mở tab **🔍 Xem chương** → click chương cần dịch lại
2. Cuộn xuống dưới → nhấn **↺ Dịch lại…**
3. Chọn tùy chọn:
   - **Cập nhật data** — cập nhật Glossary/Characters/Skills sau khi dịch lại
   - **Chạy Scout AI trước** — phân tích lại context trước khi dịch
4. Nhấn **⚡ Xác nhận dịch lại**

> ⚠️ Bản dịch cũ sẽ bị **ghi đè**.

---

## 7. Sử dụng CLI

### Cách chạy

```bash
# Chạy trực tiếp (đã activate venv)
python main.py <lệnh>

# Chạy qua Docker
docker compose run --rm cli python main.py <lệnh>

# Chạy qua make (shortcut)
make <lệnh>
```

---

### Workflow cơ bản

```bash
# 1. Dịch tất cả chương chưa dịch
python main.py translate

# 2. Xác nhận thuật ngữ Scout đề xuất
python main.py clean glossary

# 3. Merge nhân vật mới
python main.py clean characters --action merge

# 4. Kiểm tra và sửa lỗi tên (nếu có)
python main.py fix-names
```

---

### Tất cả lệnh CLI

#### `translate` — Dịch hàng loạt

```bash
python main.py translate

# Dùng Claude làm model dịch
python main.py translate --provider anthropic --model claude-sonnet-4-6

# Override model Gemini
python main.py translate --provider gemini --model gemini-2.5-pro
```

Dịch tất cả chương trong `inputs/` chưa có bản dịch. Pipeline tự động bỏ qua chương đã dịch, chạy Scout AI theo chu kỳ, và retry khi gặp lỗi.

---

#### `retranslate` — Dịch lại một chương

```bash
# Xem danh sách chương
python main.py retranslate --list

# Chọn theo số thứ tự
python main.py retranslate 5

# Chọn theo tên file (gõ một phần cũng được)
python main.py retranslate "chapter_005"

# Dịch lại và cập nhật data
python main.py retranslate 5 --update-data

# Dịch lại bằng Claude
python main.py retranslate 5 --provider anthropic --model claude-opus-4-6
```

---

#### `clean glossary` — Xác nhận thuật ngữ mới

```bash
python main.py clean glossary
```

Đọc thuật ngữ Scout đề xuất trong Staging → dùng AI phân loại vào đúng nhóm → ghi vào file Glossary tương ứng.

---

#### `clean characters` — Quản lý nhân vật

```bash
python main.py clean characters --action review    # Xem toàn bộ profile đang active
python main.py clean characters --action merge     # Merge Staging → Active
python main.py clean characters --action fix       # Tự động sửa lỗi nhỏ
python main.py clean characters --action validate  # Kiểm tra schema
python main.py clean characters --action export    # Xuất báo cáo Markdown ra Reports/
python main.py clean characters --action archive   # Xem nhân vật đã archive
```

---

#### `fix-names` — Sửa lỗi tên vi phạm Name Lock

```bash
python main.py fix-names --list         # Xem danh sách vi phạm
python main.py fix-names --dry-run      # Xem trước, không ghi file
python main.py fix-names                # Sửa thật
python main.py fix-names --all-chapters # Sửa toàn bộ tất cả chương
python main.py fix-names --clear        # Xóa name_fixes.json
```

---

#### `stats` — Thống kê nhanh

```bash
python main.py stats
```

---

### Shortcut với make (Docker)

```bash
make translate                    # dịch tất cả
make CHAPTER=5 retranslate        # dịch lại chương 5
make stats                        # thống kê
make clean-glossary               # xác nhận thuật ngữ
make merge-chars                  # merge nhân vật
make fix-names                    # sửa lỗi tên
make validate-chars               # kiểm tra schema
make export-chars                 # xuất báo cáo
make shell                        # mở shell debug
```

---

## 8. Tính năng nổi bật v4.5

### Dual-Model — Dùng Claude làm model dịch

v4.5 hỗ trợ dùng **Claude (Anthropic)** làm model dịch thuật chính, trong khi Gemini vẫn đảm nhiệm Scout AI, Pre-call và Post-call.

**Cấu hình trong `.env`:**

```env
TRANSLATION_PROVIDER=anthropic
TRANSLATION_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...
```

**Override nhanh qua CLI:**

```bash
python main.py translate --provider anthropic --model claude-opus-4-6
python main.py translate --provider gemini   --model gemini-2.5-pro
```

**Model được hỗ trợ:**

| Provider | Model | Ghi chú |
|---|---|---|
| `gemini` | `gemini-2.5-flash` | Nhanh, rẻ (khuyến nghị mặc định) |
| `gemini` | `gemini-2.5-pro` | Chất lượng cao nhất, chậm hơn |
| `anthropic` | `claude-sonnet-4-6` | Cân bằng chất lượng/tốc độ |
| `anthropic` | `claude-opus-4-6` | Chất lượng cao nhất của Claude |
| `anthropic` | `claude-haiku-4-5-20251001` | Nhanh nhất, tiết kiệm nhất |

---

### EPS — Emotional Proximity Signal

EPS theo dõi mức độ thân mật giữa các cặp nhân vật (1–5) để điều chỉnh văn phong xưng hô một cách tự nhiên:

| Mức | Nhãn | Ý nghĩa |
|---|---|---|
| 1 | FORMAL | Lạnh lùng, trang trọng — giữ kính ngữ, câu đầy đủ |
| 2 | NEUTRAL | Mặc định — xưng hô theo dynamic đã chốt |
| 3 | FRIENDLY | Thân thiện — câu ngắn hơn, có thể bỏ kính ngữ |
| 4 | CLOSE | Rất thân — nickname ok, chia sẻ cảm xúc trực tiếp |
| 5 | INTIMATE | Ngôn ngữ riêng tư, thân mật tuyệt đối |

EPS tự động cập nhật khi Post-call phát hiện thay đổi mức độ thân mật và được inject vào Trans-call prompt để điều chỉnh văn phong dịch.

---

### Post-processor — 14-pass Code Cleanup

Sau mỗi Trans-call, bản dịch được tự động làm sạch qua 14 pass thuần code (không dùng AI):

| Pass | Xử lý |
|---|---|
| 1–2 | Chuẩn hóa line endings, trailing whitespace |
| 3 | Xóa code block wrapper bọc toàn bản dịch |
| 4 | Xóa lời mở đầu/kết thúc của AI |
| 5–6 | Chuẩn hóa dấu ba chấm (`...` → `…`), em dash (`--` → `—`) |
| 7 | Typographic quotes (`"..."` → `"..."`) |
| 8 | Khoảng trắng thừa trước dấu chấm câu |
| 9 | Dòng trống thừa trong system box |
| 10–11 | Tách lượt thoại bị dính dòng, thêm dòng trống trước thoại |
| 12 | Sửa `[Kỹ năng` thiếu dấu đóng `]` |
| 13–14 | Chuẩn hóa 3+ dòng trống → 1, final trim |

---

### Scout Glossary Suggest

Scout AI tự động phát hiện thuật ngữ chuyên biệt chưa có trong Glossary và đề xuất vào Staging.

**Thuật ngữ được đề xuất theo thứ tự ưu tiên:**
1. Tên kỹ năng, chiêu thức, phép thuật
2. Danh hiệu, cảnh giới tu luyện, tước vị
3. Tên tổ chức, hội phái, môn phái
4. Địa danh, cõi giới, dungeon
5. Vật phẩm đặc biệt, vũ khí, đan dược
6. Thuật ngữ hệ thống: pathway, sequence, ability class

**Cấu hình:**

```env
SCOUT_SUGGEST_GLOSSARY=true
SCOUT_SUGGEST_MIN_CONFIDENCE=0.7    # Tăng lên 0.85 nếu muốn ít nhưng chắc hơn
SCOUT_SUGGEST_MAX_TERMS=20          # Số thuật ngữ tối đa mỗi lần Scout
```

**Xác nhận thuật ngữ:**
- **Web UI:** Tab **📚 Từ điển** → banner vàng khi có thuật ngữ chờ → nhấn **🔄 Clean glossary**
- **CLI:** `python main.py clean glossary`

---

### Scene Plan trong Pre-call

Pre-call phân tích chương và sinh Scene Plan — bản tóm tắt cấu trúc cảnh (POV, beats, tông giọng). Scene Plan được inject vào Trans-call để AI dịch hiểu mạch truyện trước khi bắt đầu.

---

## 9. Cấu trúc thư mục

```
littrans/
│
├── main.py              # Entry point CLI
├── run_ui.py            # Entry point Web UI
├── .env                 # Cấu hình của bạn (tạo từ .env.example)
├── .env.example         # Template cấu hình
│
├── Dockerfile           # Docker: multi-stage build
├── docker-compose.yml   # Docker: services ui + cli
├── docker-entrypoint.sh # Docker: script khởi tạo
├── Makefile             # Shortcut commands
│
├── src/littrans/
│   ├── engine/
│   │   ├── pipeline.py        # Pipeline orchestrator chính
│   │   ├── scout.py           # Scout AI (context, arc, emotion, glossary suggest)
│   │   ├── pre_processor.py   # Pre-call: sinh Chapter Map
│   │   ├── post_analyzer.py   # Post-call: review + extract metadata
│   │   ├── prompt_builder.py  # Xây dựng system prompt
│   │   └── quality_guard.py   # Kiểm tra chất lượng cơ học (7 tiêu chí)
│   ├── managers/
│   │   ├── glossary.py        # Glossary phân category + Aho-Corasick filter
│   │   ├── characters.py      # Tiered Characters + EPS + Emotion Tracker
│   │   ├── skills.py          # Skills.json + evolution chain
│   │   ├── name_lock.py       # Bảng Name Lock: chốt tên nhất quán
│   │   └── memory.py          # Arc Memory + Context Notes
│   ├── llm/
│   │   ├── client.py          # Gemini + Anthropic API client, Key Pool
│   │   ├── schemas.py         # Pydantic schemas (EPS, RelationshipDetail, ...)
│   │   └── token_budget.py    # Smart context truncation
│   ├── tools/
│   │   ├── clean_glossary.py  # Phân loại thuật ngữ Staging → Glossary
│   │   ├── clean_characters.py# Quản lý Character Profile
│   │   └── fix_names.py       # Sửa lỗi Name Lock trong bản dịch
│   ├── utils/
│   │   ├── io_utils.py        # Atomic write, load/save JSON
│   │   ├── text_normalizer.py # Chuẩn hóa raw EN text trước khi dịch
│   │   ├── post_processor.py  # 14-pass code cleanup sau Trans-call
│   │   └── data_versioning.py # Backup & versioning data files
│   ├── ui/
│   │   ├── app.py             # Streamlit Web UI
│   │   └── runner.py          # Background pipeline runner
│   └── config/
│       └── settings.py        # Đọc toàn bộ cấu hình từ .env
│
├── prompts/
│   ├── system_agent.md        # Hướng dẫn dịch chính
│   └── character_profile.md   # Hướng dẫn lập profile nhân vật
│
├── inputs/              # ← Đặt file chương gốc vào đây (.txt / .md)
├── outputs/             # Bản dịch (*_VN.txt) — tự sinh
│
└── data/
    ├── glossary/
    │   ├── Glossary_Pathways.md       # Hệ thống tu luyện, cảnh giới
    │   ├── Glossary_Organizations.md  # Tổ chức, hội phái
    │   ├── Glossary_Items.md          # Vật phẩm, vũ khí
    │   ├── Glossary_Locations.md      # Địa danh, cõi giới
    │   ├── Glossary_General.md        # Thuật ngữ chung, kỹ năng
    │   └── Staging_Terms.md           # Thuật ngữ chờ xác nhận
    ├── characters/
    │   ├── Characters_Active.json     # Nhân vật xuất hiện gần đây
    │   ├── Characters_Archive.json    # Nhân vật lâu không thấy
    │   └── Staging_Characters.json    # Nhân vật mới, chờ merge
    ├── skills/
    │   └── Skills.json                # Kỹ năng đã biết + evolution chain
    └── memory/
        ├── Context_Notes.md           # Ghi chú ngắn hạn từ Scout
        └── Arc_Memory.md              # Bộ nhớ arc dài hạn (chỉ append)
```

---

## 10. Pipeline hoạt động như thế nào

Với mỗi chương, pipeline chạy theo trình tự:

### Scout AI (mỗi N chương, mặc định 5)

Chạy trước khi dịch, Scout đọc các chương gần nhất và làm 4 việc:

1. **Context Notes** — Ghi chú mạch truyện, flashback, xưng hô đang active, cảnh báo cho AI dịch
2. **Arc Memory** — Tóm tắt sự kiện quan trọng, append vào bộ nhớ dài hạn (không bao giờ xóa)
3. **Emotion Tracker** — Cập nhật trạng thái cảm xúc từng nhân vật (normal / angry / hurt / changed)
4. **Glossary Suggest** — Phát hiện thuật ngữ mới, đề xuất vào Staging

### Pre-call

Phân tích chương sắp dịch, sinh **Chapter Map**:
- Tên / địa danh / kỹ năng xuất hiện + bản dịch đã lock
- Pronoun pair đang active cho từng cặp nhân vật
- Alias và scene bất thường (flashback, nhân vật đổi danh tính)
- Scene Plan: cấu trúc cảnh, POV, tông giọng

### Translation call

Dịch nội dung chính. System prompt gồm 9 phần:
- Hướng dẫn dịch + Glossary + Skills đã biết
- Character profiles + EPS summary
- Chapter Map (từ Pre-call)
- Arc Memory + Context Notes
- Name Lock Table (ưu tiên tuyệt đối)

Ngay sau khi nhận bản dịch: **Post-processor** chạy 14 pass làm sạch code-only (không tốn API call).

### Quality Guard (kiểm tra cơ học, 7 tiêu chí)

1. Dòng vượt 1000 ký tự (dính dòng nghiêm trọng)
2. Tổng dòng không rỗng < 10 (quá ít dòng)
3. Mất > 50% dòng so với bản gốc
4. Tỉ lệ dòng trống < 20%
5. Bản dịch < 45% độ dài bản gốc
6. > 15% dòng vẫn là tiếng Anh
7. Dòng trống thừa trong system box

Tự động retry nếu phát hiện vấn đề.

### Post-call

Review chất lượng dịch thuật và extract metadata:
- **retry_required**: tên sai, pronoun sai, đoạn mất → yêu cầu retry Trans-call
- **warn**: văn phong chưa hay, lỗi nhẹ → log, không retry
- Extract: thuật ngữ mới, nhân vật mới (profile đầy đủ), quan hệ thay đổi, kỹ năng mới, EPS updates

### Name Lock validate

Quét bản dịch tìm tên tiếng Anh còn sót. Ghi vi phạm vào `data/name_fixes.json` để sửa sau bằng `fix-names`.

---

## 11. Xử lý sự cố thường gặp

### Lỗi "Thiếu GEMINI_API_KEY"

```
❌ Thiếu GEMINI_API_KEY trong .env
```

Kiểm tra file `.env` có dòng:
```env
GEMINI_API_KEY=AIzaSy...
```
Không để dấu cách trước/sau dấu `=`. Không bọc trong dấu ngoặc kép.

---

### Lỗi "ANTHROPIC_API_KEY chưa set"

```
❌ TRANSLATION_PROVIDER=anthropic nhưng thiếu ANTHROPIC_API_KEY trong .env
```

Thêm vào `.env`:
```env
ANTHROPIC_API_KEY=sk-ant-...
```

---

### Bị rate limit (lỗi 429)

```
❌ Lỗi 1/5: 429 Resource exhausted
⚠️  Rate limit → chờ 60s...
```

Pipeline tự xử lý và chờ. Nếu vẫn bị liên tục:
- Thêm key dự phòng: `FALLBACK_KEY_1=AIzaSy...`
- Tăng thời gian nghỉ: `SUCCESS_SLEEP=60`
- Đổi sang model flash: `GEMINI_MODEL=gemini-2.5-flash`

---

### Bản dịch bị lỗi chất lượng

```
⚠️  Lỗi cơ học (1/5): DÍNH DÒNG NGHIÊM TRỌNG
```

Pipeline tự retry. Nếu vẫn lỗi sau nhiều lần, dịch lại chương đó:

```bash
python main.py retranslate <số thứ tự hoặc tên file>
```

---

### Tên nhân vật bị sai trong bản dịch

```
🔒 Name Lock — 2 vi phạm
```

```bash
python main.py fix-names --list    # xem danh sách
python main.py fix-names           # sửa tự động
```

---

### Model không hợp lệ

```
⚠️  TRANSLATION_MODEL='...' chưa có trong danh sách đã biết
```

Đây chỉ là cảnh báo — pipeline vẫn chạy. Nếu API báo lỗi thì tên model thực sự sai.  
Kiểm tra lại tên model tại tài liệu của Gemini hoặc Anthropic.

---

### Docker: lỗi permission trên Linux/macOS

```bash
chmod +x docker-entrypoint.sh
```

---

### Docker: port 8501 đã bị dùng

Sửa trong `docker-compose.yml`:
```yaml
ports:
  - "8502:8501"   # đổi port bên trái
```

---

### Windows: lỗi encoding

```bash
set PYTHONUTF8=1
python main.py translate
```

---

## 12. Tất cả tùy chọn cấu hình

### API

| Biến | Mặc định | Mô tả |
|---|---|---|
| `GEMINI_API_KEY` | *(bắt buộc)* | API key Gemini chính |
| `FALLBACK_KEY_1` | *(trống)* | Key dự phòng 1 |
| `FALLBACK_KEY_2` | *(trống)* | Key dự phòng 2 |
| `KEY_ROTATE_THRESHOLD` | `3` | Số lỗi liên tiếp trước khi chuyển key |
| `GEMINI_MODEL` | `gemini-2.0-flash-exp` | Model Gemini cho Scout/Pre/Post |
| `TRANSLATION_PROVIDER` | `gemini` | Provider dịch thuật: `gemini` hoặc `anthropic` |
| `TRANSLATION_MODEL` | *(tự chọn theo provider)* | Model dịch thuật cụ thể |
| `ANTHROPIC_API_KEY` | *(trống)* | API key Anthropic (bắt buộc khi dùng anthropic) |

### Pipeline

| Biến | Mặc định | Mô tả |
|---|---|---|
| `USE_THREE_CALL` | `true` | `true` = Pre+Trans+Post. `false` = 1-call legacy |
| `MAX_RETRIES` | `5` | Số lần retry khi gặp lỗi |
| `SUCCESS_SLEEP` | `30` | Nghỉ (giây) sau mỗi chương thành công |
| `RATE_LIMIT_SLEEP` | `60` | Nghỉ (giây) khi bị rate limit |
| `MIN_CHARS_PER_CHAPTER` | `500` | Cảnh báo nếu chương ngắn hơn |
| `PRE_CALL_SLEEP` | `5` | Nghỉ (giây) giữa Pre-call và Trans-call |
| `POST_CALL_SLEEP` | `5` | Nghỉ (giây) giữa Trans-call và Post-call |
| `POST_CALL_MAX_RETRIES` | `2` | Số lần retry Trans-call khi Post báo lỗi |
| `TRANS_RETRY_ON_QUALITY` | `true` | Có retry Trans-call khi Post báo lỗi không |

### Scout AI

| Biến | Mặc định | Mô tả |
|---|---|---|
| `SCOUT_REFRESH_EVERY` | `5` | Chạy Scout mỗi N chương |
| `SCOUT_LOOKBACK` | `10` | Đọc N chương gần nhất |
| `ARC_MEMORY_WINDOW` | `3` | Số arc entry đưa vào prompt |

### Scout Glossary Suggest

| Biến | Mặc định | Mô tả |
|---|---|---|
| `SCOUT_SUGGEST_GLOSSARY` | `true` | Bật/tắt tính năng |
| `SCOUT_SUGGEST_MIN_CONFIDENCE` | `0.7` | Ngưỡng confidence tối thiểu (0.0–1.0) |
| `SCOUT_SUGGEST_MAX_TERMS` | `20` | Số thuật ngữ tối đa mỗi lần Scout |

### Nhân vật

| Biến | Mặc định | Mô tả |
|---|---|---|
| `ARCHIVE_AFTER_CHAPTERS` | `60` | Chuyển nhân vật sang Archive sau N chương vắng mặt |
| `EMOTION_RESET_CHAPTERS` | `5` | Reset emotional state về normal sau N chương |

### Merge & Retry

| Biến | Mặc định | Mô tả |
|---|---|---|
| `IMMEDIATE_MERGE` | `true` | Merge Staging → Active ngay sau mỗi chương |
| `AUTO_MERGE_GLOSSARY` | `false` | Tự động clean glossary cuối pipeline |
| `AUTO_MERGE_CHARACTERS` | `false` | Tự động merge characters cuối pipeline |
| `RETRY_FAILED_PASSES` | `3` | Số vòng retry các chương thất bại cuối pipeline |

### Token Budget

| Biến | Mặc định | Mô tả |
|---|---|---|
| `BUDGET_LIMIT` | `150000` | Giới hạn token cho context (0 = tắt) |

Khi vượt giới hạn, pipeline tự cắt context theo thứ tự ưu tiên:
1. ✅ Name Lock Table + Instructions — **không bao giờ cắt**
2. 🔵 Arc Memory → giữ 1 entry gần nhất
3. 🟡 Staging glossary
4. 🟡 Character profiles phụ → giữ top 5 liên quan nhất
5. 🔴 Toàn bộ Arc Memory (last resort)

### Đường dẫn

| Biến | Mặc định | Mô tả |
|---|---|---|
| `INPUT_DIR` | `inputs` | File chương gốc |
| `OUTPUT_DIR` | `outputs` | Bản dịch |
| `DATA_DIR` | `data` | Glossary, Characters, Skills, Memory |
| `PROMPTS_DIR` | `prompts` | System prompts |
| `LOG_DIR` | `logs` | Log file |

---

## Lệnh tham khảo nhanh

```bash
# ── Lần đầu setup ─────────────────────────────────────────────────
make init                         # tạo thư mục + .env (Docker)
make build                        # build Docker image

# ── Chạy hàng ngày ────────────────────────────────────────────────
make ui                           # khởi động Web UI
make translate                    # dịch tất cả chương
make stats                        # xem thống kê

# ── Sau khi dịch ──────────────────────────────────────────────────
make clean-glossary               # xác nhận thuật ngữ Scout đề xuất
make merge-chars                  # merge nhân vật mới
make fix-names                    # sửa lỗi tên

# ── Xử lý sự cố ───────────────────────────────────────────────────
make CHAPTER=5 retranslate        # dịch lại chương 5
make validate-chars               # kiểm tra schema nhân vật
make export-chars                 # xuất báo cáo nhân vật

# ── Debug ──────────────────────────────────────────────────────────
make shell                        # mở shell trong container
make logs                         # xem log Web UI real-time
```

---

*LiTTrans v4.5 — Powered by Google Gemini & Anthropic Claude*