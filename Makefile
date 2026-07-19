.PHONY: install lint format typecheck test backtest

install:
	pip install -e ".[dev]"

lint:
	ruff check .

format:
	black .
	ruff check --fix .

typecheck:
	mypy core config market_data features market_regime strategies portfolio risk backtesting analytics journal optimization

test:
	pytest

backtest:
	python scripts/run_backtest.py $(ARGS)
