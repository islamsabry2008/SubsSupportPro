#!/bin/sh

# wget -qO - https://raw.githubusercontent.com/popking159/SubsSupportPro/refs/heads/main/myinstaller.sh | /bin/sh
# =========================================================================
# CONFIGURATION (Change these for different repositories)
# =========================================================================
PLUGIN_NAME="SubsSupportPro"
USERNAME="popking159"
REPO="SubsSupportPro"

# 1. SYSTEM DEPENDENCIES (Binary utilities installed exactly as written, e.g., unrar)
SYS_DEPENDS="unrar ffmpeg"
# =========================================================================

# Dynamically construct the download link
PLUGIN_URL="https://github.com/${USERNAME}/${REPO}/raw/refs/heads/main/main.tar.gz"

# Workspace paths
TMP_DIR="/var/volatile/tmp"
[ -d "$TMP_DIR" ] || TMP_DIR="/tmp"
TMP_FILE="$TMP_DIR/main_install.tar.gz"

PKG_MANAGER=""
PYTHON_VERSION=""
FINAL_DEPENDS=""

log() {
    echo "$1"
}

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

is_pkg_installed() {
    pkg="$1"
    # Check apt-get first for DreamOS
    if [ "$PKG_MANAGER" = "apt" ]; then
        dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" && return 0
        return 1
    fi

    # Fallback to opkg for OE-Alliance
    if [ "$PKG_MANAGER" = "opkg" ]; then
        if [ -f /var/lib/opkg/status ]; then
            grep -q "^Package: $pkg$" /var/lib/opkg/status && return 0
        fi
        opkg list-installed 2>/dev/null | grep -q "^$pkg[[:space:]-]" && return 0
        return 1
    fi
    return 1
}

restart_enigma2() {
    log "[INFO] Restarting Enigma2 UI..."
    sleep 2
    if has_cmd systemctl; then
        systemctl restart enigma2
    else
        init 4 && sleep 2 && init 3 || killall -9 enigma2 >/dev/null 2>&1
    fi
}

echo "===================================================="
echo "         $PLUGIN_NAME INSTALLER UTILITY            "
echo "===================================================="

# 1. Detect Package Manager
# STRICT CHECK: We must check apt-get FIRST because some DreamOS 
# distributions contain dummy opkg binaries that fail when executed.
if has_cmd apt-get; then
    PKG_MANAGER="apt"
elif has_cmd opkg; then
    PKG_MANAGER="opkg"
fi
log "[INFO] Package manager detected: ${PKG_MANAGER:-None}"

# 2. Force Python Version based on OS architecture
if [ "$PKG_MANAGER" = "apt" ]; then
    # DreamOS ALWAYS uses Python 2.7 for Enigma2 plugins
    PYTHON_VERSION="2"
    PY_PREFIX="python-"
else
    # OE-Alliance (OpenATV, etc.) uses Python 3 on modern images
    if has_cmd python3; then
        PYTHON_VERSION="3"
        PY_PREFIX="python3-"
    elif has_cmd python; then
        PYTHON_VERSION="2"
        PY_PREFIX="python-"
    fi
fi
log "[INFO] Detected Python Environment: Python $PYTHON_VERSION ($PY_PREFIX)"

# 3. Build the Final Dependency List based on Package Manager & Python Version
# DreamOS (apt) uses 'twisted', OE-Alliance (opkg) uses 'twisted-web'
if [ "$PKG_MANAGER" = "apt" ]; then
    TWISTED_MOD="twisted"
else
    TWISTED_MOD="twisted-web"
fi

PY3_DEPENDS="requests beautifulsoup4 codecs compression core difflib json six $TWISTED_MOD xmlrpc"
PY2_DEPENDS="requests beautifulsoup4 codecs compression core difflib json six twisted xmlrpc"

ACTIVE_PY_DEPENDS=""
if [ "$PYTHON_VERSION" = "3" ]; then
    ACTIVE_PY_DEPENDS="$PY3_DEPENDS"
elif [ "$PYTHON_VERSION" = "2" ]; then
    ACTIVE_PY_DEPENDS="$PY2_DEPENDS"
fi

for dep in $ACTIVE_PY_DEPENDS; do
    FINAL_DEPENDS="$FINAL_DEPENDS ${PY_PREFIX}${dep}"
done

for dep in $SYS_DEPENDS; do
    FINAL_DEPENDS="$FINAL_DEPENDS $dep"
done

# 4. Update Package Feeds (Only if dependencies are requested)
if [ -n "$FINAL_DEPENDS" ] && [ -n "$PKG_MANAGER" ]; then
    if [ "$PKG_MANAGER" = "apt" ]; then
        log "[INFO] Updating apt feeds..."
        apt-get update >/dev/null 2>&1 || log "[WARN] apt update failed, continuing..."
    elif [ "$PKG_MANAGER" = "opkg" ]; then
        log "[INFO] Updating opkg feeds..."
        opkg update >/dev/null 2>&1 || log "[WARN] opkg update failed, continuing..."
    fi
fi

# 5. Check and Download Dependencies (Strict Mode)
if [ -n "$FINAL_DEPENDS" ]; then
    log "[INFO] Verifying required dependencies..."
    for pkg in $FINAL_DEPENDS; do
        if is_pkg_installed "$pkg"; then
            log "[OK] Already installed: $pkg"
        else
            log "[INFO] Downloading and installing: $pkg"
            if [ "$PKG_MANAGER" = "apt" ]; then
                DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg" >/dev/null 2>&1
            elif [ "$PKG_MANAGER" = "opkg" ]; then
                opkg install "$pkg" >/dev/null 2>&1
            fi
            
            # Strict Verification: If it failed to install, abort immediately
            if is_pkg_installed "$pkg"; then
                log "[OK] Successfully installed: $pkg"
            else
                log "[ERROR] Required dependency '$pkg' could not be installed! Aborting setup."
                exit 1
            fi
        fi
    done
else
    log "[INFO] No dependencies specified in configuration. Skipping dependency phase."
fi

# 6. Download Plugin Archive
log "[INFO] Downloading main plugin tree archive..."
rm -f "$TMP_FILE"
wget -q --no-check-certificate "$PLUGIN_URL" -O "$TMP_FILE"

if [ ! -s "$TMP_FILE" ]; then
    log "[ERROR] Download failed or file is empty!"
    rm -f "$TMP_FILE"
    exit 1
fi

# 7. Extract directly to ROOT (/)
log "[INFO] Extracting payload contents to system paths..."
tar -xzf "$TMP_FILE" -C /
if [ $? -ne 0 ]; then
    log "[ERROR] Extraction failed!"
    rm -f "$TMP_FILE"
    exit 1
fi

rm -f "$TMP_FILE"
sync

echo "===================================================="
echo "          $PLUGIN_NAME INSTALLATION COMPLETE        "
echo "===================================================="

restart_enigma2
exit 0
