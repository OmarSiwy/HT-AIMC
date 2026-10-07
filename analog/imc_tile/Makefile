# imc_tile: Verilog-A models of the chosen IMC tile (va/), driven by digital/imc_driver.
# Run inside ./env.sh mixed (vera, espice, iverilog, numpy). ESPice runs take the shared lock.
#   make lint       vera --lint on every model
#   make units      ESPice unit benches of B1-B5 (test/tb_va_units.py)
#   make cosim      driver RTL -> Verilog-A tiles -> driver chain, both drive modes, ideal + full
#   make timing     t_pass, streaming stalls, drive settling (driver RTL in iverilog)
#   make accuracy   class-weighted SNR_eff per term vs G2 (behavioural, full 8 x 256 tiles)
#   make vasnr      SNR of Verilog-A codes vs the golden, pooled (ESPice, ~30 min per mode)
#   make quality    V9 perplexity of tokact vs block8 operands (heavy python: lock + 4 GB)
#   make test       all of the above plus the golden and driver regressions
PY ?= python3
VA := $(wildcard va/*.va)
.PHONY: lint units cosim timing accuracy vasnr quality golden driver test clean
lint:
	@for f in $(VA); do vera $$f --lint --allow=W0650 >/dev/null && echo "lint OK $$f" || { echo "lint FAIL $$f"; exit 1; }; done
units: lint
	cd test && $(PY) tb_va_units.py
cosim: lint
	cd test && for m in ml2 bitserial; do for k in ideal full; do $(PY) tb_cosim.py $$m $$k || exit 1; done; done
timing:
	cd test && $(PY) tb_timing.py
accuracy:
	cd test && $(PY) tb_accuracy.py
vasnr: lint
	cd test && $(PY) tb_va_snr.py bitserial 4 && $(PY) tb_va_snr.py ml2 4
quality:
	cd test && $(PY) tb_quality.py
golden:
	$(PY) ../../scripts/golden/test_imc_tile.py
driver:
	$(MAKE) -C ../../digital/imc_driver test
test: golden driver units cosim timing accuracy
clean:
	rm -rf output build ../../digital/imc_driver/build
