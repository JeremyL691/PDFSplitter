# PDFSplitter

**在本机识别扫描文档，校正章节边界，再拆分原始 PDF。**

[![Tests](https://github.com/JeremyL691/PDFSplitter/actions/workflows/tests.yml/badge.svg)](https://github.com/JeremyL691/PDFSplitter/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](requirements.txt)
[![Target: macOS 13+](https://img.shields.io/badge/target-macOS%2013%2B-orange.svg)](docs/VALIDATION.md)

[快速开始](#快速开始) · [使用指南](docs/USAGE.md) · [验收记录](docs/VALIDATION.md) · [开发路线](docs/STATUS.md) · [参与开发](CONTRIBUTING.md)

适用于需要按章节整理教材、讲义或扫描书籍的场景。PDFSplitter 使用 Apple PDFKit 与 Vision 获取页面文字，比较书签、目录和正文标题，生成可以人工检查的拆分计划。OCR 在本机运行，不调用云端服务。

> **v0.3.0 开发预览**：主体功能已实现，本机 33 项测试通过。macOS 13+ 是构建目标；当前实测为 Apple Silicon / macOS 27.0 / Python 3.12。其他系统与 Intel 的兼容性、真实 Finder 拖拽及发布验收仍待完成，详见 [项目状态](docs/STATUS.md)。

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/evidence/ui-after-dark.jpg">
  <img src="docs/evidence/ui-after-light.jpg" alt="PDFSplitter displaying a scanned contents page, OCR text boxes, page status and editable recognized text" width="1100">
</picture>

*实际应用截图：扫描目录的页面预览、文字位置框、OCR 文本与逐页处理状态。[查看改造前后对比](docs/VALIDATION.md#界面对比与桌面交互)。*

## 从识别到导出

**导入 PDF → 分析与 OCR → 预览、校正 → 更新计划 → 导出**

| 功能 | 可以做什么 |
| --- | --- |
| 本地 OCR | 英文、简体中文、繁体中文和混排；自动判断、关闭或强制识别；中英双通道保留候选 |
| 章节分析 | 从书签、目录和正文获取结构；支持 Part、重复章号、中文编号及同页小节 |
| 预览校正 | 翻页、缩放、文字框定位；修改文字、标题、归属和起止页；新增、合并、拆开或排除范围 |
| 可复用计划 | 保存/加载 JSON，重新 OCR 时保留人工修改，缓存已完成页面 |
| 安全导出 | 校验范围与源文件哈希，暂存完成后整体发布，保留原始页面内容 |
| GUI 与 CLI | 桌面批处理、逐页进度、主题切换；命令行分析、复核与应用计划 |

识别置信度仅作复核提示，不表示准确率。拆分 PDF 保留原页面，当前不添加可搜索 PDF 隐形文字层。

## 快速开始

需要 **macOS、Python 3.12（含 Tk）和 Xcode Command Line Tools**。当前提供源码运行方式，尚无应用安装包。

```bash
git clone https://github.com/JeremyL691/PDFSplitter.git
cd PDFSplitter
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python native/build.py
python main.py --ocr-status
python main.py --gui
```

选择 PDF 后先分析，在 `Page and text` 中检查识别结果，在 `Split plan` 中调整范围。确认告警后再点击 `Export`。导入不会立即写出拆分文件。

命令行也可以先生成计划再导出：

```bash
python main.py book.pdf --dry-run --plan-out review.json
python main.py --apply-plan review.json -o output --accept-warnings
```

`--accept-warnings` 表示已检查非致命告警，不能绕过无效范围、重叠或输入变化。退出码 `3` 表示需要复核。[完整 CLI 与桌面操作](docs/USAGE.md)

## 导出内容

每次导出包含章节 PDF，以及可以复核和再次使用的记录：

```text
output/
  <chapter>/
    <section>.pdf
  document.txt       # 按页分隔的最终文字
  ocr.json           # 位置、来源、置信度与候选
  split-plan.json    # 结构、范围、人工修改与输入哈希
  manifest.json
  manifest.txt
```

默认目录已存在时分配新目录；显式 `-o` 不覆盖非空目录。原文件变化会拒绝旧计划。[导出与缓存规则](docs/USAGE.md#检测缓存和导出规则)

## 验证与后续开发

已有 15 项结构/导出、9 项恢复、5 项真实 Vision 与 4 项 Tk 测试。仓库内提供 [人工标注扫描样本](docs/evidence/annotated-scan.pdf)、[实际验收结果](docs/evidence/native-acceptance.json) 与 [原始测试日志](docs/evidence/test-run.txt)。CI 状态以页首 Actions 徽章和运行记录为准，本机结果不能代替远端验收。

复杂多栏、模糊或倾斜扫描、手写、公式和特殊排版仍需人工检查。下一阶段优先补齐真实桌面与跨平台验收、扩大真实文档覆盖；可搜索 PDF、应用安装包与其他平台 OCR 留待后续版本。

- [项目状态与下一步](docs/STATUS.md)
- [开发交接与复核重点](docs/HANDOFF.md)
- [参与开发与测试](CONTRIBUTING.md)
- [更新记录](CHANGELOG.md)

## License

[MIT](LICENSE) · Copyright © 2026 JeremyL691
