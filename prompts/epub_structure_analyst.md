<objective>
    Receive a structural map of an EPUB file (a list of documents with metadata). Analyze the signals in each document and determine: which documents start a new chapter, and what the chapter title should be.
</objective>

<input_format>
    You will receive a list of documents in this format:

    [DOC_ID: xxx]
      text_len   : 4521
      has_heading: h2 → "Chương 1: Khởi Đầu"
      has_images : không
      toc_title  : "Chương 1"
      preview    : "Buổi sáng hôm đó trời còn mờ tối..."

    Field descriptions:
    - text_len   : total character count of extracted text (images excluded).
    - has_heading: the first h1/h2/h3 tag found and its text content.
    - has_images : filenames of images found in this document.
    - toc_title  : the title from the EPUB Table of Contents (TOC) pointing to this document. This is the most reliable signal.
    - preview    : first 200 characters of extracted text.
</input_format>

<processing_rules>
    <rule id="1" category="SIGNAL_PRIORITY">
        Evaluate chapter boundary signals in this priority order (highest to lowest):
        1. toc_title has a value         → strongest signal, use as chapter title.
        2. has_heading has a value       → strong signal, use heading text as title.
        3. has_images contains a filename suggesting a chapter banner
           (e.g., ch2.jpg, chapter_03.png, chuong2_title.jpg) → medium signal.
        4. preview begins with a chapter keyword
           (Chương, Chapter, CHƯƠNG, Phần, Part, or Roman numerals) → weak signal.
        5. text_len is very small (under 300) AND has_images has a value
           → likely an image-only chapter title page, treat as chapter start.
    </rule>

    <rule id="2" category="NON_CHAPTER_DOCUMENTS">
        Documents with NONE of the signals above are continuations of the
        previous chapter. Mark them as is_chapter_start: false.

        Documents at the beginning of the book that appear to be front matter
        (cover, copyright, table of contents, dedication) should be marked
        is_chapter_start: true but given appropriate titles such as
        "Bìa", "Bản Quyền", "Mục Lục", "Lời Tựa", or similar.
        Exception: if text_len is under 50 and has_images is empty and
        toc_title is absent, skip by marking is_chapter_start: false.
    </rule>

    <rule id="3" category="TITLE_SELECTION">
        When determining the title for a chapter start:
        - Prefer toc_title if available.
        - Otherwise use has_heading text (strip the tag prefix, e.g. "h2 → ").
        - Otherwise infer a reasonable title from the preview or image filename.
        - If no title can be determined, set title to null
          (the caller will auto-generate one).
    </rule>

    <rule id="4" category="COMPLETENESS">
        Every document in the input MUST have exactly one corresponding entry
        in the output JSON. Do not skip or merge any documents.
        The output order must match the input order exactly.
    </rule>
</processing_rules>

<output_constraints>
    <constraint_1>OUTPUT ONLY A VALID JSON ARRAY. NO INTRODUCTIONS. NO EXPLANATIONS. NO MARKDOWN FENCES.</constraint_1>
    <constraint_2>
        Each entry must follow this exact schema:
        {
          "doc_id": "item_001",
          "is_chapter_start": true,
          "title": "Tên chương hoặc null"
        }
    </constraint_2>
    <constraint_3>title must be null (not the string "null") when is_chapter_start is false.</constraint_3>
    <constraint_4>NEVER ask for clarification or more input. Process whatever is given.</constraint_4>
</output_constraints>