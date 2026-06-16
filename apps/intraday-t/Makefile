.PHONY: help web test

help:
	@printf "可用命令:\n"
	@printf "  make web   启动本地 Web UI\n"
	@printf "  make test  运行 unittest 测试\n"

web:
	python scripts/intraday_web.py

test:
	PYTHONPATH=src python -m unittest discover -s tests -v
