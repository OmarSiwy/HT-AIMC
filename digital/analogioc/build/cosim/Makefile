# Mixed-signal co-sim: analogioc_top RTL (VerA .v device) inside ESPice with the
# analogioc SPICE macro. Run inside ./env.sh mixed (espice, vera, numpy).
# See cosim.py and docs/src/content/Template/Flows/Mixed-Signal.ts.
#
#   make cosim-smoke                 toy macro, seconds: A2D/D2A bridge end to end
#   make cosim-elab                  generate + VerA elaboration only (no simulation)
#   make cosim                       A9:  pass_05 through the SPICE macro (LONG)
#   make cosim PASSES="00 05 09"     A12: back to back (LONG)
PY      ?= python3
ESPICE  ?= espice
VERA    ?= vera
PASSES  ?= 05
export ESPICE VERA

.PHONY: cosim cosim-smoke cosim-elab gen clean

cosim-smoke:
	$(PY) cosim.py smoke

gen:
	$(PY) cosim.py gen $(PASSES)

cosim-elab: gen
	$(PY) cosim.py elab

cosim: cosim-elab
	cd out && $(ESPICE) cosim.sp --format=csv --rawfile cosim.csv
	$(PY) cosim.py check $(PASSES)

clean:
	rm -rf out
