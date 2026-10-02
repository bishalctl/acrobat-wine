#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "$(realpath -- "$0")")/.." && pwd)"
cd -- "$root"
export XDG_CACHE_HOME="$root/state/cache"
export XDG_CONFIG_HOME="$root/state/config"
mkdir -p "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$root/dist"
target="${1:-all}"
case "$target" in
    all|nix|appimage|check) ;;
    *) printf 'Usage: %s [all|nix|appimage|check]\n' "$0" >&2; exit 2 ;;
esac
if [[ "$target" == check ]]; then
    stage="$(python3 "$root/packaging/stage-source.py" --source-only)"
    nix flake check "path:$stage" --cores 2 --max-jobs 2 \
        --option substituters https://cache.nixos.org
    exit 0
fi
stage="$(python3 "$root/packaging/stage-source.py")"
case "$target" in
    nix|all)
        nix build "path:$stage#acrobat" --out-link "$root/dist/nix-package" \
            --cores 2 --max-jobs 2 --option substituters https://cache.nixos.org
        ;;
    appimage) ;;
esac
if [[ "$target" == appimage || "$target" == all ]]; then
    image="$(nix build "path:$stage#appimage" --no-link --print-out-paths \
        --cores 2 --max-jobs 2 --option substituters https://cache.nixos.org)"
    cp --reflink=auto -- "$image" "$root/dist/.Acrobat.AppImage.partial"
    chmod 755 "$root/dist/.Acrobat.AppImage.partial"
    mv -f -- "$root/dist/.Acrobat.AppImage.partial" "$root/dist/Acrobat-26.002.21931-x86_64.AppImage"
    (cd "$root/dist" && sha256sum Acrobat-26.002.21931-x86_64.AppImage > SHA256SUMS)
fi
if [[ -f "$stage/flake.lock" ]]; then
    cp -- "$stage/flake.lock" "$root/flake.lock"
fi
# A real directory is necessary: path flakes cannot follow a root symlink out
# of their source tree in pure evaluation. Keep any previous export intact.
if [[ -L "$root/dist/flake" ]]; then
    rm -- "$root/dist/flake"
elif [[ -d "$root/dist/flake" ]]; then
    previous="$(mktemp -d "$root/state/build/previous-flake-XXXXXXXX")"
    mv -- "$root/dist/flake" "$previous/flake"
elif [[ -e "$root/dist/flake" ]]; then
    printf 'Cannot publish the flake over a non-directory: %s\n' "$root/dist/flake" >&2
    exit 1
fi
mv -- "$stage" "$root/dist/flake"
printf '%s\n' "$root/dist/flake" > "$root/state/package-source-path"
