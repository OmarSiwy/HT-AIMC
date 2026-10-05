{
  pkgs,
  eda,
}:
let
  edaPkgs = eda.packages.${pkgs.system};
  cktimgPkg = edaPkgs.cktimg;
  spicerackPkg = edaPkgs.spicerack;
  philisPkg = edaPkgs.philis;
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
    pkgs.magic-vlsi

    # Netlist-first flow. cktimgPkg ships `cktimg-json`, which .flows/tools/
    # cktimg_to_xschem.py shells out to; spicerackPkg is a Python package and is reached
    # through PYTHONPATH below rather than by landing a binary on PATH.
    cktimgPkg
    spicerackPkg

    # Design-flow tools (analog-design-flow skill):
    #  - philis: automated P&R + in-loop DRC/LVS/PEX (layout rung); rule decks under
    #    share/philis/pdks, exported as PHILIS_PDK_DIR below
    #  - espice: THE simulator (SpiceRack backend `espice`). Golden models (Verilog-A)
    #    compile through VerA at first use (`.hdl`, cache in ~/.cache/espice). No OSDI.
    #  - vera: Verilog-A lint/check/--emit-verilog; ships its contract.zig (VERA_CONTRACT)
    philisPkg
    edaPkgs.espice
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
    export VERA_CONTRACT="${edaPkgs.vera}/share/vera/contract.zig"

    # === Analog Tools Configuration ===
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
