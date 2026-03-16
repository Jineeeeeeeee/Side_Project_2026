<?xml version="1.0" encoding="UTF-8"?>
<CHARACTER_PROFILING_SYSTEM version="2.0_LITRPG_EDITION">

<!--
  Dành cho: AI Agent dịch truyện LitRPG / Tu Tiên
  Mục đích: Hướng dẫn lập và cập nhật Character Profile nhất quán
  Dùng cùng với: Characters.json schema v2.0 + translate.py pipeline
-->

<PHILOSOPHY>
  Profile nhân vật KHÔNG phải bảng thống kê khô khan.
  Profile là BỘ NHỚ SỐNG giúp bản dịch nhất quán từ Chapter 1 đến Chapter 1000.
  Mỗi field phải có giá trị thực dụng: AI đọc vào → biết ngay cách dịch
  hội thoại và hành động của nhân vật đó.
</PHILOSOPHY>


<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!--  PHẦN 1 — KHI NÀO TẠO PROFILE MỚI                                    -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->

<PROFILE_CREATION>

  <CREATE_WHEN>
    <CONDITION>Nhân vật có tên riêng VÀ xuất hiện hơn 1 lần trong chương</CONDITION>
    <CONDITION>Có ít nhất 1 dòng hội thoại hoặc được mô tả hành động cụ thể</CONDITION>
    <CONDITION>Có quan hệ rõ ràng với MC hoặc nhân vật chính khác</CONDITION>
  </CREATE_WHEN>

  <DO_NOT_CREATE_FOR>
    <EXCEPTION>NPC vô danh: tên lính, người qua đường không có tên</EXCEPTION>
    <EXCEPTION>Nhân vật được nhắc thoáng qua, không có interaction trực tiếp</EXCEPTION>
  </DO_NOT_CREATE_FOR>

</PROFILE_CREATION>


<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!--  PHẦN 2 — HƯỚNG DẪN ĐIỀN TỪNG FIELD                                  -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->

<FIELD_GUIDE>

  <!-- 2.1 identity -->
  <FIELD id="identity">
    <SUB name="full_name">
      Tên đầy đủ theo bản gốc. Giữ nguyên tiếng Anh.
    </SUB>
    <SUB name="aliases">
      Biệt danh, danh hiệu phi chính thức.
      Dịch sang Hán Việt nếu là danh hiệu chiến đấu.
    </SUB>
    <SUB name="title_history">
      Danh hiệu chính thức. Ghi chapter_acquired và chapter_lost.
      chapter_lost = null nếu nhân vật còn giữ danh hiệu đó.
    </SUB>
    <SUB name="current_title">
      Danh hiệu đang dùng khi xưng hô trang trọng ở thời điểm hiện tại.
    </SUB>
    <SUB name="faction">Guild, môn phái, phe phái. Dịch Hán Việt.</SUB>
    <SUB name="cultivation_path">Hệ năng lực / tu luyện. Dịch sát nghĩa + Hán Việt.</SUB>
  </FIELD>

  <!-- 2.2 power -->
  <FIELD id="power">
    <SUB name="current_level">
      Rank / Cảnh giới — viết đầy đủ.
      <EX en="Rank B" vn="Rank B — Thức Tỉnh Tầng 3"/>
    </SUB>
    <SUB name="level_history">
      LUÔN ghi lại mỗi lần thăng cấp kèm chapter tương ứng.
      Không bỏ sót bất kỳ lần thăng cấp nào.
    </SUB>
    <SUB name="signature_skills">
      Chỉ ghi kỹ năng ĐẶC TRƯNG — dùng nhiều lần hoặc định nghĩa nhân vật.
      Format bắt buộc: ["[Tên VN]"] — LUÔN dùng ngoặc vuông, LUÔN dịch tên kỹ năng.
      <EX wrong='["Fireball"]' correct='["[Hỏa Cầu]"]'/>
    </SUB>
    <SUB name="combat_style">
      Mô tả bằng câu đầy đủ: chiến thuật ưa dùng, điểm mạnh, điểm yếu.
    </SUB>
  </FIELD>

  <!-- 2.3 personality_traits — QUAN TRỌNG NHẤT -->
  <FIELD id="personality_traits" priority="HIGHEST">
    <RULE>
      Mỗi trait phải là 1 câu mô tả ĐỦ NGỮ CẢNH để dùng ngay khi dịch.
      KHÔNG dùng keyword ngắn một mình.
      Mỗi nhân vật nên có 4–6 traits. Không nhiều hơn.
    </RULE>
    <EXAMPLES>
      <BAD>"Lạnh lùng, mạnh mẽ, bí ẩn"</BAD>
      <GOOD>
        "Bề ngoài lạnh lùng với người lạ nhưng thực ra đang quan sát và đánh giá —
         một khi đã tin thì trung thành tuyệt đối"
      </GOOD>
      <BAD>"Thích chiến đấu"</BAD>
      <GOOD>
        "Không tìm kiếm chiến đấu nhưng KHÔNG BAO GIỜ bỏ chạy khi đồng đội bị đe dọa —
         đây là điểm bất hợp lý duy nhất trong logic tự bảo toàn của hắn"
      </GOOD>
    </EXAMPLES>
  </FIELD>

  <!-- 2.4 speech -->
  <FIELD id="speech">
    <SUB name="pronoun_self">
      Đại từ xưng hô MẶC ĐỊNH của nhân vật.
      Các lựa chọn: Tao / Ta / Tôi / Tớ / Mình / Bổn tọa / Lão phu / Ta...
    </SUB>
    <SUB name="formality_level">Giá trị: low / medium-low / medium / medium-high / high</SUB>
    <SUB name="formality_note">
      Ghi điều kiện CỤ THỂ khi nào thay đổi formality.
      <EX vn="Chỉ nâng lên Tôi khi gặp người lạ lần đầu hoặc tình huống ngoại giao bắt buộc"/>
    </SUB>
    <SUB name="how_refers_to_others" priority="HIGH">
      Key = tên nhân vật cụ thể HOẶC "default_ally" / "default_enemy".
      Value = đại từ gọi họ + ngữ cảnh dùng.
      <EX key="Elara"         value="Cậu (thân thiết) / Ê cậu ơi (khi hối thúc)"/>
      <EX key="default_enemy" value="Mày — chủ động hạ cấp để thể hiện coi thường"/>
      <EX key="default_ally"  value="Ông/Tôi hoặc Anh/Tôi tùy tuổi"/>
    </SUB>
    <SUB name="speech_quirks">
      Từ khóa / kiểu nói ĐẶC TRƯNG. Phải dùng được ngay khi dịch hội thoại.
      <EX vn="Hay kết câu bằng '...hiểu chưa?' với giọng không cần biết đối phương có hiểu không"/>
      <EX vn="Khi thật sự tức giận thì ngược lại — nói rất ít, rất chậm, rất lạnh"/>
    </SUB>
  </FIELD>

  <!-- 2.5 habitual_behaviors -->
  <FIELD id="habitual_behaviors">
    <RULE>
      CHỈ GHI KHI CÓ BẰNG CHỨNG thực tế trong văn bản.
      Confidence dưới 0.65 → KHÔNG GHI, bỏ qua hoàn toàn.
    </RULE>
    <SUB name="behavior">Mô tả hành động CỤ THỂ. Không trừu tượng.</SUB>
    <SUB name="trigger">Điều kiện kích hoạt hành vi này.</SUB>
    <SUB name="intensity">Giá trị: subtle (khó thấy) / medium / strong (rõ ràng)</SUB>
    <SUB name="narrative_effect">Tác dụng với độc giả và bản dịch là gì?</SUB>
    <SUB name="evidence_chapters">
      Danh sách chapter đã xuất hiện. BẮT BUỘC phải có dẫn chứng.
      Không có dẫn chứng → không ghi behavior này.
    </SUB>
    <SUB name="confidence">
      Thang đo 0.0–1.0.
      Dưới 0.65: chưa chắc chắn → BỎ QUA.
      0.65–0.79: có bằng chứng nhưng chưa đủ chắc.
      0.80–1.00: đã xác nhận nhiều lần.
    </SUB>
  </FIELD>

  <!-- 2.6 relationships -->
  <FIELD id="relationships">
    <SUB name="type">
      đồng đội / kẻ thù / thầy trò / tình địch / đồng minh bất đắc dĩ /
      tình nhân / đối thủ / ân nhân...
    </SUB>
    <SUB name="feeling">
      Cảm xúc HIỆN TẠI của nhân vật này với nhân vật kia.
      Cập nhật mỗi khi thay đổi — không để cảm xúc cũ.
    </SUB>
    <SUB name="dynamic">
      Cặp đại từ khi 2 người nói chuyện — ghi cả 2 chiều và điều kiện thay đổi.
      <EX vn="Tao/Mày → Tớ/Cậu (sau Chapter_03 khi đã thân thiết hơn)"/>
    </SUB>
    <SUB name="current_status">
      1 câu mô tả trạng thái quan hệ hiện tại. Cụ thể, không chung chung.
    </SUB>
    <SUB name="tension_points">
      Mâu thuẫn NGẦM chưa được giải quyết giữa 2 nhân vật.
      Rất quan trọng cho việc dịch đúng ngữ điệu hội thoại.
      <EX vn="Elara biết bí mật về vết sẹo của Arthur — Arthur không biết cô biết"/>
    </SUB>
    <SUB name="history">
      Mỗi entry = 1 sự kiện THỰC SỰ thay đổi bản chất quan hệ.
      Không ghi sự kiện nhỏ, giao tiếp thông thường.
      Format: {"chapter": "Chapter_XX", "event": "Mô tả ngắn gọn"}
    </SUB>
  </FIELD>

  <!-- 2.7 arc_status -->
  <FIELD id="arc_status">
    <SUB name="current_goal">Mục tiêu nhân vật đang theo đuổi (độc giả đã biết).</SUB>
    <SUB name="hidden_goal">
      Mục tiêu thật sự chưa lộ, hoặc nhân vật tự che giấu.
      Khi hidden_goal lộ ra → chuyển sang current_goal, ghi chú chapter lộ.
    </SUB>
    <SUB name="current_conflict">Xung đột nội tâm hoặc ngoại cảnh đang diễn ra.</SUB>
    <SUB name="last_updated">Chapter cuối cùng cập nhật arc_status này.</SUB>
  </FIELD>

</FIELD_GUIDE>


<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!--  PHẦN 3 — KHI NÀO CẬP NHẬT PROFILE                                   -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->

<UPDATE_TRIGGERS>

  <UPDATE_NOW>
    <TRIGGER event="Thăng cấp / đạt cảnh giới mới"
             fields="power.current_level, power.level_history"/>
    <TRIGGER event="Học được kỹ năng đặc trưng mới"
             fields="power.signature_skills"/>
    <TRIGGER event="Nhận hoặc mất danh hiệu"
             fields="identity.title_history, identity.current_title"/>
    <TRIGGER event="Chuyển phe / rời guild"
             fields="identity.faction"/>
    <TRIGGER event="Quan hệ thay đổi rõ ràng: phản bội, hòa giải, yêu..."
             fields="relationships[X].feeling, .current_status, .dynamic, .history"/>
    <TRIGGER event="Phát hiện tension mới giữa 2 nhân vật"
             fields="relationships[X].tension_points"/>
    <TRIGGER event="Mục tiêu nhân vật thay đổi"
             fields="arc_status.current_goal hoặc hidden_goal"/>
    <TRIGGER event="Hidden goal lộ ra"
             fields="hidden_goal → current_goal (ghi chú chapter lộ)"/>
    <TRIGGER event="Phát hiện thói quen mới có bằng chứng"
             fields="habitual_behaviors[]"/>
  </UPDATE_NOW>

  <DO_NOT_UPDATE_WHEN>
    <SKIP>Sự kiện nhỏ không thay đổi bản chất quan hệ</SKIP>
    <SKIP>Hành động nhất thời không phản ánh tính cách lâu dài</SKIP>
    <SKIP>Thông tin chưa đủ bằng chứng — confidence dưới 0.65</SKIP>
  </DO_NOT_UPDATE_WHEN>

</UPDATE_TRIGGERS>


<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!--  PHẦN 4 — RELATIONSHIP_UPDATES FORMAT                                 -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->

<RELATIONSHIP_UPDATE_PROTOCOL>

  <RULE>
    Chỉ báo cáo khi quan hệ THỰC SỰ thay đổi trong chương vừa dịch.
    Chỉ điền field nào THỰC SỰ thay đổi. Field không thay đổi → để chuỗi rỗng "".
  </RULE>

  <FORMAT>
    <![CDATA[
{
  "character_a"  : "Tên nhân vật chủ thể",
  "character_b"  : "Tên nhân vật đối tượng",
  "chapter"      : "Chapter_XX",
  "event"        : "Mô tả sự kiện CỤ THỂ gây ra thay đổi — không chung chung",
  "new_type"     : "(bỏ trống nếu không đổi)",
  "new_feeling"  : "(bỏ trống nếu không đổi)",
  "new_status"   : "(bỏ trống nếu không đổi)",
  "new_dynamic"  : "(bỏ trống nếu không đổi)",
  "new_tension"  : "(bỏ trống nếu không có tension mới)"
}
    ]]>
  </FORMAT>

  <EXAMPLE>
    <![CDATA[
{
  "character_a"  : "Arthur",
  "character_b"  : "Elara",
  "chapter"      : "Chapter_05",
  "event"        : "Elara che chắn Arthur khi bị phục kích — Arthur nhận ra cô biết rõ rủi ro",
  "new_feeling"  : "biết ơn + lo lắng ngược — không muốn Elara bị thương vì mình",
  "new_status"   : "thân thiết — có chiều sâu chưa được nói ra",
  "new_tension"  : "Arthur bắt đầu muốn giữ khoảng cách để bảo vệ Elara — Elara không biết",
  "new_type"     : "",
  "new_dynamic"  : ""
}
    ]]>
  </EXAMPLE>

</RELATIONSHIP_UPDATE_PROTOCOL>


<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!--  PHẦN 5 — CÁCH DÙNG PROFILE KHI DỊCH                                 -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->

<TRANSLATION_USAGE>

  <PRIORITY_ORDER>
    <STEP order="1" use_for="Xưng hô hội thoại mặc định">
      speech.pronoun_self + speech.how_refers_to_others
    </STEP>
    <STEP order="2" use_for="Xưng hô cụ thể khi nói với nhân vật X">
      relationships[X].dynamic
    </STEP>
    <STEP order="3" use_for="Thêm vào cuối câu thoại khi phù hợp">
      speech.speech_quirks
    </STEP>
    <STEP order="4" use_for="Giọng điệu tổng thể cả đoạn">
      personality_traits
    </STEP>
    <STEP order="5" use_for="Khi mô tả hành động / cử chỉ nhân vật">
      habitual_behaviors (chỉ dùng khi confidence >= 0.65)
    </STEP>
    <STEP order="6" use_for="Ngữ điệu độc thoại nội tâm">
      arc_status.current_conflict
    </STEP>
  </PRIORITY_ORDER>

  <EXAMPLE>
    <SOURCE_EN>Arthur sighed. "Fine. I'll help you," he said, not meeting her eyes.</SOURCE_EN>
    <PROFILE_CHECK>
      <CHECK field="pronoun_self">Tao</CHECK>
      <CHECK field='how_refers_to_others["Elara"]'>Tớ/Cậu</CHECK>
      <CHECK field="habitual_behaviors[1]">Thở dài rồi mới nói câu chấp nhận giúp đỡ</CHECK>
      <CHECK field="speech_quirks">Khi thật sự tức giận nói rất ít, rất lạnh</CHECK>
    </PROFILE_CHECK>
    <OUTPUT_VN>
      Arthur thở dài. "Thôi được. Tao giúp cậu," hắn nói, ánh mắt nhìn chỗ khác.
    </OUTPUT_VN>
  </EXAMPLE>

</TRANSLATION_USAGE>


<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!--  PHẦN 6 — LƯU Ý ĐẶC THÙ THỂ LOẠI LITRPG / TU TIÊN                   -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->

<GENRE_SPECIFIC_RULES>

  <TITLES_AND_RANKS>
    <RULE>Danh hiệu chiến đấu → Hán Việt.
      <EX en="Shadow Scythe"    vn="Hắc Liêm Thần"/>
      <EX en="White Fire Archer" vn="Bạch Hỏa Cung Thủ"/>
    </RULE>
    <RULE>Cảnh giới tu luyện → Giữ hệ thống nhất quán từ chapter 1, không tự thay đổi.</RULE>
    <RULE>Khi nhân vật thăng cấp → Kiểm tra xem pronoun_self có thay đổi không.
      Một số nhân vật chuyển từ "Tôi" → "Ta" sau khi đạt ngưỡng sức mạnh nhất định.
    </RULE>
  </TITLES_AND_RANKS>

  <POWER_DYNAMIC_PRONOUNS>
    <RULE>Kẻ mạnh hơn thường dùng "Ta/Ngươi" hoặc "Tao/Mày" tùy tính cách.</RULE>
    <RULE>Khi bị áp đảo về sức mạnh → kẻ yếu hơn tự động nâng cấp đại từ lên trang trọng hơn.</RULE>
    <RULE>Ghi rõ điều kiện trong dynamic:
      <EX vn='"Tao/Mày (khi ngang sức) → Ta/Ngươi (khi Arthur vượt hẳn về Rank)"'/>
    </RULE>
  </POWER_DYNAMIC_PRONOUNS>

  <SYSTEM_ENTITIES>
    <RULE>SYSTEM thông báo thông thường → KHÔNG có profile nhân vật.</RULE>
    <RULE>Nếu System có "nhân cách" riêng (Spirit Companion, AI System có cảm xúc...)
      → TẠO PROFILE đầy đủ với archetype = SYSTEM_AI.
    </RULE>
  </SYSTEM_ENTITIES>

</GENRE_SPECIFIC_RULES>


<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!--  PHẦN 7 — ARCHETYPES THAM KHẢO                                        -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->

<ARCHETYPE_REFERENCE>
  <!--
    Dùng để điền field archetype trong CharacterDetail.
    Chọn archetype GẦN NHẤT, không cần hoàn toàn khớp.
  -->
  <A id="MC_GREMLIN"    voice="Cợt nhả / Ảo thật"          pronoun_default="Tao/Mày"/>
  <A id="SYSTEM_AI"     voice="Vô cảm / Châm biếm ngầm"    pronoun_default="Hệ thống/Ký chủ"/>
  <A id="EDGELORD"      voice="Tỏ vẻ nguy hiểm / Ngầu lòi" pronoun_default="Ta/Bọn kiến rệp"/>
  <A id="ARROGANT_NOBLE" voice="Khinh khỉnh / Thượng đẳng" pronoun_default="Bản thiếu gia/Ngươi"/>
  <A id="BRO_COMPANION" voice="Sảng khoái / Nhiệt huyết"   pronoun_default="Tớ/Cậu"/>
  <A id="ANCIENT_MAGE"  voice="Cổ trang / Uyên bác"        pronoun_default="Lão phu/Tiểu tử"/>
  <A id="UNKNOWN"       voice="Chưa xác định"               pronoun_default="Tôi/Bạn"/>
</ARCHETYPE_REFERENCE>

</CHARACTER_PROFILING_SYSTEM>