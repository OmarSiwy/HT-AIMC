{
  pkgs,
  eda,
}:
let
  edaPkgs = eda.packages.${pkgs.system};
  cktimgPkg = edaPkgs.cktimg;
  spicerackPkg = edaPkgs.spicerack;
  philisPkg = edaPkgs.philis;
  # OpenVAF (Verilog-A -> OSDI for ngspice) installs as `openvaf-r`; SpiceRack's
  # `veriloga()` and build/va call plain `openvaf`, so expose both names.
  openvafPkg = pkgs.runCommand "openvaf-alias" { } ''
    mkdir -p $out/bin
    ln -s ${edaPkgs.openvaf}/bin/openvaf-r $out/bin/openvaf-r
    ln -s ${edaPkgs.openvaf}/bin/openvaf-r $out/bin/openvaf
  '';
  # The shared-library build of ngspice. The Rust analog crates link against it, which
  # plain `ngspice` (a binary only) cannot satisfy.
  ngspiceShared = pkgs.libngspice;
in
{
  packages = [
    # EDA tools, straight from nixpkgs.
    pkgs.xschem
    pkgs.klayout
    # The VLSI LVS tool. NOT `pkgs.netgen`, which is a 3D tetrahedral mesh generator from
    # ngsolve.org that shares nothing with this but a name — nixpkgs has no VLSI netgen
    # under any attribute, which is why it comes through the EDA-Packaged pin.
    edaPkgs.netgen
    ngspiceShared
    pkgs.ngspice
    pkgs.magic-vlsi

    # Netlist-first flow. cktimgPkg ships `cktimg-json`, which .flows/tools/
    # cktimg_to_xschem.py shells out to; spicerackPkg is a Python package and is reached
    # through PYTHONPATH below rather than by landing a binary on PATH.
    cktimgPkg
    spicerackPkg

    # Design-flow tools (analog-design-flow skill):
    #  - philis: automated P&R + in-loop DRC/LVS/PEX (layout rung); rule decks under
    #    share/philis/pdks, exported as PHILIS_PDK_DIR below
    #  - openvaf: golden models (Verilog-A) -> OSDI for ngspice (DUT=va)
    #  - vera: Verilog-A lint/check. --check/--run need contract.zig from the SAME VerA
    #    commit: taken from the package (share/vera/, once VerA ships it) or from a
    #    VerA checkout in VERA_SRC; exported as VERA_CONTRACT below.
    #  - espice: NOT installed from the store — its `.hdl` loader writes a build cache into
    #    its own source tree (AccessDenied in /nix/store). Set ESPICE_SRC to a local
    #    ESPice/ARPice checkout built with `zig build -Doptimize=ReleaseFast`.
    philisPkg
    openvafPkg
    edaPkgs.vera
    # gm/ID lookup library for analog/docs/gmid.py (ctypes via GMID_LIB)
    edaPkgs.gmidvisualizer

    # Rust toolchain from nixpkgs (+ protoc: the substrate2 `cache` crate compiles
    # protobufs at build time — analog/common/layout generators need it)
    pkgs.protobuf
    pkgs.cargo
    pkgs.rustc
    pkgs.rust-analyzer
    pkgs.rustfmt
    pkgs.clippy
  ];
  shellHook = ''
    # === Design-flow tools ===
    export PHILIS_PDK_DIR="${philisPkg}/share/philis/pdks"
    export GMID_LIB="${edaPkgs.gmidvisualizer}/lib/libGmIDVisualizer.so"
    # contract.zig must come from the same VerA commit as the binary (ABI check)
    if [ -f "${edaPkgs.vera}/share/vera/contract.zig" ]; then
      export VERA_CONTRACT="${edaPkgs.vera}/share/vera/contract.zig"
    elif [ -n "$VERA_SRC" ] && [ -f "$VERA_SRC/tools/contract.zig" ]; then
      export VERA_CONTRACT="$VERA_SRC/tools/contract.zig"
    fi
    if [ -n "$ESPICE_SRC" ] && [ -x "$ESPICE_SRC/zig-out/bin/espice" ]; then
      export PATH="$ESPICE_SRC/zig-out/bin:$PATH"
    fi

    # === Analog Tools Configuration ===
    export BINDGEN_EXTRA_CLANG_ARGS="-I${ngspiceShared}/include $BINDGEN_EXTRA_CLANG_ARGS"
    export CPATH="${ngspiceShared}/include:$CPATH"
    export NIX_LD_LIBRARY_PATH="${ngspiceShared}/lib:$NIX_LD_LIBRARY_PATH"
    export PKG_CONFIG_PATH="${ngspiceShared}/lib/pkgconfig:$PKG_CONFIG_PATH"
    export KLAYOUT_PATH="$PDK_ROOT/$PDK/libs.tech/klayout"
    export XSCHEM_USER_LIBRARY_PATH="$PDK_ROOT/$PDK/libs.tech/xschem"
    export XSCHEM_LIBRARY_PATH="$PDK_ROOT/$PDK/libs.tech/xschem:${pkgs.xschem}/share/xschem/xschem_library"

    # === Rust Build Config ===
    export LIBCLANG_PATH="${pkgs.llvmPackages.libclang.lib}/lib"
    export BINDGEN_EXTRA_CLANG_ARGS="-I${pkgs.glibc.dev}/include $BINDGEN_EXTRA_CLANG_ARGS"
    export CPATH="${pkgs.python312}/include/python3.12:$CPATH"
    export NIX_LD_LIBRARY_PATH="${pkgs.python312}/lib:$NIX_LD_LIBRARY_PATH"

    # === Analog Python Libraries ===
    # spicerack is a nix-built Python package, and the venv shell.nix creates does not
    # inherit system site-packages, so PYTHONPATH is what makes `import spicerack`
    # resolve inside it. Prepended, not appended: the venv must not shadow it with a
    # half-built copy from a previous `maturin develop`.
    export PYTHONPATH="${spicerackPkg}/${pkgs.python312.sitePackages}:$PYTHONPATH"

    pip install maturin pytest
    for pkg in analog/library/dep_library/gmid analog/library/dep_library/UWASIC-ALG; do
        if [ -d "$PROJECT_ROOT/$pkg" ]; then
            echo "Installing editable package: $pkg"
            python -m pip install -e "$PROJECT_ROOT/$pkg"
        fi
    done
  '';
}
