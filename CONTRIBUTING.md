# 参与开发

先阅读 [项目状态](docs/STATUS.md)、[开发交接](docs/HANDOFF.md) 与 [验收记录](docs/VALIDATION.md)。目前优先收尾 v0.3.0 的正确性、真实桌面操作及兼容性验收。

## 开发环境

使用 Python 3.12。原生 OCR 需要 macOS 与 Xcode Command Line Tools；桌面测试还需要可用的 Tk 和图形会话。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python native/build.py
python main.py --ocr-status
```

`.build/`、`.codegraph/` 和缓存不提交。页面缓存默认位于 `~/Library/Caches/PDFSplitter`，测试可通过 `PDFSPLITTER_CACHE_DIR` 使用隔离目录。

## 验证改动

```bash
# 核心与恢复测试；未启用的原生/GUI 测试会跳过
python -m unittest discover -v

# 在有图形会话的 Mac 上启用全部测试
PDFSPLITTER_NATIVE_TESTS=1 PDFSPLITTER_GUI_TESTS=1 \
python -m unittest discover -v

# 人工桌面复验入口
python -m tests.gui_demo --theme light
git diff --check
```

`python -m tests.acceptance` 会重新生成仓库中的标注样本和验收记录。审查输入、计划和哈希是否同步更新；提交原始结果时标注平台及范围。

修复缺陷应先提供可复现输入或有效回归。涉及 OCR 的声明需要真实 Vision 证据；故障替身、拖拽数据解析和 Tk 几何测试各有范围，不能替代完整外部交互。GUI 改动检查 320、768、1024、1440 宽度和浅色/深色主题。

## Issue 与 Pull Request

报告问题时提供系统/架构、Python 版本、复现步骤、期望与实际行为，以及日志或可分享的最小 PDF。章节问题注明 PDF 实际页码与印刷页码。不要上传无法公开分享的文档。

PR 描述说明具体触发条件、修复后的行为、实际验证及剩余限制。改动涉及结构或导出时，核对输入不变、范围有效、输出与清单一致。更新对应使用文档与验收记录。

未覆盖的平台或未执行的 CI 应保留待验证状态，不以部署目标或本机绿灯代替验收。
