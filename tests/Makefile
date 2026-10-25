.PHONY: help install test test-unit test-integration test-cov test-cov-html test-verify score-ci clean

FORM ?= 10-K
SCORE_BASE ?= workspace
TICKERS ?= AAPL,AMZN,V,TDG,AXON
SCORE_OUT_JSON ?=
SCORE_OUT_MD ?=

help:
	@echo "Engine Package 测试命令"
	@echo ""
	@echo "make install         - 安装测试依赖（pytest-cov）"
	@echo "make test            - 运行所有测试"
	@echo "make test-unit       - 仅运行单元测试"
	@echo "make test-integration - 仅运行集成测试"
	@echo "make test-cov        - 运行测试并生成覆盖率报告（终端）"
	@echo "make test-cov-html   - 运行测试并生成 HTML 覆盖率报告"
	@echo "make test-verify     - 验证覆盖率达标（>80%）"
	@echo "make score-ci        - 执行 SEC 报告 CI 评分（FORM=10-K|10-Q）"
	@echo "make clean           - 清理测试生成的文件"

install:
	pip install pytest-cov --break-system-packages

test:
	cd .. && pytest tests/ -v

test-unit:
	cd .. && pytest tests/engine/ -v

test-integration:
	cd .. && pytest tests/integration/ -v

test-cov:
	cd .. && pytest tests/ --cov=alpha/engine --cov-report=term

test-cov-html:
	cd .. && pytest tests/ --cov=alpha/engine --cov-report=html --cov-report=term
	@echo ""
	@echo "HTML 覆盖率报告已生成: htmlcov/index.html"
	@echo "运行 'open htmlcov/index.html' 查看报告"

test-verify:
	cd .. && pytest tests/ --cov=alpha/engine --cov-report=term --cov-fail-under=80
	@echo ""
	@echo "✅ 覆盖率验证通过（>80%）"

score-ci:
	cd .. && python -m alpha.fins.score_sec_ci --form $(FORM) --base $(SCORE_BASE) --tickers $(TICKERS) $(if $(SCORE_OUT_JSON),--output-json $(SCORE_OUT_JSON),) $(if $(SCORE_OUT_MD),--output-md $(SCORE_OUT_MD),)
	@echo ""
	@echo "✅ $(FORM) CI 评分完成"

clean:
	rm -rf .pytest_cache
	rm -rf ../htmlcov
	rm -rf ../.coverage
	rm -rf __pycache__
	rm -rf engine/__pycache__
	rm -rf integration/__pycache__
	rm -rf fixtures/__pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "✅ 清理完成"
