# 使用指南

[返回项目首页](../README.md) · [验收记录](VALIDATION.md)

## 安装与运行

目标环境：macOS 13+、Python 3.12、Xcode Command Line Tools。当前实际验证的平台和限制见 [验收记录](VALIDATION.md)。Python 必须具备可工作的 Tk，推荐使用 python.org 的 Python 3.12 或已配置 Tk 的环境。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python native/build.py
python main.py --ocr-status
python main.py --gui
```

若没有 Apple 构建工具，先通过系统安装 Xcode Command Line Tools。Swift 辅助程序输出为 `.build/vision-helper`，部署目标 macOS 13，架构取构建机器的架构，独立于 Python 版本。修改 Swift 源码后必须重新构建。原生程序缺失时，`--ocr off` 可以使用 pypdf 文本和书签；需要 OCR 的页面会明确报告错误。

## 桌面使用

- 拖入或选择多个 PDF；文件逐个分析，单文件失败不会阻止后续文件。左栏显示页面处理状态及缓存命中。
- 在“Page and text”中翻页、缩放，点击文字框定位文字；文本光标所在行会突出对应区域。PDF 上的框是识别位置，不会写入输出页面。
- 修改文字后点击“Save text”，然后在“Split plan”中“Rebuild plan”。此时导出会阻止使用过期计划。
- “Run OCR”接受单页或范围，如 `2-5`。人工文字保持原样，新结果保存为待比较候选；通过“Candidates”比较后选择“Use new OCR”或“Keep edits”。两份结果会随计划保存。
- 在计划中编辑标题、编号、章节目录（归属）、起止页；新增、排除/恢复、合并连续范围或拆开范围。“Boundary”定位起始页，前后翻页检查边界。
- 保存/加载 JSON 计划；加载时验证输入哈希。输入移动后可通过 CLI 指定新路径，内容必须相同。
- 检查告警后勾选“Accept reviewed nonfatal warnings”再导出。无效范围、重叠范围、输入变化及未解决页面错误仍会阻止导出。
- 支持跟随系统、浅色、深色及减少动效。窄窗口会折叠设置并提供页面/文字切换；点击“Settings”展开。键盘支持 Tab、Space、Command-S / Control-S、Escape、Alt-左右键。

## CLI

```bash
# 只分析，保存可编辑的计划
python main.py book.pdf --dry-run --plan-out review.json
# 应用已检查的计划
python main.py --apply-plan review.json -o output --accept-warnings
# 原文件移动后应用计划，仍会核对内容哈希
python main.py /new/path/book.pdf --apply-plan review.json -o output
# 直接分析并导出
python main.py book.pdf --ocr auto --ocr-languages mixed --ocr-dpi 300
# 只用原生文本，指定书签或目录
python main.py book.pdf --source outline --ocr off
python main.py book.pdf --source toc --section-depth 2
# 强制重新识别全文
python main.py book.pdf --ocr force --ocr-languages zh-Hant --ocr-dpi 450
python main.py --clear-ocr-cache
python main.py --help
```

`--source auto|outline|toc|scan` 控制结构来源；OCR 独立控制文本获取：

| 参数 | 行为 |
| --- | --- |
| `--ocr auto` | 优先原生文本，有效文字不足 40 字符或替换乱码超过 10% 时 OCR；明确空白页跳过 |
| `--ocr off` | 不运行文字识别；macOS 辅助程序可用于原生文字位置和预览 |
| `--ocr force` | 重新识别全文，绕过页面缓存；GUI 可以只重识别指定页 |
| `--ocr-languages mixed` | 英文通道 + 简体、繁体、英文优先顺序的中文通道 |
| `--ocr-languages en` | 单英文通道 |
| `--ocr-languages zh-Hans / zh-Hant` | 英文通道 + 简中/繁中优先的中文通道 |
| `--ocr-dpi 150 / 300 / 450` | 默认 300；渲染不超过每页 2500 万像素 |
| `--no-ocr-cache` | 禁止读写页面缓存 |

混合识别按位置和文字类型合并，中文通道负责汉字，英文通道负责匹配位置的英文片段。保留另一通道及模型候选。**置信度不是识别准确率**，不作为跨语言唯一选择标准。低置信度或中文通道冲突会要求复核。

退出码：`0` 成功，`1` 操作失败，`2` 参数错误，`3` 需要复核，`130` 取消。指定了不存在的小节深度会返回可选深度，不能静默导出整章。

## 检测、缓存和导出规则

章节使用独立实例和父节点，支持 Part 层级、重复章号、小节书签合成章节、Appendix 字母、英文复合数字及 `第十二章 / 第一节 / 附录 A`。自动模式比较书签、目录和正文候选；目录按文档顺序及独立标题匹配，不把普通正文引用作为标题锚点。无法证实的偏移和同页边界会提示复核。同页标题共享一个原始页面，不能在页面内部裁切。

页面文本只提取一次并复用于目录和正文分析。默认缓存为 `~/Library/Caches/PDFSplitter`，键包含输入内容哈希、页码、系统版本、Vision revision、语言、DPI、辅助程序内容及处理版本。完成的页面在取消后可复用。`PDFSPLITTER_CACHE_DIR` 可用于隔离测试缓存。清除入口只删除本工具命名的缓存内容。

单页处理限时 60 秒，超时会关闭辅助进程、记录该页错误，并重启进程继续下一页。通常整个文档复用一个辅助进程。取消首先终止进程，两秒未退出再强制结束。关闭窗口会等待本次后台任务退出和暂存清理。

- 默认输出为 `<文件名> - split`，已存在时分配 `(2)` 等新目录。
- 显式 `-o` 必须不存在或为空，本版不覆盖非空目录。
- 导出前、发布前核对输入哈希；输出不能指向输入文件。
- 所有文件在同一父目录的独立暂存目录生成，核对页数后整体发布；失败/取消只清理本次暂存内容。
- 未覆盖的前言、排除页或跳过的章引言写入计划和 manifest。

输出包含章节 PDF、兼容的 `manifest.json / manifest.txt`，以及：

- `document.txt`：按 PDF 页分隔的最终文字。
- `ocr.json`：位置、来源、候选和置信度。
- `split-plan.json`：结构、范围、人工修改、待比较结果与输入哈希。

## 开发与验收

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -v
# 本机真实 OCR 和桌面测试，不能在无图形桌面的环境中启用 GUI 测试
PDFSPLITTER_NATIVE_TESTS=1 PDFSPLITTER_GUI_TESTS=1 python -m unittest discover -v
python -m tests.acceptance
```

CI 配置包含 Linux 核心测试和 macOS 原生测试；桌面交互单独本地验收。详情、原始结果、人工标注样本、界面前后对比见 [docs/VALIDATION.md](VALIDATION.md)。

Python API：`analyze_pdf(...) -> SplitPlan`、`validate_plan(...)`、`export_plan(...)`。兼容入口 `split_pdf(...)` 组合分析与导出，保留原返回字段并追加计划与诊断。

## 范围和限制

复杂目录、手写文字、倾斜/模糊扫描、数学公式、图表和特殊排版仍需人工复核。布局恢复采用位置启发式，不保证所有多栏文档。系统 OCR 版本变化可能改变识别结果。当前没有可搜索 PDF 隐形文字层、完整安装包或其他平台 OCR；加密 PDF 暂不支持。macOS 13/14、Intel Mac 和其他 Python 版本尚未进行本地实机验收，不能由当前 Mac 的通过结果推断。

MIT License，见 [LICENSE](../LICENSE)。
