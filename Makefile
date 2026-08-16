# 一键验证入口（设计 §8 第 2 条 / DevOps N4）
# 覆盖 PRD #1–#10 全部验收标准的自动验证部分。
# 验收 #1 的口径依据：CN-001（已由 PM 确认落入 PRD 正文）/ 设计 §4.1 步骤 4「窗口级对账」。
#
# PY 自动探测（O2）：有 .venv 用 .venv，没有则回退 python3——CI 里没有 .venv，
# 换机 / 协作者也未必建过。`?=` 允许 `make PY=/path/to/python test` 覆盖。
PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

# lint 排除规则须与 CI 保持一致，否则给 CI 加 venv 缓存时会毫无征兆地红灯。
LINT_EXCLUDE := docs/research|\.venv

.PHONY: test lint check

test:
	@echo "口径提示：验收 #1 按「窗口级对账」判定（CN-001 / 设计 §4.1 步骤 4）"
	$(PY) -m pytest -q

lint:
	$(PY) -m compileall -q -x '$(LINT_EXCLUDE)' .

check: lint test
