#! /usr/bin/env bash
# Copyright (c) 2025, Tomasz Pakuła Using Arch BTW

PREFIX=""
if [[ $1 == "add-prefix" ]]; then
    PREFIX="$2"
fi

# uninstall foxblat
if [[ $1 == "remove" || $3 == "remove" ]]; then
    rm "$PREFIX/usr/share/applications/"*foxblat.desktop
    rm "$PREFIX/usr/bin/foxblat"
    rm "$PREFIX/usr/share/metainfo/"*foxblat*
    rm -rf "$PREFIX/usr/share/foxblat"
    cp -r ./icons/* "$PREFIX/usr/share/icons/hicolor/"
    rm "$PREFIX/usr/lib/udev/rules.d/"*foxblat*.rules
    exit 0
fi

if [[ -n $PREFIX ]]; then
    mkdir -p "$PREFIX/usr/lib/udev/rules.d"
    mkdir -p "$PREFIX/usr/bin"
    mkdir -p "$PREFIX/usr/share/applications"
fi

mkdir -p "$PREFIX/usr/share/foxblat"
mkdir -p "$PREFIX/usr/share/metainfo"
mkdir -p "$PREFIX/usr/share/icons/hicolor/"

cp -r ./foxblat "$PREFIX/usr/share/foxblat/"
cp -r ./data "$PREFIX/usr/share/foxblat/"
cp -r ./icons/* "$PREFIX/usr/share/icons/hicolor/"
cp -r ./udev "$PREFIX/usr/share/foxblat/"
cp entrypoint.py "$PREFIX/usr/share/foxblat/"
cp ./*metainfo.xml "$PREFIX/usr/share/metainfo/"

cp --preserve=mode "foxblat.sh" "$PREFIX/usr/bin/foxblat"
cp ./*.desktop "$PREFIX/usr/share/applications/"
cp udev/* "$PREFIX/usr/lib/udev/rules.d/"

# refresh udev so the rules take effect immadietely
if [[ $1 == "no-udev" || $3 == "no-udev" ]]; then
    exit 0
fi

udevadm control --reload
udevadm trigger --attr-match=subsystem=tty
