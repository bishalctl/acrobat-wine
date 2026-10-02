{ pkgs, mkAppImagePackage ? import ../appimage-package.nix }:
let
  lib = pkgs.lib;
  fixtureText = ''
    #!${pkgs.runtimeShell}
    if [[ "''${1:-}" == --exit ]]; then exit "$2"; fi
    if [[ "''${1:-}" == --wait ]]; then
      printf '%s\n' "$$" > "$ACROBAT_TEST_PIDFILE"
      exec ${pkgs.coreutils}/bin/sleep 300
    fi
    printf '%s\0' "$@"
  '';
  fixture = pkgs.writeTextFile {
    name = "acrobat-appimage-test-input";
    destination = "/an app's é 100%.AppImage";
    executable = true;
    text = fixtureText;
  };
  plain = pkgs.writeText "non-executable.AppImage" fixtureText;
  fixturePath = "${fixture}/an app's é 100%.AppImage";
  evaluate = settings: (import (pkgs.path + "/nixos/lib/eval-config.nix") {
    inherit pkgs;
    system = "x86_64-linux";
    modules = [
      ../../modules/acrobat-appimage.nix
      {
        boot.isContainer = true;
        system.stateVersion = "24.05";
        programs.acrobat-appimage = { enable = true; } // settings;
      }
    ];
  }).config;
  good = evaluate { appImage = fixturePath; sha256 = builtins.hashString "sha256" fixtureText; };
  direct = mkAppImagePackage {
    inherit pkgs;
    appImage = fixturePath;
    sha256 = builtins.hashString "sha256" fixtureText;
  };
  unpinned = evaluate { appImage = fixturePath; };
  missing = evaluate { appImage = "/nonexistent-acrobat-test/Acrobat.AppImage"; };
  notExecutable = evaluate { appImage = "${plain}"; };
  wrongHash = evaluate { appImage = fixturePath; sha256 = lib.concatStrings (lib.replicate 64 "0"); };
  relative = evaluate { appImage = "relative.AppImage"; };
  invalidHash = evaluate { appImage = fixturePath; sha256 = "not-a-sha256"; };
  disabled = (import (pkgs.path + "/nixos/lib/eval-config.nix") {
    inherit pkgs;
    system = "x86_64-linux";
    modules = [ ../../modules/acrobat-appimage.nix ];
  }).config;
  command = configuration: "${configuration.system.build.acrobat-appimage}/bin/acrobat-wine";
  commands = pkgs.writeText "acrobat-module-test-commands.json" (builtins.toJSON {
    good = command good;
    unpinned = command unpinned;
    missing = command missing;
    notExecutable = command notExecutable;
    wrongHash = command wrongHash;
    desktop = "${good.system.build.acrobat-appimage}/share/applications/acrobat-wine.desktop";
  });
in
assert lib.all (entry: entry.assertion) good.assertions;
assert direct.drvPath == good.system.build.acrobat-appimage.drvPath;
assert lib.any (entry: !entry.assertion && lib.hasInfix "absolute path string" entry.message) relative.assertions;
assert lib.any (entry: !entry.assertion && lib.hasInfix "hexadecimal SHA-256" entry.message) invalidHash.assertions;
assert !(disabled.system.build ? acrobat-appimage);
pkgs.runCommand "acrobat-appimage-module-check" {
  nativeBuildInputs = [ pkgs.python3 ];
} ''
  python3 ${./appimage_module.py} ${commands}
  touch "$out"
''
