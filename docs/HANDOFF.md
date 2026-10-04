# 接续开发交接

更新日期：2026-10-03（America/Los_Angeles）。在仓库根目录执行后续命令。

## 接续目标与边界

继续完善 v0.3.0，优先关闭 M5 验收缺口及独立复核发现的缺陷。先读 [STATUS.md](STATUS.md)、[VALIDATION.md](VALIDATION.md) 与 [README.md](../README.md)，以当前源代码及新的实际运行结果为准，不把历史测试日志当作最新代码通过证明。

保留 Python 3.12、Tkinter/ttk、pypdf 与小型 Swift PDFKit/Vision 辅助程序路线；保留现有产品文案、橙色强调色、系统字体及 Soft 5/5/5 的设计约定。OCR 仅用于结构识别与文字产物，拆分始终使用原 PDF 页面。隐形文字层、安装包、其他平台 OCR 不属于本轮收尾范围。

本轮开发起点为 `1d29020`（v0.2.0），v0.3.0 实现与交接材料随本轮仓库更新提交。接续时先运行 `git status --short` 和 `git log -1`，检查当前代码与差异，保留现有修改，不要 reset/clean 或覆盖交接成果。GitHub 仓库更新不代表 M5 验收或正式版本发布完成。

## 代码地图

| 文件 | 职责 |
| --- | --- |
| `pdfsplitter/models.py` | 数据对象、计划保存/加载、输入哈希、取消与 OCR 参数 |
| `pdfsplitter/headings.py` | 中英文编号、章节类型和标题解析 |
| `pdfsplitter/splitter.py` | 书签/目录/正文候选、结构评分、范围构建、重建计划、校验及安全导出 |
| `pdfsplitter/toc_parser.py` | 保留的兼容对象/解析帮助函数，公共入口委托统一逻辑 |
| `pdfsplitter/ocr.py` | 原生子进程、单页超时与取消、缓存、双通道文字合并、布局恢复及预览 |
| `native/vision-helper.swift` | JSON Lines 协议 1，PDFKit 渲染/原生文字位置，Vision revision 3 accurate 识别 |
| `native/build.py` | 生成 `.build/vision-helper`，目标 macOS 13，架构跟随本机 |
| `pdfsplitter/gui.py` | 文件批处理、页面/文字预览、人工校正、OCR 冲突、计划编辑与导出状态 |
| `pdfsplitter/cli.py` | OCR 选项、dry-run/apply-plan、告警接受和退出码 |
| `tests/test_core.py` / `test_recovery.py` | 结构、导出、缓存/故障与 CLI 回归 |
| `tests/test_native.py` / `test_gui.py` | 可显式启用的真实 Vision / Tk 测试 |
| `tests/acceptance.py` / `gui_demo.py` | 可访问标注样本验收与人工桌面复验入口 |
| `.github/workflows/tests.yml` | Linux 核心及 macOS 原生测试；远端尚未运行 |

核心接口为 `analyze_pdf(...) -> SplitPlan`、`validate_plan(...)`、`export_plan(...)`；兼容 `split_pdf(...)`。人工修改与 OCR 原始/候选分开保存；未更新计划和未解决候选应阻止误导出。

## 恢复与运行

当前机器使用下面的解释器完成验收；默认 `python3` 可能指向另一版本，应先确认 Python、Tk 与依赖。

```bash
cd PDFSplitter
git status --short
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 --version
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 native/build.py
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 main.py --ocr-status
```

依赖见 `requirements.txt` / `requirements-dev.txt`。若需要新环境，按 README 创建 Python 3.12 虚拟环境。不要为交接无故更换已工作的运行时。

完整本机验收：

```bash
PDFSPLITTER_CACHE_DIR=/private/tmp/pdfsplitter-v030-cache \
PDFSPLITTER_NATIVE_TESTS=1 PDFSPLITTER_GUI_TESTS=1 \
PYTHONDONTWRITEBYTECODE=1 \
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest discover -v

/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m tests.gui_demo --theme light
```

在当前受限执行环境中，Vision 和 Tk 的真实运行需要正常桌面访问，此前通过批准的本机执行获得成功。Swift 编译本身可在受限环境完成。不要把沙箱无法访问原生服务误报成产品缺陷，也不要把跳过原生/GUI 测试后的绿灯算作全套通过。

`python3.12 -m tests.acceptance` 会重新生成 `docs/evidence` 中的标注样本和验收结果。重新生成 PDF 会改变内容哈希，应同步生成记录与计划并审查差异，不能混用新样本和旧计划。实际验收导出在临时目录完成，仓库保留结果记录。

## 先做的复核

以下是建议调查点，**尚未全部复现为缺陷**，不要未经验证写成已确认 bug：

- 无原生辅助程序时，pypdf 某一页提取异常是否能记录为页面错误并继续后续页；原生可用/不可用时乱码判定是否一致。
- 加载人工计划时，对布尔页数、页面文本索引、结构父节点和条目引用的类型/一致性校验是否充分。
- 预览缓存与页面文字缓存的失效条件是否一致；辅助程序、系统版本、旋转与裁剪变化是否可能留下旧预览。
- 更复杂英文数字、目录跨行标题、双栏/多栏、重复页眉是否产生错误章节边界；只有正文普通引用时是否仍拒绝锚点。
- 长文档内存、超时后进程重启、关闭窗口期间任务退出及暂存清理是否在真实压力下成立。

验证核心不变量：输入哈希改变必须拒绝旧计划；无效/重叠范围不可通过告警接受绕过；失败/取消只能清理本次暂存；显式非空输出目录不可覆盖；人工文字不得被重新 OCR 静默替换。

## 尚未关闭的验收与交付方式

1. Finder 真实拖拽。已有解析与批处理测试，但此前桌面自动化的 Tk 坐标点击没有可靠地产生事件。通过真正的文件拖入与状态变化验证，不能只调用 `_on_drop` 后宣称真实拖拽通过。
2. 远端 CI。配置存在，没有实际远端运行记录。运行后记录提交、平台、通过/跳过/失败和修复结果。
3. macOS 13/14、Intel。当前只验证 arm64 macOS 27.0；部署目标不能替代实机测试。
4. 大型与复杂真实文档。旧教材源文件缺失，不使用历史拆分产物替代重跑。新样本应有可访问输入、人工标注与明确复核结果。

每次完成任务更新 STATUS 和 VALIDATION，记录新证据与仍未验证的范围。环境无法满足的项目明确保留待验收，同时继续可独立完成的代码与测试工作。最终说明实际修复、验证结果、剩余缺口；不要只引用已有 README 或旧绿灯宣称全部完成。
