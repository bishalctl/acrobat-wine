{ pkgs }:
assert pkgs.wineWow64Packages.staging.version == "11.18";
pkgs.buildEnv {
  name = "acrobat-prefix-setup-tools";
  paths = [
    pkgs.wineWow64Packages.staging
    pkgs.winetricks
    pkgs.p7zip
    pkgs.cabextract
    pkgs.pkgsCross.mingwW64.stdenv.cc
    pkgs.python3
    pkgs.curl
    pkgs.unzip
    pkgs.zstd
    pkgs.ripgrep
    pkgs.coreutils
    pkgs.util-linux
  ];
  pathsToLink = [ "/bin" ];
}
