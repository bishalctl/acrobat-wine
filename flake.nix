{
  description = "Acrobat on Wine — AppImage and Nix packaging for v26.2.21931 x64 Multilingual";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/7a0f122f5090cf4c2ade2a13a0e229d4e19ba71f";
    appimage-src = {
      url = "github:ralismark/nix-appimage/7946addbc0d97e358a6d7aefe5e82310f0fe6b18";
      flake = false;
    };
  };
  outputs = { self, nixpkgs, appimage-src }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
      mkAppImagePackage = import ./packaging/appimage-package.nix;
      payload = ./packaging + "/payload";
      hasPayload = builtins.all (name: builtins.pathExists (payload + "/${name}")) [
        "manifest.json" "prefix.tar.zst" "Adobe.Acrobat.2026.u17.x64.Multilingual.iso"
      ];
      wineRuntime = import ./packaging/wine-runtime.nix { inherit pkgs; };
      package = import ./packaging/package.nix { inherit pkgs wineRuntime payload; };
      static = pkgs.pkgsStatic;
      runtime = static.callPackage (appimage-src + "/runtimes/appimage-type2-runtime") { };
      apprun = static.stdenv.mkDerivation {
        name = "acrobat-appimage-apprun";
        dontUnpack = true;
        buildPhase = ''
          $CC -std=gnu11 -Os -Wall -Wextra -Werror -static ${./packaging/AppRun.c} -o AppRun
        '';
        installPhase = ''
          mkdir -p "$out/mountroot"
          cp AppRun "$out/AppRun"
          cp ${pkgs.closureInfo { rootPaths = [ package ]; }}/store-paths "$out/closure.txt"
        '';
      };
      mkAppImage = pkgs.callPackage (appimage-src + "/mkAppImage.nix") {
        mkappimage-runtime = runtime;
        mkappimage-apprun = apprun;
      };
    in {
      lib.mkAppImagePackage = mkAppImagePackage;
      packages.${system} = {
        wine = wineRuntime;
        appimage-runtime = runtime;
      } // pkgs.lib.optionalAttrs hasPayload {
        default = package;
        acrobat = package;
        appimage = mkAppImage {
          program = "${package}/bin/acrobat-wine";
          pname = "Acrobat-26.002.21931-x86_64";
          squashfsArgs = [ "-comp zstd" "-Xcompression-level 10" "-processors 2" "-mem 512M" ];
        };
      };
      apps.${system} = pkgs.lib.optionalAttrs hasPayload {
        default = {
          type = "app";
          program = "${package}/bin/acrobat-wine";
          meta.description = "Acrobat v26.2.21931 x64 Multilingual with Wine";
        };
      };
      nixosModules.default = { config, lib, ... }: {
        options.programs.acrobat-wine.enable = lib.mkEnableOption "the personal Acrobat on Wine bundle";
        config = lib.mkIf config.programs.acrobat-wine.enable {
          assertions = [{
            assertion = hasPayload;
            message = "This native bundle module needs the prepared private payload. For an external AppImage, use lib.mkAppImagePackage or nixosModules.appimage described in docs/packaging.md.";
          }];
          environment.systemPackages = lib.optional hasPayload package;
        };
      };
      nixosModules.appimage = import ./modules/acrobat-appimage.nix;
      checks.${system} = {
        appimage-module = import ./packaging/tests/appimage-module.nix { inherit pkgs mkAppImagePackage; };
        launcher = pkgs.runCommand "acrobat-launcher-check" {
          nativeBuildInputs = [ (pkgs.python3.withPackages (p: [ p.dbus-next ])) pkgs.dbus ];
        } ''
          cp -r ${./packaging/tests} tests
          chmod -R u+w tests
          cp ${./packaging/launcher.py} tests/launcher.py
          cp ${./packaging/native_file_chooser.py} tests/native_file_chooser.py
          cp ${./packaging/export-profile.py} tests/export-profile.py
          cp ${./scripts/supervise.py} tests/supervise.py
          cp ${./scripts/host_files.py} tests/host_files.py
          cp ${./packaging/source_tree.py} tests/source_tree.py
          cd tests
          python3 -m unittest -v
          touch "$out"
        '';
      };
      formatter.${system} = pkgs.nixfmt;
    };
}
