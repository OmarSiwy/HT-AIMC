# LibreLane hardening of this digital top around its analog hard macro(s).
#
#   make config        regenerate config.yaml's macro block from ../macros.toml (checks ports first)
#   make harden        full Classic flow -> runs/harden/, views copied to ../../output/{gds,lef,nl,...}
#   make harden-smoke  self-checking end to end run on smoke/ (counter + dummy macro): port
#                      check, iverilog sim with the behavioural model, harden, signoff counts
#
# LibreLane comes from the nix shell (./env.sh digital), used as-is. It needs the
# sky130 build it pins (librelane/pdk_hashes.yaml, 8afc8346 for 3.0.14): the
# shell.nix volare pin (PDK_VERSION, fa87f8f4) is too old for it (no
# libs.tech/librelane, no KLAYOUT_DEF_LAYER_MAP). So LibreLane fetches its own pin
# with ciel into LL_PDK_ROOT, apart from ~/.volare.
# TODO: bump shell.nix PDK_VERSION to 8afc8346 (re-check the analog side), then set
# LL_PDK_ROOT=$(PDK_ROOT) so analog and digital share one PDK.

PDK ?= sky130A
LL_PDK_ROOT ?= $(HOME)/.ciel
LIBRELANE ?= librelane
LL = $(LIBRELANE) --pdk-root $(LL_PDK_ROOT) --pdk $(PDK)
MACROS_PY = ../macros.py
OUT ?= ../../output

SMOKE = smoke/build

.PHONY: config harden harden-smoke check-env clean

check-env:
	@command -v $(LIBRELANE) >/dev/null || { echo "librelane not on PATH: run ./env.sh digital"; exit 1; }

config:
	python3 $(MACROS_PY) config ../macros.toml config.yaml

harden: check-env config
	$(LL) --run-tag harden --overwrite --save-views-to $(OUT) config.yaml
	python3 $(MACROS_PY) signoff ../macros.toml runs/harden

harden-smoke: check-env
	rm -rf $(SMOKE) && mkdir -p $(SMOKE)
	klayout -b -r smoke/gen_dummy_macro.py -rd out=$(SMOKE)
	python3 $(MACROS_PY) check smoke/macros.toml
	iverilog -g2012 -o $(SMOKE)/tb.vvp smoke/tb_smoke_top.v smoke/smoke_top.v \
		$$(python3 $(MACROS_PY) sim smoke/macros.toml)
	vvp $(SMOKE)/tb.vvp | tee $(SMOKE)/sim.log
	grep -q '^PASS' $(SMOKE)/sim.log
	sed -e 's|@MODULE_NAME@|smoke_top|g' -e 's|@VERILOG_FILES@|dir::../smoke_top.v|g' \
		config.yaml.in > $(SMOKE)/config.yaml
	python3 $(MACROS_PY) config smoke/macros.toml $(SMOKE)/config.yaml
	$(LL) --run-tag smoke --overwrite $(SMOKE)/config.yaml
	python3 $(MACROS_PY) signoff smoke/macros.toml $(SMOKE)/runs/smoke

clean:
	rm -rf runs $(SMOKE)
