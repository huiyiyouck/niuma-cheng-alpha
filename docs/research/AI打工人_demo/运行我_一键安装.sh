#!/bin/bash
echo "=== Brain Project Installer (Linux/Mac) ==="

# Function: Download and Install Node on Mac manually if Brew is missing
install_node_mac_manual() {
    echo "⚠️ Homebrew not found. Attempting manual installation from npmmirror..."
    
    ARCH=$(uname -m)
    NODE_VER="v20.11.0"
    MIRROR="https://npmmirror.com/mirrors/node/$NODE_VER"
    
    if [[ "$ARCH" == "arm64" ]]; then
        FILENAME="node-$NODE_VER-darwin-arm64.pkg"
    else
        FILENAME="node-$NODE_VER-darwin-x64.pkg"
    fi
    
    URL="$MIRROR/$FILENAME"
    TEMP_PKG="/tmp/$FILENAME"
    
    echo "⬇️ Downloading Node.js ($ARCH) from mirror..."
    echo "   URL: $URL"
    curl -L "$URL" -o "$TEMP_PKG" --progress-bar
    
    if [[ -f "$TEMP_PKG" ]]; then
        echo "📦 Installing Node.js (Root password required)..."
        sudo installer -pkg "$TEMP_PKG" -target /
        rm "$TEMP_PKG"
    else
        echo "❌ Download failed."
        exit 1
    fi
}

# 1. Dependency Checks & Installation
echo "[1/3] Checking System Dependencies..."

# --- Node.js Check ---
if ! command -v node &> /dev/null; then
    echo "🔸 Node.js not found. Installing..."
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # MacOS
        if command -v brew &> /dev/null; then
            echo "🍺 Using Homebrew to install Node..."
            brew install node
        else
            install_node_mac_manual
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux (Debian/Ubuntu fallback)
        if command -v apt-get &> /dev/null; then
            echo "🐧 Using apt-get to install Node..."
            # Install prerequisites for latest node if possible, or just standard
            sudo apt-get update
            sudo apt-get install -y nodejs npm
        else
            echo "❌ Automatic install failed (Not Ubuntu/Debian?). Please install Node.js manually."
            exit 1
        fi
    fi
    
    # Check again
    if ! command -v node &> /dev/null; then
        echo "❌ Node.js installation failed. Please install manually."
        exit 1
    fi
else
    echo "✅ Node.js found: $(node -v)"
fi

# --- Python3 Check ---
if ! command -v python3 &> /dev/null; then
    echo "🔸 Python3 not found."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "🍎 Please install Python 3. Usually executing 'python3' triggers the install prompt."
        exit 1
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "🐧 Installing Python3..."
        sudo apt-get install -y python3 python3-pip venv
    fi
else
    echo "✅ Python3 found: $(python3 --version)"
fi

# --- Claude CLI Check ---
if ! command -v claude &> /dev/null; then
    echo "[2/3] Installing Claude Code CLI..."
    # Config npm to use mirror first
    npm config set registry https://registry.npmmirror.com/
    
    # Try install
    echo "📦 npm install -g @anthropic-ai/claude-code"
    # Try without sudo first (configuration might allow it), then with sudo
    if ! npm install -g @anthropic-ai/claude-code --registry=https://registry.npmmirror.com; then
        echo "⚠️ Permission denied. Retrying with sudo..."
        sudo npm install -g @anthropic-ai/claude-code --registry=https://registry.npmmirror.com --unsafe-perm=true --allow-root
    fi
else
    echo "✅ Claude CLI found: $(claude --version)"
fi

# Install python pip deps just in case
echo "📦 Installing/Upgrading cnhkmcp requirements..."
# Ensure pip is explicitly available for python3
if command -v pip3 &> /dev/null; then
   PIP_CMD="pip3"
else
   PIP_CMD="python3 -m pip"
fi
$PIP_CMD install --upgrade pip

# 2. Run Python Setup
echo "[3/3] Running Configuration Script..."
python3 setup_unix.py

# 3. Finish
echo ""
echo "🎉 Installation Finished!"
echo "➡️  Restart your terminal."
echo "➡️  Run 'claude' to start."
