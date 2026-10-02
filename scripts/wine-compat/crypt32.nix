{ baseOnly ? false }:
let
  source = builtins.getFlake "github:NixOS/nixpkgs/7a0f122f5090cf4c2ade2a13a0e229d4e19ba71f";
  pkgs = import source.outPath { system = "x86_64-linux"; };
  base = pkgs.wineWow64Packages.staging;
in if baseOnly then base else base.overrideAttrs (old: {
  pname = "acrobat-wine-crypt32";
  patches = (old.patches or []) ++ [ ./crypt32-force-close.patch ];
  buildPhase = ''
    runHook preBuild
    make -j"$NIX_BUILD_CORES" dlls/crypt32/x86_64-windows/crypt32.dll
    runHook postBuild
  '';
  installPhase = ''
    mkdir -p "$out/lib/wine/x86_64-windows"
    cp dlls/crypt32/x86_64-windows/crypt32.dll "$out/lib/wine/x86_64-windows/"
    mkdir -p "$out/share/doc/acrobat-wine-crypt32"
    cp COPYING.LIB "$out/share/doc/acrobat-wine-crypt32/"
  '';
  postInstall = "";
  doCheck = false;
  doInstallCheck = false;
})
