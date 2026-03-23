.PHONY: init build rebuild ui ui-d stop logs shell \
        translate retranslate stats \
        clean-glossary merge-chars fix-names \
        validate-chars export-chars \
        epub epub-one translate-book

# ── Setup ─────────────────────────────────────────────────────────

## Tạo thư mục cần thiết và file .env từ template (chỉ chạy lần đầu)
init:
	mkdir -p inputs outputs logs data/glossary data/characters \
	         data/skills data/memory prompts epub
	@if [ ! -f .env ]; then \
	    cp .env.example .env && \
	    echo "✅ .env tạo từ .env.example"; \
	    echo "   → Mở .env và điền GEMINI_API_KEY trước khi chạy."; \
	else \
	    echo "ℹ️  .env đã tồn tại — bỏ qua."; \
	fi

# ── Image ─────────────────────────────────────────────────────────

## Build image (lần đầu ~3-5 phút do compile pyahocorasick)
build:
	docker compose build

## Rebuild từ đầu, không dùng cache
rebuild:
	docker compose build --no-cache

# ── Web UI ────────────────────────────────────────────────────────

## Chạy Web UI (foreground — Ctrl+C để dừng)
ui:
	docker compose up ui

## Chạy Web UI nền (background)
ui-d:
	docker compose up -d ui

## Dừng tất cả containers
stop:
	docker compose down

## Xem log Web UI theo thời gian thực
logs:
	docker compose logs -f ui

# ── CLI Pipeline ──────────────────────────────────────────────────

## Dịch tất cả chương chưa dịch
translate:
	docker compose run --rm cli python main.py translate

## Dịch lại 1 chương. Dùng: make CHAPTER=42 retranslate
## hoặc: make CHAPTER=chapter_001.txt retranslate
retranslate:
	@if [ -z "$(CHAPTER)" ]; then \
	    echo "❌ Thiếu CHAPTER. Dùng: make CHAPTER=42 retranslate"; \
	    exit 1; \
	fi
	docker compose run --rm cli python main.py retranslate $(CHAPTER)

## Thống kê nhanh
stats:
	docker compose run --rm cli python main.py stats

## Phân loại thuật ngữ từ Staging vào đúng Glossary file
clean-glossary:
	docker compose run --rm cli python main.py clean glossary

## Merge Staging_Characters → Active
merge-chars:
	docker compose run --rm cli python main.py clean characters --action merge

## Xem và sửa vi phạm Name Lock
fix-names:
	docker compose run --rm cli python main.py fix-names

## Kiểm tra schema character profiles
validate-chars:
	docker compose run --rm cli python main.py clean characters --action validate

## Xuất báo cáo nhân vật ra Reports/
export-chars:
	docker compose run --rm cli python main.py clean characters --action export

# ── Dev ───────────────────────────────────────────────────────────

## Mở shell trong container (debug)
shell:
	docker compose run --rm cli bash

# ── EPUB Processor ────────────────────────────────────────────────

## Xử lý tất cả .epub trong epub/
epub:
	docker compose run --rm cli python main.py epub process

## Xử lý 1 file: make EPUB=mybook.epub epub-one
epub-one:
	@if [ -z "$(EPUB)" ]; then \
	    echo "❌ Thiếu EPUB. Dùng: make EPUB=mybook.epub epub-one"; \
	    exit 1; \
	fi
	docker compose run --rm cli python main.py epub process $(EPUB)

## Dịch 1 sách epub đã xử lý: make BOOK=mybook translate-book
translate-book:
	@if [ -z "$(BOOK)" ]; then \
	    echo "❌ Thiếu BOOK. Dùng: make BOOK=mybook translate-book"; \
	    exit 1; \
	fi
	docker compose run --rm cli python main.py translate --book $(BOOK)