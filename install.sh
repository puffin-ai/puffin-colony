#!/bin/sh
# Install Puffin Colony: uv when it is missing (with Astral's official installer), then the `colony` command.
#   curl -LsSf https://raw.githubusercontent.com/puffin-ai/puffin-colony/main/install.sh | sh
set -eu

if ! command -v uv >/dev/null 2>&1; then
    echo "Puffin Colony runs with uv, which is not installed. Installing it now with the official installer:"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "install.sh: needs curl or wget to install uv, see https://docs.astral.sh/uv/" >&2
        exit 1
    fi
    # The uv installer puts uv in ~/.local/bin (or $XDG_BIN_HOME), which this shell's PATH may not hold yet.
    PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$HOME/.cargo/bin:$PATH"
    export PATH
    if ! command -v uv >/dev/null 2>&1; then
        echo "install.sh: uv installed, but it is not on PATH: open a new terminal and run this again" >&2
        exit 1
    fi
fi

uv tool install puffin-colony
uv tool update-shell >/dev/null 2>&1 || true

echo
echo "Puffin Colony is installed. Run colony in your repo."
