# sysreference synthesis on ASAP7: yosys + ASAP7 RVT TT liberty -> out/synth/*.json.
# Hardening goes through LibreLane (same flow family as digital/analogioc/build/librelane),
# not OpenROAD-flow-scripts. Tools from nix:
#   nix-shell -p 'python3.withPackages(p:[p.numpy])' yosys --run 'make -C build synth LIB_DIR=...'
# LIB_DIR: a directory holding asap7sc7p5t_{AO,INVBUF,OA,SIMPLE,SEQ}_RVT_TT_nldm_*.lib[.gz]
# (flat, or under lib/NLDM/).
LIB_DIR ?= $(error set LIB_DIR to an ASAP7 asap7sc7p5t liberty directory)
OUT     := $(CURDIR)/out

.PHONY: synth

synth:
	mkdir -p $(OUT)/synth
	python3 synth_sweep.py $(LIB_DIR) $(OUT)/synth
