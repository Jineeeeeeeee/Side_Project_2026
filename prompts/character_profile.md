<?xml version="1.0" encoding="UTF-8"?>
<CHARACTER_PROFILING_SYSTEM version="2.0_LITRPG_EDITION">

<PHILOSOPHY>
  Profile nhân vật KHÔNG phải bảng thống kê khô khan.
  Profile là BỘ NHỚ SỐNG giúp bản dịch nhất quán từ Chapter 1 đến Chapter 1000.
  Mỗi field phải có giá trị thực dụng: AI đọc vào → biết ngay cách dịch
  hội thoại và hành động của nhân vật đó.
</PHILOSOPHY>

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

<FIELD_GUIDE>

  <FIELD id="personality_traits" priority="HIGHEST">
    <RULE>
      Mỗi trait phải là 1 câu mô tả ĐỦ NGỮ CẢNH để dùng ngay khi dịch.
      KHÔNG dùng keyword ngắn một mình. 4–6 traits.
    </RULE>
    <EXAMPLES>
      <BAD>"Lạnh lùng, mạnh mẽ, bí ẩn"</BAD>
      <GOOD>"Bề ngoài lạnh lùng với người lạ nhưng đang quan sát và đánh giá — một khi đã tin thì trung thành tuyệt đối"</GOOD>
    </EXAMPLES>
  </FIELD>

  <FIELD id="speech">
    <SUB name="pronoun_self">Tao / Ta / Tôi / Tớ / Mình / Bổn tọa / Lão phu...</SUB>
    <SUB name="formality_level">low / medium-low / medium / medium-high / high</SUB>
    <SUB name="how_refers_to_others">
      Key = tên nhân vật cụ thể HOẶC "default_ally" / "default_enemy".
      Value = đại từ gọi họ + ngữ cảnh.
    </SUB>
    <SUB name="speech_quirks">Từ khóa / kiểu nói ĐẶC TRƯNG. Phải dùng được ngay khi dịch.</SUB>
  </FIELD>

  <FIELD id="habitual_behaviors">
    <RULE>CHỈ GHI KHI CÓ BẰNG CHỨNG thực tế. Confidence dưới 0.65 → KHÔNG GHI.</RULE>
    <SUB name="confidence">0.65–0.79: có bằng chứng nhưng chưa đủ. 0.80–1.00: đã xác nhận.</SUB>
  </FIELD>

  <FIELD id="relationships">
    <SUB name="dynamic">
      Cặp đại từ khi 2 người nói chuyện — ghi cả 2 chiều.
      ĐÂY LÀ NGUỒN ƯU TIÊN CAO NHẤT khi dịch hội thoại.
    </SUB>
    <SUB name="pronoun_status">
      weak  = chưa có tương tác đủ để chốt.
      strong = đã được xác nhận qua tương tác trực tiếp, KHÔNG thay đổi
               trừ sự kiện bắt buộc (phản bội, tra khảo, lật mặt, đổi phe...).
    </SUB>
  </FIELD>

</FIELD_GUIDE>

<UPDATE_TRIGGERS>
  <UPDATE_NOW>
    <TRIGGER event="Thăng cấp"                         fields="power.current_level, power.level_history"/>
    <TRIGGER event="Học kỹ năng đặc trưng mới"          fields="power.signature_skills"/>
    <TRIGGER event="Quan hệ thay đổi rõ ràng"           fields="relationships[X].*"/>
    <TRIGGER event="Mục tiêu thay đổi"                  fields="arc_status.*"/>
    <TRIGGER event="Hidden goal lộ ra"                  fields="hidden_goal → current_goal"/>
  </UPDATE_NOW>
  <DO_NOT_UPDATE_WHEN>
    <SKIP>Sự kiện nhỏ không thay đổi bản chất quan hệ</SKIP>
    <SKIP>Thông tin chưa đủ bằng chứng — confidence dưới 0.65</SKIP>
  </DO_NOT_UPDATE_WHEN>
</UPDATE_TRIGGERS>

<GENRE_SPECIFIC_RULES>
  <TITLES_AND_RANKS>
    <RULE>Danh hiệu chiến đấu → Hán Việt. VD: "Shadow Scythe" → "Hắc Liêm Thần"</RULE>
    <RULE>Khi nhân vật thăng cấp → kiểm tra xem pronoun_self có thay đổi không.</RULE>
  </TITLES_AND_RANKS>
  <POWER_DYNAMIC_PRONOUNS>
    <RULE>Kẻ mạnh hơn thường dùng "Ta/Ngươi" hoặc "Tao/Mày" tùy tính cách.</RULE>
    <RULE>Khi bị áp đảo → kẻ yếu tự động nâng cấp đại từ lên trang trọng hơn.</RULE>
  </POWER_DYNAMIC_PRONOUNS>
</GENRE_SPECIFIC_RULES>

<ARCHETYPE_REFERENCE>
  <A id="MC_GREMLIN"    voice="Cợt nhả / Ảo thật"          pronoun_default="Tao/Mày"/>
  <A id="SYSTEM_AI"     voice="Vô cảm / Châm biếm ngầm"    pronoun_default="Hệ thống/Ký chủ"/>
  <A id="EDGELORD"      voice="Tỏ vẻ nguy hiểm / Ngầu lòi" pronoun_default="Ta/Bọn kiến rệp"/>
  <A id="ARROGANT_NOBLE" voice="Khinh khỉnh / Thượng đẳng" pronoun_default="Bản thiếu gia/Ngươi"/>
  <A id="BRO_COMPANION" voice="Sảng khoái / Nhiệt huyết"   pronoun_default="Tớ/Cậu"/>
  <A id="ANCIENT_MAGE"  voice="Cổ trang / Uyên bác"        pronoun_default="Lão phu/Tiểu tử"/>
  <A id="UNKNOWN"       voice="Chưa xác định"               pronoun_default="Tôi/Bạn"/>
</ARCHETYPE_REFERENCE>

</CHARACTER_PROFILING_SYSTEM>
