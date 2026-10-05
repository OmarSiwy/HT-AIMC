# sysreference PPA flow on ASAP7 (OpenROAD-flow-scripts asap7 platform).
# Tools from nix (python first so its pyyaml wins on PATH):
#   nix-shell -p 'python3.withPackages(p:[p.pyyaml p.numpy])' openroad yosys klayout \
#             iverilog gnumake time --run 'make -C build ppa'
#
#   make orfs-fetch               sparse clone of ORFS at the tag matching nixpkgs OpenROAD
#                                 (run once; the other targets expect $(ORFS) to exist)
#   make synth                    yosys + ASAP7 TT liberty sweep -> out/synth/*.json
#   make harden SIZE=16 PERIOD_PS=330   ORFS full flow (synth..route, finish)
#   make power  SIZE=16           gate-level GEMM VCD -> OpenROAD report_power
#   make ppa                      collect everything -> ../ppa.json
SIZE      ?= 16
PERIOD_PS ?= 400
ORFS_TAG  := 26Q2
ORFS      ?= $(CURDIR)/orfs/ORFS
FLOW      := $(ORFS)/flow
WORK      := $(CURDIR)/orfs/work
OUT       := $(CURDIR)/out
SYSREF    := $(abspath $(CURDIR)/..)
ORFS_MAKE  = $(MAKE) -C $(FLOW) DESIGN_CONFIG=$(CURDIR)/flow/config.mk \
             WORK_HOME=$(WORK) SIZE=$(SIZE)

.PHONY: orfs-fetch synth harden power ppa

orfs-fetch:
	test -d $(ORFS) || sh fetch_orfs.sh $(ORFS_TAG) $(ORFS)

synth:
	mkdir -p $(OUT)/synth
	python3 synth_sweep.py $(FLOW)/platforms/asap7 $(OUT)/synth

harden:
	mkdir -p $(WORK)
	sed 's/@PERIOD_PS@/$(PERIOD_PS)/' flow/constraint.sdc > $(WORK)/sa_top_$(SIZE).sdc
	$(ORFS_MAKE) clean_all
	$(ORFS_MAKE) finish

power:
	python3 power.py $(SIZE) $(FLOW) $(WORK) $(OUT)/power

ppa:
	python3 ppa.py $(OUT) $(WORK) $(SYSREF)/ppa.json
