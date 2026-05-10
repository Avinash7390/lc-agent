PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PYCACHE_PREFIX ?= /private/tmp/lc-agent-pycache

.DEFAULT_GOAL := help

.PHONY: help install check run potd contest live-readonly live

help:
	@echo "lc-agent Makefile targets:"
	@echo "  make install                         Install Python dependencies"
	@echo "  make check                           Compile Python files"
	@echo "  make run                             Run interactive mode selection"
	@echo "  make potd                            Run LeetCode Problem of the Day mode"
	@echo "  make contest [CONTEST_SLUG=slug]     Run past contest virtual-practice mode"
	@echo "  make live-readonly [LIVE_CONTEST_SLUG=slug]  Scrape live contest without submitting"
	@echo ""
	@echo "Examples:"
	@echo "  make install"
	@echo "  make potd"
	@echo "  make contest CONTEST_SLUG=weekly-contest-500"
	@echo "  make live-readonly LIVE_CONTEST_SLUG=weekly-contest-501"

install:
	$(PIP) install -r requirements.txt

check:
	PYTHONPYCACHEPREFIX=$(PYCACHE_PREFIX) $(PYTHON) -m compileall .

run:
	$(PYTHON) main.py

potd:
	LC_SOLVER_MODE=potd $(PYTHON) main.py

contest:
	LC_SOLVER_MODE=contest CONTEST_SLUG="$(CONTEST_SLUG)" $(PYTHON) main.py

live-readonly:
	LC_SOLVER_MODE=live-readonly LIVE_CONTEST_SLUG="$(LIVE_CONTEST_SLUG)" $(PYTHON) main.py

live: live-readonly
