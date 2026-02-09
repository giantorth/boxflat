#! /usr/bin/env sh
# Copyright (c) 2025, Tomasz Pakuła Using Arch BTW

COMMAND="python3 /usr/share/foxblat/entrypoint.py"

if [ "$FLATPAK_ID" = "io.github.lawstorant.foxblat" ]; then
    COMMAND="python3 /app/share/foxblat/entrypoint.py --flatpak"
fi

$COMMAND "$@"
