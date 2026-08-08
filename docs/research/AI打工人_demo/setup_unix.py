import os
import sys
import shutil
import subprocess
import json
import platform
import time
from pathlib import Path

# --- Helpers ---
def run_cmd(cmd, shell=False):
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    subprocess.check_call(cmd, shell=shell)

def get_home():
    return Path.home()

def set_unix_env_var(name, value):
    """Appends export command to shell config files"""
    if not value: return
    
    shell = os.environ.get("SHELL", "/bin/bash")
    rc_files = set()
    
    # Detect shell config files
    home = get_home()
    if "zsh" in shell:
        rc_files.add(home / ".zshrc")
        rc_files.add(home / ".zprofile")
    elif "bash" in shell:
        rc_files.add(home / ".bashrc")
        rc_files.add(home / ".bash_profile")
    else:
        rc_files.add(home / ".profile")
    
    entry = f'\nexport {name}="{value}"'
    
    for rc in rc_files:
        if not rc.exists(): continue # Only append to existing files
        try:
            content = rc.read_text(encoding='utf-8')
            if f'export {name}=' in content:
                print(f"Update: {name} already exists in {rc.name}, skipping append (manual check recommended).")
            else:
                with open(rc, "a", encoding='utf-8') as f:
                    f.write(entry)
                print(f"✅ Added {name} to {rc.name}")
        except Exception as e:
            print(f"⚠️ Could not write to {rc}: {e}")

# --- Steps ---

def step1_init_files():
    print("\n[Api/Files] Running Step 1: Project Initialization...")
    try:
        # Run Step1_init_project_files.py
        run_cmd([sys.executable, "Step1_init_project_files.py"])
    except Exception as e:
        print(f"Step 1 failed: {e}")
        sys.exit(1)

def step2_brain_system_prompt():
    print("\n[Config] Running Step 2: Configure Brain Consultant Persona...")
    src = Path("brain-consultant.md").resolve()
    if not src.exists():
        print(f"Error: {src} not found.")
        return

    dest_dir = get_home() / ".claude" / "agents"
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    dest = dest_dir / "brain-consultant.md"
    shutil.copy2(src, dest)
    print(f"✅ Copied Persona to: {dest}")

def step3_setup_mcp():
    print("\n[MCP] Running Step 3: Setup MCP Server...")
    
    script_path = Path("platform_functions.py").resolve()
    if not script_path.exists():
        print("Error: platform_functions.py not found.")
        sys.exit(1)
        
    print("Installing Python dependencies for MCP...")
    pip_cmd = [sys.executable, "-m", "pip", "install", "playwright", "beautifulsoup4", "pandas", "requests", "mcp"]
    run_cmd(pip_cmd)
    
    print("Installing Playwright browsers...")
    run_cmd([sys.executable, "-m", "playwright", "install", "chromium"])
    
    # Configure Claude MCP
    print("Configuring Claude MCP...")
    
    # Remove old
    try:
        run_cmd(["claude", "mcp", "remove", "brain-mcp"])
    except:
        pass # Ignore if not exists
        
    # Add new
    # On Unix we just call python3 directly
    # Using sys.executable to ensure we use the same python env
    mcp_cmd = ["claude", "mcp", "add", "--scope", "user", "brain-mcp", "--", sys.executable, str(script_path)]
    try:
        run_cmd(mcp_cmd)
    except Exception as e:
        print("Note: 'claude mcp add' might have failed if clauce CLI is not logged in or ready. Continuing to config edit...")

    # Edit config for timeout
    config_path = get_home() / ".claude.json"
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Ensure structure
            if "mcpServers" not in config: config["mcpServers"] = {}
            if "brain-mcp" not in config["mcpServers"]: config["mcpServers"]["brain-mcp"] = {}
            
            brain_mcp = config["mcpServers"]["brain-mcp"]
            brain_mcp["timeout"] = 900
            brain_mcp["description"] = "WorldQuant BRAIN Platform MCP Server - Comprehensive trading platform integration. Credentials in user_config.json. Docs/Forum support."
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print("✅ Updated .claude.json with timeout/description")
        except Exception as e:
            print(f"Failed to update config json: {e}")

def step4_api_config():
    print("\n[API] Running Step 4: Configure API Model...")
    
    # We will import Step4 module to use its interactive logic, but we need to patch the env var setter
    # Because Step4 currently uses PowerShell
    
    try:
        # Load Step4 as a module
        import importlib.util
        spec = importlib.util.spec_from_file_location("Step4", "Step4_SetAPI_And_Check_LLMModel.py")
        step4_module = importlib.util.module_from_spec(spec)
        
        # Monkey patch the windows env var function
        step4_module.set_windows_env_var = set_unix_env_var
        
        # Execute
        spec.loader.exec_module(step4_module)
        
        # Run main
        if hasattr(step4_module, "main"):
            step4_module.main()
            
    except Exception as e:
        print(f"Error running Step 4 logic: {e}")
        print("Fallback: Please manually set ANTHROPIC_BASE_URL and ANTHROPIC_API_KEY in your shell.")

def main():
    print("=== WorldQuant BRAIN Setup (Linux/Mac) ===")
    
    # Prereq check (Runtime)
    if not shutil.which("claude"):
        print("❌ 'claude' command not found. Please install it via 'npm install -g @anthropic-ai/claude-code'")
        sys.exit(1)
        
    step1_init_files()
    step2_brain_system_prompt()
    step3_setup_mcp()
    step4_api_config()
    
    print("\n✅ Setup Complete!")
    print("Please RESTART your terminal to ensure environment variables are loaded.")
    print("Then run: claude --agent brain-consultant")

if __name__ == "__main__":
    main()
