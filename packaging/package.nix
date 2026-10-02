{ pkgs, wineRuntime, payload ? ./payload }:
let
  manifest = builtins.fromJSON (builtins.readFile (payload + "/manifest.json"));
  content = builtins.path {
    path = payload;
    name = "acrobat-personal-payload";
    filter = path: type: type == "directory" || builtins.elem (baseNameOf path)
      [ "manifest.json" "prefix.tar.zst" "Adobe.Acrobat.2026.u17.x64.Multilingual.iso" ];
  };
  icon = ./acrobat-wine.svg;
  python = pkgs.python3.withPackages (p: [ p.dbus-next ]);
in pkgs.stdenvNoCC.mkDerivation {
  pname = "acrobat-wine";
  version = manifest.application_version;
  dontUnpack = true;
  nativeBuildInputs = [ pkgs.makeWrapper pkgs.desktop-file-utils ];
  installPhase = ''
    mkdir -p "$out/libexec/acrobat-wine" "$out/bin" \
      "$out/share/applications" "$out/share/icons/hicolor/scalable/apps"
    cp ${./launcher.py} "$out/libexec/acrobat-wine/launcher.py"
    cp ${./native_file_chooser.py} "$out/libexec/acrobat-wine/native_file_chooser.py"
    cp ${../scripts/supervise.py} "$out/libexec/acrobat-wine/supervise.py"
    cp ${../scripts/host_files.py} "$out/libexec/acrobat-wine/host_files.py"
    cat > "$out/libexec/acrobat-wine/runtime.json" <<'EOF'
    ${builtins.toJSON {
      version = manifest.application_version;
      wine_version = manifest.wine_version;
      wine = "${wineRuntime}/bin/wine";
      wineserver = "${wineRuntime}/bin/wineserver";
      zstd = "${pkgs.zstd}/bin/zstd";
      archive = "${content}/prefix.tar.zst";
      manifest = "${content}/manifest.json";
      iso = "${content}/Adobe.Acrobat.2026.u17.x64.Multilingual.iso";
    }}
    EOF
    makeWrapper ${python}/bin/python3 "$out/bin/acrobat-wine" \
      --add-flags "$out/libexec/acrobat-wine/launcher.py"
    install -m644 ${icon} "$out/share/icons/hicolor/scalable/apps/acrobat-wine.svg"
    install -Dm644 ${./Selawik-LICENSE.txt} "$out/share/licenses/acrobat-wine/Selawik.txt"
    cat > "$out/share/applications/acrobat-wine.desktop" <<EOF
    [Desktop Entry]
    Type=Application
    Name=Acrobat (Wine)
    Comment=v26.2.21931 x64 Multilingual — experimental Wine package
    Exec=$out/bin/acrobat-wine %F
    Icon=acrobat-wine
    Terminal=false
    Categories=Office;Viewer;
    MimeType=application/pdf;
    StartupWMClass=acrobat.exe
    StartupNotify=false
    EOF
    desktop-file-validate "$out/share/applications/acrobat-wine.desktop"
  '';
  meta = {
    description = "Acrobat v26.2.21931 x64 Multilingual — personal Wine bundle";
    mainProgram = "acrobat-wine";
    platforms = [ "x86_64-linux" ];
    license = pkgs.lib.licenses.unfree;
  };
}
