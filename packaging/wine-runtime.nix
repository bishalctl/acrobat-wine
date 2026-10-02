{ pkgs }:
let
  base = pkgs.wineWow64Packages.staging;
  compatibility = base.overrideAttrs (old: {
    pname = "acrobat-wine-compatibility";
    patches = (old.patches or [ ]) ++ [
      ../scripts/wine-compat/crypt32-force-close.patch
      ../scripts/wine-compat/native-file-dialog.patch
    ];
    postPatch = (old.postPatch or "") + ''
      cp ${../scripts/wine-compat/native-file-dialog.h} dlls/comdlg32/acrobat_native_dialog.h
    '';
    buildPhase = ''
      runHook preBuild
      make -j"$NIX_BUILD_CORES" dlls/crypt32/x86_64-windows/crypt32.dll \
        dlls/comdlg32/x86_64-windows/comdlg32.dll
      runHook postBuild
    '';
    installPhase = ''
      mkdir -p "$out/lib/wine/x86_64-windows"
      cp dlls/crypt32/x86_64-windows/crypt32.dll "$out/lib/wine/x86_64-windows/"
      cp dlls/comdlg32/x86_64-windows/comdlg32.dll "$out/lib/wine/x86_64-windows/"
      mkdir -p "$out/share/doc/acrobat-wine-compatibility"
      cp COPYING.LIB "$out/share/doc/acrobat-wine-compatibility/"
    '';
    postInstall = "";
    doCheck = false;
    doInstallCheck = false;
  });
  x11Compatibility = base.overrideAttrs (old: {
    pname = "acrobat-wine-x11-popup";
    patches = (old.patches or [ ]) ++ [ ../scripts/wine-compat/acrobat-popup.patch ];
    buildPhase = ''
      runHook preBuild
      make -j"$NIX_BUILD_CORES" dlls/winex11.drv/winex11.so
      runHook postBuild
    '';
    installPhase = ''
      mkdir -p "$out/lib/wine/x86_64-unix" "$out/share/doc/acrobat-wine-x11-popup"
      cp dlls/winex11.drv/winex11.so "$out/lib/wine/x86_64-unix/"
      cp COPYING.LIB "$out/share/doc/acrobat-wine-x11-popup/"
    '';
    postInstall = "";
    doCheck = false;
    doInstallCheck = false;
  });
in
assert base.version == "11.18";
pkgs.runCommand "acrobat-wine-runtime-11.18" { } ''
  mkdir -p "$out"
  cp -rs --no-preserve=mode ${base}/. "$out/"
  for file in lib/wine/x86_64-unix/wine lib/wine/x86_64-unix/wine-preloader lib/wine/x86_64-unix/ntdll.so; do
    cp --remove-destination ${base}/"$file" "$out/$file"
  done
  ln -sfn ../lib/wine/x86_64-unix/wine "$out/bin/wine"
  for tool in wineboot winecfg winepath winedbg wineconsole msiexec regedit regsvr32 notepad; do
    ln -sfn wine "$out/bin/$tool"
  done
  for dll in crypt32 comdlg32; do
    cp --remove-destination ${compatibility}/lib/wine/x86_64-windows/"$dll.dll" \
      "$out/lib/wine/x86_64-windows/$dll.dll"
  done
  cp --remove-destination ${x11Compatibility}/lib/wine/x86_64-unix/winex11.so \
    "$out/lib/wine/x86_64-unix/winex11.so"
''
