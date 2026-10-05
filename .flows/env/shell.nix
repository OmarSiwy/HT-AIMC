{
  type ? "mixed",
  pkgs ?
    import (builtins.fetchTarball "https://github.com/NixOS/nixpkgs/archive/nixos-25.11.tar.gz")
      { },
}:
let
  # Everything the template needs that nixpkgs does not carry, prebuilt and cached:
  # cktimg and spicerack (built there because nothing else caches them) plus VLSI netgen
  # (re-exported from nix-eda — `pkgs.netgen` is an unrelated 3D mesh generator).
  # Run `cachix use omarsiwy` first, or these compile locally.
  eda = builtins.getFlake "github:OmarSiwy/EDA-Packaged";
  # LibreLane: not in nixpkgs 25.11. Pinned to a release tag; its binary cache is
  # https://nix-cache.fossi-foundation.org (env.sh passes it), else openroad builds locally.
  # PDK_VERSION below is LibreLane 3.0.14's sky130 pin (8afc8346), so analog and
  # digital share one PDK under ~/.ciel.
  librelane = builtins.getFlake "github:librelane/librelane/3.0.14";
  analog = import ./Analog.nix { inherit pkgs eda; };
  digital = import ./Digital.nix { inherit pkgs librelane; };

  useAnalog = type == "analog" || type == "mixed";
  useDigital = type == "digital" || type == "mixed";

  commonPackages = with pkgs; [
    # Builds
    gnumake
    librelane.inputs.ciel.packages.${pkgs.system}.ciel  # PDK manager (volare successor), the one LibreLane uses
    git
    gh
    python312
    ccache

    # C compilation dependencies
    gcc
    clang
    llvmPackages.libclang
    libffi.dev
    fftw

    # Python deps
    python312Packages.pip
    python312Packages.numpy
    python312Packages.setuptools
    python312Packages.wheel

    # Graphics/GUI support
    xorg.libX11
    xorg.libXpm
    xorg.libXt
    cairo
    xterm
    xorg.fontutil
    xorg.fontmiscmisc
    xorg.fontcursormisc
    dejavu_fonts
    liberation_ttf
    inkscape
    vim

    # Viewing docs locally
    bun
  ];

in
pkgs.mkShell {
  name = "eda-env";

  buildInputs =
    commonPackages
    ++ (if useAnalog then analog.packages else [ ])
    ++ (if useDigital then digital.packages else [ ]);

  env = {
    NIX_ENFORCE_PURITY = "0";
  };

  shellHook = ''
    export PROJECT_ROOT="$(pwd)"

    # === Environment Variables Setup ===
    export CC="ccache gcc"
    export CXX="ccache g++"
    export CCACHE_DIR="$PROJECT_ROOT/.tools/ccache"

    # === PDK Configuration ===
    export PDK="sky130A"
    export PDK_VERSION="8afc8346a57fe1ab7934ba5a6056ea8b43078e71"  # = LibreLane 3.0.14 pin
    export PDK_ROOT="$HOME/.ciel"

    # === Python Dependencies Installation ===
    export VENV_DIR="$PROJECT_ROOT/.venv"
    if [ -z "$VIRTUAL_ENV" ] || [ "$VIRTUAL_ENV" != "$VENV_DIR" ]; then
      if [ ! -d "$VENV_DIR" ]; then
        echo "Creating Python virtual environment..."
        python3 -m venv "$VENV_DIR"
      fi
      source "$VENV_DIR/bin/activate"
    fi

    pip install --upgrade pip==24.2 setuptools==75.1.0 wheel==0.44.0 >/dev/null 2>&1

    # === PDK SETUP WITH CIEL (nixpkgs; same store LibreLane uses) ===
    # Downloads $PDK_VERSION once and points $PDK_ROOT/$PDK at it. Other versions are left alone.
    ciel enable --pdk-root "$PDK_ROOT" --pdk-family sky130 "$PDK_VERSION" >/dev/null \
      || echo "WARNING: ciel could not enable sky130 $PDK_VERSION in $PDK_ROOT"

    # === Mode Specific Hooks ===
    ${if useAnalog then analog.shellHook else ""}
    ${if useDigital then digital.shellHook else ""}

    echo "=== EDA Environment ==="
    echo "Mode: ${type}"
    echo ""
    echo "System tools available:"
    echo "  - Python: $(python --version)"

    if [ "${type}" = "analog" ] || [ "${type}" = "mixed" ]; then
      echo "  - xschem: $(xschem --version 2>/dev/null | head -n 1 || echo 'custom build')"
      echo "  - magic: $(magic --version 2>/dev/null || echo 'from nixpkgs')"
      echo "  - cktimg-json: $(command -v cktimg-json >/dev/null && echo ok || echo 'not found')"
      echo "  - spicerack: $(python -c 'import spicerack' 2>/dev/null && echo ok || echo 'not found')"
      echo "  - espice: $(command -v espice >/dev/null && echo ok || echo 'not found')"
    fi

    if [ "${type}" = "digital" ] || [ "${type}" = "mixed" ]; then
      echo "  - yosys: $(yosys -V 2>/dev/null | head -1 || echo 'not found')"
      echo "  - verilator: $(verilator --version 2>/dev/null | head -1 || echo 'not found')"
      echo "  - openroad: $(openroad -version 2>/dev/null | head -1 || echo 'not found')"
      echo "  - librelane: $(librelane --version 2>/dev/null || echo 'not found')"
    fi

    echo "  - PDK: $PDK in $PDK_ROOT"
    echo ""
  '';
}
