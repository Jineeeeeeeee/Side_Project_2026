# Pipeline Dịch Truyện v3.1

**Tuần tự · Name Lock · Tiered Characters · Pronoun Priority · Skills Tracking · Quality Guard**

---

## Mục lục

- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [Cài đặt](#cài-đặt)
- [Cấu hình .env](#cấu-hình-env)
- [Sử dụng](#sử-dụng)
- [Tính năng](#tính-năng)
- [Pipeline Flow](#pipeline-flow)
- [System Prompt (8 phần)](#system-prompt-8-phần)
- [Kiểm tra chất lượng bản dịch](#kiểm-tra-chất-lượng-bản-dịch)
- [Quy tắc dịch tên](#quy-tắc-dịch-tên)
- [Xưng hô & Quan hệ](#xưng-hô--quan-hệ)

---

## Cấu trúc dự án

```
.
├── translate.py                         ← Dịch toàn bộ chương chưa dịch
├── retranslate.py                       ← Dịch lại một chương cụ thể
├── clean_glossary.py                    ← Phân loại & merge thuật ngữ vào Glossary
├── clean_characters.py                  ← Quản lý Character Profile
├── translateAGENT_INSTRUCTIONS.md       ← Hướng dẫn dịch (đưa vào prompt)
├── CHARACTER_PROFILING_INSTRUCTIONS.md  ← Hướng dẫn lập profile nhân vật
├── .env                                 ← Cấu hình API key và tham số
│
├── core/                                ← Logic pipeline
│   ├── config.py        — Đọc .env, hằng số, đường dẫn
│   ├── models.py        — Pydantic schemas (TermDetail, CharacterDetail, SkillUpdate...)
│   ├── glossary.py      — Multi-category glossary + Aho-Corasick filter
│   ├── characters.py    — Tiered Active/Archive + Identity Tracking + Pronoun Priority
│   ├── skills.py        — Quản lý Skills.json (kỹ năng + tiến hóa)
│   ├── name_lock.py     — Bảng tên đã chốt, validate vi phạm
│   ├── arc_memory.py    — Bộ nhớ arc dài hạn (append-only)
│   ├── scout.py         — Scout AI: Context_Notes + Arc_Memory
│   ├── prompt.py        — Build system prompt 8 phần
│   ├── runner.py        — Pipeline điều phối tuần tự + Quality Guard
│   ├── ai_client.py     — Gọi Gemini API + parse response
│   └── io_utils.py      — Đọc/ghi file (atomic write)
│
├── Raw_English/                         ← Input: file chương gốc (.txt / .md)
├── Translated_VN/                       ← Output: file đã dịch tiếng Việt
│
└── data/                                ← Data tự động tạo & cập nhật
    ├── glossary/
    │   ├── Glossary_Pathways.md         ← Hệ thống tu luyện, Sequence, Path
    │   ├── Glossary_Organizations.md    ← Tổ chức, hội phái, môn phái
    │   ├── Glossary_Items.md            ← Vật phẩm, linh khí, bảo vật
    │   ├── Glossary_Locations.md        ← Địa danh, thành phố, địa điểm
    │   ├── Glossary_General.md          ← Tên riêng, thuật ngữ chung
    │   └── Staging_Terms.md             ← Thuật ngữ mới, chờ phân loại
    ├── characters/
    │   ├── Characters_Active.json       ← Nhân vật đang hoạt động
    │   ├── Characters_Archive.json      ← Nhân vật ít xuất hiện (archive)
    │   └── Staging_Characters.json      ← Nhân vật mới, chờ merge
    ├── skills/
    │   └── Skills.json                  ← Kỹ năng đã biết + evolution chain
    └── memory/
        ├── Context_Notes.md             ← Ngắn hạn: xóa & tạo lại mỗi N chương
        └── Arc_Memory.md                ← Dài hạn: chỉ APPEND, không xóa
```

---

## Cài đặt

```bash
pip install google-genai pydantic python-dotenv tqdm
pip install pyahocorasick   # Khuyến nghị — tăng tốc filter glossary ~10x
```

---

## Cấu hình .env

Tạo file `.env` trong thư mục gốc:

```env
# Bắt buộc
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.5-flash

# Giới hạn API
MAX_RETRIES=5
SUCCESS_SLEEP=30
RATE_LIMIT_SLEEP=60
MIN_CHARS_PER_CHAPTER=500

# Scout AI
SCOUT_LOOKBACK=10          # Số chương gốc Scout đọc mỗi lần
SCOUT_REFRESH_EVERY=5      # Cứ mỗi N chương thành công thì Scout chạy lại
ARC_MEMORY_WINDOW=3        # Số entry Arc Memory đưa vào prompt

# Character rotation
ARCHIVE_AFTER_CHAPTERS=60  # Nhân vật không xuất hiện N chương → Archive

# Merge & Retry
IMMEDIATE_MERGE=true           # Merge nhân vật/thuật ngữ ngay sau mỗi chương
AUTO_MERGE_GLOSSARY=false      # Tự động chạy clean_glossary.py sau pipeline
AUTO_MERGE_CHARACTERS=false    # Tự động chạy clean_characters.py sau pipeline
RETRY_FAILED_PASSES=3          # Số lần retry chương thất bại
```

---

## Sử dụng

### Dịch toàn bộ

```bash
# Bỏ file chương (.txt / .md) vào Raw_English/ rồi chạy:
python translate.py
```

Chương đã có file trong `Translated_VN/` sẽ tự động bỏ qua.

---

### Dịch lại một chương cụ thể

```bash
# Chọn từ danh sách tương tác
python retranslate.py

# Tìm theo từ khoá (số chương, tên file...)
python retranslate.py 0005
python retranslate.py "Chapter 5"

# Liệt kê tất cả chương + trạng thái đã/chưa dịch
python retranslate.py --list

# Dịch lại + cập nhật Glossary / Characters / Skills
python retranslate.py 0005 --update-data
```

> **Mặc định:** chỉ ghi đè bản dịch, **không** cập nhật data — dùng khi chỉ muốn cải thiện chất lượng văn dịch.
> **`--update-data`:** dùng khi chương đó có nhân vật / thuật ngữ / kỹ năng mới chưa được lưu.

---

### Quản lý Glossary

```bash
python clean_glossary.py       # Phân loại thuật ngữ trong Staging vào đúng file
```

---

### Quản lý Character Profile

```bash
python clean_characters.py --action review    # Xem toàn bộ profile
python clean_characters.py --action merge     # Merge Staging → Active
python clean_characters.py --action archive   # Xem nhân vật trong Archive
python clean_characters.py --action validate  # Kiểm tra lỗi schema
python clean_characters.py --action export    # Xuất báo cáo Markdown
python clean_characters.py --action fix       # Tự động sửa lỗi nhỏ
```

---

## Tính năng

### 1. Dịch tuần tự tuyệt đối
Các chương được dịch **từng cái một theo thứ tự**. Chương N+1 luôn có đầy đủ context từ chương N (Glossary, Characters, Skills, Arc Memory đã cập nhật). Không dùng ThreadPool, không song song — chất lượng ưu tiên hơn tốc độ.

---

### 2. Name Lock — Khóa tên nhất quán
M��i tên đã được dịch/phiên âm đều được lưu vào **bảng Name Lock**, đưa vào prompt mỗi chương dưới dạng bảng tra cứu. AI bắt buộc dùng đúng bản chuẩn, không được dùng tên tiếng Anh gốc nếu đã có bản dịch.

- Nguồn: `Characters_Active.json` + `Characters_Archive.json` + Glossary Organizations/Locations/General
- Conflict: giữ bản lock đầu tiên, log cảnh báo
- Validate: sau mỗi chương, hệ thống tự quét bản dịch phát hiện tên tiếng Anh còn sót

---

### 3. Quy tắc dịch tên
| Loại tên | Xử lý |
|---|---|
| Tên gốc Trung (pinyin: Zhang Wei, Xiao Yan...) | Dịch sang **Hán Việt** |
| Tên LitRPG / phương Tây (Arthur, Klein, Backlund...) | **Giữ nguyên** tiếng Anh |
| Danh hiệu / Alias chiến đấu (The Fool, Shadow Scythe...) | Dịch **Hán Việt / Thuần Việt** rồi lock |
| Tên mơ hồ, không rõ nguồn gốc | Dựa vào bối cảnh; nếu vẫn không chắc → giữ nguyên + ghi `new_terms` |

---

### 4. Xưng hô & Quan hệ — Pronoun Priority System
Xưng hô được kiểm tra theo **thứ tự ưu tiên nghiêm ngặt**:

```
1. relationships[X].dynamic — STRONG  →  Đã chốt, KHÔNG thay đổi
2. relationships[X].dynamic — WEAK    →  Dùng tạm, xác nhận khi có tương tác
3. how_refers_to_others[X]            →  Fallback khi chưa có quan hệ
4. how_refers_to_others[default_*]    →  Fallback cuối cùng
```

- `STRONG`: đã xác nhận qua tương tác trực tiếp → không bao giờ thay đổi trừ sự kiện bắt buộc (phản bội, lật mặt, tra khảo, đổi phe...)
- `WEAK`: chọn tạm khi gặp lần đầu → AI báo cáo `promote_to_strong=true` khi xác nhận
- Thay đổi dynamic bắt buộc → tự động promote lên `strong`

---

### 5. Skills.json — Theo dõi kỹ năng
Toàn bộ kỹ năng / chiêu thức được lưu vào `data/skills/Skills.json` với `evolution_chain`.

- Khi dịch bảng hệ thống: AI tra cứu tên kỹ năng đã chốt trước, không tự đặt tên mới
- Kỹ năng mới / tiến hóa: AI báo cáo qua `skill_updates` → hệ thống tự cập nhật
- Filter theo chương: chỉ đưa vào prompt kỹ năng xuất hiện trong chương đó

---

### 6. Tiered Characters + Identity Tracking
- **Active**: nhân vật xuất hiện trong `ARCHIVE_AFTER_CHAPTERS` chương gần nhất → luôn có trong prompt nếu tên match
- **Archive**: lâu không xuất hiện → chỉ load khi tên xuất hiện trong chương
- **Identity Tracking**: `active_identity` + `identity_context` → cảnh báo khi nhân vật đang dùng alias khác tên thật

---

### 7. Scout AI + Arc Memory

**Context Notes** (ngắn hạn):
- Chạy mỗi `SCOUT_REFRESH_EVERY` chương
- Đọc `SCOUT_LOOKBACK` chương gần nhất
- Sinh 4 mục: mạch truyện đặc biệt, khoá xưng hô active, diễn biến gần nhất, cảnh báo cho AI dịch
- Xóa và tạo lại mỗi lần → luôn cập nhật

**Arc Memory** (dài hạn):
- Chỉ APPEND, không bao giờ xóa
- Tóm tắt: sự kiện lớn, thay đổi thế giới, danh tính active, xưng hô đã chốt
- Đưa vào prompt: `ARC_MEMORY_WINDOW` entry gần nhất

---

### 8. Kiểm tra chất lượng bản dịch (Quality Guard)
Trước khi cập nhật Glossary / Characters / Skills, hệ thống kiểm tra bản dịch theo **4 tiêu chí**:

| Tiêu chí | Mô tả | Ngưỡng |
|---|---|---|
| Dính dòng nghiêm trọng | Có dòng vượt X ký tự | > 1000 ký tự/dòng |
| Quá ít dòng | Tổng dòng không rỗng quá ít | < 10 dòng |
| Mất dòng so với bản gốc | Tỉ lệ dòng bị mất cao | > 75% |
| Thiếu dòng trống | Dòng trống quá ít (thiếu khoảng cách đoạn văn) | < 20% tổng số dòng |

Nếu vi phạm → **yêu cầu AI dịch lại** với cảnh báo cụ thể về lỗi, tối đa `MAX_RETRIES` lần. Cảnh báo chỉ tồn tại trong vòng retry của chương đó, sang chương mới là reset.

---

### 9. Categorical Glossary
5 file phân loại riêng biệt — dễ quản lý khi glossary lớn (1000+ dòng):

| File | Nội dung |
|---|---|
| `Glossary_Pathways.md` | Hệ thống tu luyện, Sequence, Path, cảnh giới |
| `Glossary_Organizations.md` | Tổ chức, hội phái, môn phái |
| `Glossary_Items.md` | Vật phẩm, linh khí, bảo vật |
| `Glossary_Locations.md` | Địa danh, thành phố, địa điểm |
| `Glossary_General.md` | Tên riêng, thuật ngữ chung |

Filter thông minh: chỉ đưa thuật ngữ **có trong chương đó** vào prompt, không dump toàn bộ.

---

## Pipeline Flow

```
python translate.py
│
├─ ① Khởi động
│   ├── Nạp config, instructions, char_instructions
│   ├── Lọc chương chưa dịch (skip nếu đã có _VN.txt)
│   └── Hiển thị banner: tổng chương, nhân vật, name lock, skills, cấu hình
│
├─ ② Vòng lặp tuần tự (mỗi chương):
│   │
│   ├─ [Mỗi SCOUT_REFRESH_EVERY chương] Scout AI:
│   │   ├── Xóa Context_Notes.md cũ → sinh mới (4 mục)
│   │   ├── Append Arc_Memory.md (tóm tắt window)
│   │   └── Rotate nhân vật lâu không xuất hiện → Archive
│   │
│   ├─ Build context:
│   │   ├── filter_glossary()       → thuật ngữ liên quan trong chương
│   │   ├── filter_characters()     → Active + Archive match
│   │   ├── load_arc_memory()       → N entry gần nhất
│   │   ├── load_context_notes()    → Scout notes
│   │   ├── build_name_lock_table() → bảng tên đã chốt
│   │   └── load_skills_for_chapter() → kỹ năng liên quan
│   │
│   ├─ Build system prompt (8 phần)
│   │
│   ├─ Gọi Gemini API (retry với backoff):
│   │   ├── Nếu retry do quality → đính cảnh báo cụ thể vào input
│   │   ├── Kiểm tra chất lượng (4 tiêu chí) TRƯỚC khi cập nhật data
│   │   └── Validate Name Lock vi phạm
│   │
│   ├─ Atomic write file dịch (_VN.txt)
│   │
│   ├─ Cập nhật data (theo thứ tự):
│   │   ├── add_new_terms()         → Glossary
│   │   ├── add_skill_updates()     → Skills.json
│   │   ├── update_from_response()  → Characters (new + rel updates)
│   │   └── touch_seen()            → last_seen_chapter_index
│   │
│   └─ [IMMEDIATE_MERGE=true] sync_staging_to_active()
│
├─ ③ Retry pass (RETRY_FAILED_PASSES vòng, chờ RATE_LIMIT_SLEEP giữa các pass)
│
└─ ④ Final sync + Auto-merge (nếu bật) + Tổng kết
```

---

## System Prompt (8 phần)

| Phần | Nội dung | Ghi chú |
|---|---|---|
| 1 | Hướng dẫn dịch | `translateAGENT_INSTRUCTIONS.md` |
| 2 | Từ điển thuật ngữ | Glossary filter + Skills đã biết |
| 3 | Profile nhân vật | Active ưu tiên, Archive khi match |
| 4 | Hướng dẫn lập profile | `CHARACTER_PROFILING_INSTRUCTIONS.md` |
| 5 | Yêu cầu JSON output | 5 trường: translation, new_terms, new_characters, relationship_updates, skill_updates |
| 6 | Arc Memory | N entry gần nhất (nếu có) |
| 7 | Context Notes | Scout AI notes (nếu có) |
| 8 | **Name Lock Table** | Bảng tên đã chốt — ràng buộc CỨNG nhất, để cuối cùng |

---

## Lưu ý quan trọng

**Không xóa thủ công các file trong `data/`** — đây là bộ nhớ tích lũy của pipeline. Xóa sẽ mất toàn bộ context đã xây dựng.

**Thứ tự file trong `Raw_English/`** — pipeline sắp xếp theo tên file (natural sort). Đặt tên file có số thứ tự ở đầu: `0001_...`, `0002_...` để đảm bảo thứ tự đúng.

**Khi thêm thuật ngữ thủ công vào Glossary** — chạy lại `python retranslate.py` cho các chương liên quan để bản dịch phản ánh thuật ngữ mới.