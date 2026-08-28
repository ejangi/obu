.PHONY: test check

test:
	PYTHONPATH=src python3 -m unittest discover -v

check: test
	python3 -m compileall -q src scripts
