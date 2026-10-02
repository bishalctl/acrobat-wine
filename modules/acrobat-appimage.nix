{ config, lib, pkgs, ... }:
let
  cfg = config.programs.acrobat-appimage;
  package = import ../packaging/appimage-package.nix {
    inherit pkgs;
    inherit (cfg) appImage sha256 verifyEveryLaunch;
  };
in {
  options.programs.acrobat-appimage = {
    enable = lib.mkEnableOption "Acrobat from a locally downloaded AppImage";
    appImage = lib.mkOption {
      type = lib.types.str;
      example = "/etc/nixos/local/acrobat/Acrobat.AppImage";
      description = ''
        Absolute runtime path to the private AppImage. Keep this a quoted string:
        a Nix path literal would try to import the ignored binary during evaluation.
        Set this explicitly in the consuming system configuration. The file is needed
        at launch, so system builds also work before downloading it. The installed
        launcher does not depend on a local checkout of the packaging repository.
      '';
    };
    sha256 = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Optional SHA-256 checksum as 64 lowercase hexadecimal characters.
        Successful verification is cached per user until the file identity,
        size, modification time, change time, or configured checksum changes.
      '';
    };
    verifyEveryLaunch = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Recompute the configured SHA-256 on every launch instead of using the
        metadata cache. This rereads the entire AppImage for each PDF opened.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.hostPlatform.system == "x86_64-linux";
        message = "The Acrobat AppImage requires x86_64 Linux.";
      }
      {
        assertion = lib.hasPrefix "/" cfg.appImage;
        message = "programs.acrobat-appimage.appImage must be an absolute path string.";
      }
      {
        assertion = cfg.sha256 == null || builtins.match "[0-9a-f]{64}" cfg.sha256 != null;
        message = "programs.acrobat-appimage.sha256 must be a lowercase hexadecimal SHA-256 checksum.";
      }
    ];
    environment.systemPackages = [ package ];
    system.build.acrobat-appimage = package;
  };
}
