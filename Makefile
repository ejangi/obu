.PHONY: test check integration-wallpapers

test:
	PYTHONPATH=src python3 -m unittest discover -v

check: test
	python3 -m compileall -q src tests

integration-wallpapers:
	python3 tests/integration_restore_check.py
