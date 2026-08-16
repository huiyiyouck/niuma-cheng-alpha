# 一键验证入口（设计 §8 第 2 条 / DevOps N4）
# 覆盖 PRD #1–#10 全部验收标准的自动验证部分。
# 验收 #1 的口径依据：CN-001（已由 PM 确认落入 PRD 正文）/ 设计 §4.1 步骤 4「窗口级对账」。
PY := .venv/bin/python

.PHONY: test lint check

test:
	@echo "口径提示：验收 #1 按「窗口级对账」判定（CN-001 / 设计 §4.1 步骤 4）"
	$(PY) -m pytest -q

lint:
	$(PY) -m compileall -q -x 'docs/research|\.venv' .

check: lint test
