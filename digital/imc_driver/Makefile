# imc_driver: RTL of the IMC tile-array controller (src/), iverilog regression (test/).
#   make test     systolic-reference jobs through the driver + ideal tiles, bit-exact vs the golden
#   make lint     iverilog elaboration of the RTL alone
PY ?= python3
.PHONY: test lint clean
test:
	$(PY) test/run_tests.py
lint:
	iverilog -g2005 -Wall -o /dev/null -s imc_driver src/*.v
clean:
	rm -rf build
