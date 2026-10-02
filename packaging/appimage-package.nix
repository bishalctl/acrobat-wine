{ pkgs, appImage, sha256 ? null, verifyEveryLaunch ? false }:
let
  lib = pkgs.lib;
  launcher = pkgs.writeShellApplication {
    name = "acrobat-wine";
    runtimeInputs = [ pkgs.coreutils pkgs.util-linux pkgs.libnotify ];
    text = ''
      image=${lib.escapeShellArg appImage}

      fail() {
        local status="$1"
        local message="$2"
        printf 'Acrobat: %s\n' "$message" >&2
        timeout 2s logger --tag acrobat-wine --priority user.err -- "$message" || true
        if [[ -n "''${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
          timeout 2s notify-send --app-name='Acrobat (Wine)' --icon=dialog-error \
            'Acrobat could not start' "$message" >/dev/null 2>&1 || true
        fi
        exit "$status"
      }

      [[ -f "$image" && -r "$image" ]] || \
        fail 127 "Download the private AppImage to: $image"
      if [[ ! -x "$image" ]]; then
        printf -v executable_hint 'chmod +x -- %q' "$image"
        fail 126 "The AppImage needs executable permission. Run: $executable_hint"
      fi
      ${lib.optionalString (sha256 != null) ''
        if ! verification_error=$(${pkgs.python3}/bin/python3 ${./verify_appimage.py} \
            "$image" ${lib.escapeShellArg sha256} ${lib.optionalString verifyEveryLaunch "--always"} 2>&1); then
          fail 1 "$verification_error"
        fi
      ''}

      # The configured file is independent of the packaging checkout.
      exec "$image" "$@"
    '';
  };
  desktop = pkgs.makeDesktopItem {
    name = "acrobat-wine";
    desktopName = "Acrobat (Wine)";
    comment = "View and edit PDF documents";
    exec = "${launcher}/bin/acrobat-wine %F";
    tryExec = "${launcher}/bin/acrobat-wine";
    icon = "application-pdf";
    terminal = false;
    categories = [ "Office" "Viewer" ];
    mimeTypes = [ "application/pdf" ];
    startupWMClass = "acrobat.exe";
    startupNotify = false;
  };
in
assert lib.assertMsg (pkgs.stdenv.hostPlatform.system == "x86_64-linux")
  "The Acrobat AppImage requires x86_64 Linux.";
assert lib.assertMsg (builtins.isString appImage && lib.hasPrefix "/" appImage)
  "mkAppImagePackage.appImage must be a quoted absolute path string.";
assert lib.assertMsg (sha256 == null || (builtins.isString sha256 && builtins.match "[0-9a-f]{64}" sha256 != null))
  "mkAppImagePackage.sha256 must be a lowercase hexadecimal SHA-256 checksum.";
pkgs.symlinkJoin {
  name = "acrobat-appimage-launcher";
  paths = [ launcher desktop ];
  meta = {
    description = "Desktop integration for a local Acrobat AppImage";
    mainProgram = "acrobat-wine";
    platforms = [ "x86_64-linux" ];
  };
}
