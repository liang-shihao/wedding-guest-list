# 查询页背景图片 — 短设计

- **意图**：新人可在后台上传一张照片（如婚纱照）作为查询页背景。
- **方案**：A 背景图片（选定）；B 预设配色（未选，无照片）。
- **后台**：页面设置新增「背景图片」：PNG/JPG/WEBP，≤ 1MB（带宽考虑），预览 + 删除。
- **接口**：`POST /api/admin/background`（原始字节，同平面图）、`DELETE /api/admin/background`、`GET /background`（`Cache-Control: public, max-age=86400`，URL 带 `?v=<mtime>`）。`/api/settings` 增加 `has_background`、`background_version`。文件存 `data/background.{ext}`，settings 键 `background`，不可经 PUT settings 修改。
- **查询页**：有背景时用固定定位的背景层铺满（兼容 iOS），上覆半透明浅色蒙版；标题区放进半透明卡片保证可读。无背景时与现在完全一致。
- **非目标**：蒙版深浅、照片位置等可调参数。
- **实现者决定**：蒙版透明度与样式。
