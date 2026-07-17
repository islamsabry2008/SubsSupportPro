#!/bin/sh

# ============================================================
# SubsSupportPro Installer v1.1.0
# Supports DreamOS + OpenATV/OpenPLi style images
# Adds dependency check/install before plugin extraction
# ============================================================

PLUGIN_PACKAGE="enigma2-plugin-extensions-subssupportpro"
PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/SubsSupportPro"
PLUGIN_URL="https://github.com/popking159/SubsSupportPro/raw/refs/heads/main/main.tar.gz"
TMP_DIR="/var/volatile/tmp"
[ -d "$TMP_DIR" ] || TMP_DIR="/tmp"
TMP_FILE="$TMP_DIR/subssupportpro-main.tar.gz"

# Set STRICT_DEPS=1 if you want installer to stop when a dependency cannot be installed.
STRICT_DEPS=0
FAILED_DEPS=""
PKG_MANAGER=""
PYTHON_BIN="python"
PREFER_PY3=0

log() {
    echo "$1"
}

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

is_pkg_installed() {
    pkg="$1"

    if [ "$PKG_MANAGER" = "opkg" ]; then
        if [ -f /var/lib/opkg/status ]; then
            grep -q "^Package: $pkg$" /var/lib/opkg/status && return 0
        fi
        opkg list-installed 2>/dev/null | grep -q "^$pkg[[:space:]-]" && return 0
        return 1
    fi

    if [ "$PKG_MANAGER" = "apt" ]; then
        dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" && return 0
        return 1
    fi

    return 1
}

install_pkg() {
    pkg="$1"

    if is_pkg_installed "$pkg"; then
        log "[OK] Dependency already installed: $pkg"
        return 0
    fi

    log "[INFO] Installing dependency: $pkg"

    if [ "$PKG_MANAGER" = "opkg" ]; then
        opkg install "$pkg" >/dev/null 2>&1 && return 0
    elif [ "$PKG_MANAGER" = "apt" ]; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg" >/dev/null 2>&1 && return 0
    else
        log "[WARN] No supported package manager found for: $pkg"
        return 1
    fi

    log "[WARN] Could not install dependency package: $pkg"
    return 1
}

install_alt() {
    # Usage: install_alt display_name pkg_py2 pkg_py3
    display="$1"
    shift

    # If any alternative is already installed, the dependency group is satisfied.
    for pkg in "$@"; do
        if is_pkg_installed "$pkg"; then
            log "[OK] $display satisfied by installed package: $pkg"
            return 0
        fi
    done

    # Prefer python3-* packages when python3 exists.
    if [ "$PREFER_PY3" = "1" ]; then
        for pkg in "$@"; do
            case "$pkg" in
                python3-*)
                    install_pkg "$pkg" && return 0
                    ;;
            esac
        done
    fi

    # Then try remaining alternatives in the order supplied.
    for pkg in "$@"; do
        case "$pkg" in
            python3-*)
                [ "$PREFER_PY3" = "1" ] && continue
                ;;
        esac
        install_pkg "$pkg" && return 0
    done

    log "[WARN] Failed to satisfy dependency group: $display"
    FAILED_DEPS="$FAILED_DEPS $display"
    return 1
}

python_has_module() {
    module="$1"
    "$PYTHON_BIN" - <<ENDPY >/dev/null 2>&1
import $module
ENDPY
}

python_has_xmlrpc() {
    "$PYTHON_BIN" - <<'ENDPY' >/dev/null 2>&1
try:
    import xmlrpc.client
except Exception:
    import xmlrpclib
ENDPY
}

install_python_dep_if_needed() {
    display="$1"
    module="$2"
    shift 2

    if python_has_module "$module"; then
        log "[OK] Python module available: $module"
        return 0
    fi

    install_alt "$display" "$@"
}

install_xmlrpc_if_needed() {
    if python_has_xmlrpc; then
        log "[OK] Python module available: xmlrpc"
        return 0
    fi

    install_alt "python-xmlrpc" python-xmlrpc python3-xmlrpc
}

install_unrar_if_needed() {
    if has_cmd unrar; then
        log "[OK] Binary available: unrar"
        return 0
    fi

    install_alt "unrar" unrar
}

restart_enigma2() {
    log "Restarting Enigma2..."
    killall -9 enigma2 >/dev/null 2>&1
}

echo "===================================================="
echo "        SubsSupportPro INSTALLER STARTED            "
echo "===================================================="

# ---------------------------
# Detect image/package manager
# ---------------------------
if has_cmd opkg; then
    PKG_MANAGER="opkg"
elif has_cmd apt-get; then
    PKG_MANAGER="apt"
fi

if has_cmd python3; then
    PYTHON_BIN="python3"
    PREFER_PY3=1
elif has_cmd python; then
    PYTHON_BIN="python"
    PREFER_PY3=0
fi

log "[INFO] Package manager: ${PKG_MANAGER:-not found}"
log "[INFO] Python binary: $PYTHON_BIN"

# ---------------------------
# Update feeds
# ---------------------------
if [ "$PKG_MANAGER" = "opkg" ]; then
    log "[INFO] Updating opkg feeds..."
    opkg update >/dev/null 2>&1 || log "[WARN] opkg update failed, continuing..."
elif [ "$PKG_MANAGER" = "apt" ]; then
    log "[INFO] Updating apt feeds..."
    apt-get update >/dev/null 2>&1 || log "[WARN] apt-get update failed, continuing..."
else
    log "[WARN] No opkg/apt package manager found. Dependency install will be skipped."
fi

# ---------------------------
# Remove old version
# ---------------------------
log "[INFO] Removing old SubsSupportPro files..."
rm -rf "$PLUGIN_DIR"

# ---------------------------
# Remove old package if exists
# ---------------------------
if [ "$PKG_MANAGER" = "opkg" ] && is_pkg_installed "$PLUGIN_PACKAGE"; then
    log "[INFO] Removing old opkg package: $PLUGIN_PACKAGE"
    opkg remove "$PLUGIN_PACKAGE" >/dev/null 2>&1 || true
elif [ "$PKG_MANAGER" = "apt" ] && is_pkg_installed "$PLUGIN_PACKAGE"; then
    log "[INFO] Removing old apt package: $PLUGIN_PACKAGE"
    DEBIAN_FRONTEND=noninteractive apt-get remove -y "$PLUGIN_PACKAGE" >/dev/null 2>&1 || true
fi

# ---------------------------
# Check/install dependencies
# Equivalent Depends line:
# python-codecs | python3-codecs,
# python-compression | python3-compression,
# python-core | python3-core,
# python-difflib | python3-difflib,
# python-json | python3-json,
# python-requests | python3-requests,
# python-six | python3-six,
# python-twisted-web | python3-twisted-web,
# python-xmlrpc | python3-xmlrpc,
# python-beautifulsoup4 | python3-beautifulsoup4,
# unrar
# ---------------------------
log "[INFO] Checking/installing dependencies..."

install_python_dep_if_needed "python-codecs" "codecs" python-codecs python3-codecs
install_python_dep_if_needed "python-compression" "gzip" python-compression python3-compression
install_python_dep_if_needed "python-core" "sys" python-core python3-core
install_python_dep_if_needed "python-difflib" "difflib" python-difflib python3-difflib
install_python_dep_if_needed "python-json" "json" python-json python3-json
install_python_dep_if_needed "python-requests" "requests" python-requests python3-requests
install_python_dep_if_needed "python-six" "six" python-six python3-six
install_python_dep_if_needed "python-twisted-web" "twisted.web" python-twisted-web python3-twisted-web
install_xmlrpc_if_needed
install_python_dep_if_needed "python-beautifulsoup4" "bs4" python-beautifulsoup4 python3-beautifulsoup4
install_unrar_if_needed

if [ -n "$FAILED_DEPS" ]; then
    log "[WARN] Some dependencies could not be confirmed/installed:$FAILED_DEPS"
    if [ "$STRICT_DEPS" = "1" ]; then
        log "[ERROR] STRICT_DEPS=1, stopping installation."
        exit 1
    fi
    log "[INFO] Continuing because STRICT_DEPS=0."
fi

# ---------------------------
# Download plugin
# ---------------------------
log "[INFO] Downloading plugin..."
rm -f "$TMP_FILE"

wget -q --no-check-certificate "$PLUGIN_URL" -O "$TMP_FILE"

if [ ! -s "$TMP_FILE" ]; then
    log "[ERROR] Download failed or empty file!"
    rm -f "$TMP_FILE"
    exit 1
fi

# ---------------------------
# Extract plugin
# ---------------------------
log "[INFO] Extracting plugin..."
tar -xzf "$TMP_FILE" -C /

if [ "$?" != "0" ]; then
    log "[ERROR] Extraction failed!"
    rm -f "$TMP_FILE"
    exit 1
fi

rm -f "$TMP_FILE"

# ---------------------------
# Finish
# ---------------------------
sync

echo "===================================================="
echo "       SubsSupportPro INSTALLATION DONE             "
echo "===================================================="

restart_enigma2

exit 0
