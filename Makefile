.PHONY: check test bench

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest

test:
	uv run pytest

bench:
	uv run stalecheck bench run --seed 0
