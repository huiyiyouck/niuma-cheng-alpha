# SetAPI_And_Check_MoonShot.py
import os
import sys
import subprocess
import time

# Ensure openai is installed
try:
    from openai import OpenAI
except ImportError:
    print("正在安装 openai 依赖包...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openai"])
    from openai import OpenAI

def set_windows_env_var(name, value):
    """Set a user-level environment variable on Windows using PowerShell."""
    if not value:
        return
    # Escape double quotes for PowerShell
    value_escaped = value.replace('"', '`"')
    ps_command = f'[Environment]::SetEnvironmentVariable("{name}", "{value_escaped}", "User")'
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command]
    try:
        subprocess.check_call(cmd)
        print(f"✅ 环境变量已设置: {name}")
    except subprocess.CalledProcessError as e:
        print(f"❌ 设置失败 {name}: {e}")

def get_provider_config():
    print("\n请选择您要使用的 API 提供商:")
    print("1. Kimi (Moonshot) - [platform.moonshot.cn]")
    print("2. DeepSeek (深度求索) - [platform.deepseek.com]")
    
    while True:
        choice = input("\n请输入序号 (1 或 2): ").strip()
        if choice == "1":
            return {
                "name": "Moonshot (Kimi)",
                "site": "platform.moonshot.cn",
                "list_base_url": "https://api.moonshot.cn/v1",
                "anthropic_base_url": "https://api.moonshot.cn/anthropic",
                "extra_envs": {}
            }
        elif choice == "2":
            return {
                "name": "DeepSeek",
                "site": "platform.deepseek.com",
                "list_base_url": "https://api.deepseek.com",
                "anthropic_base_url": "https://api.deepseek.com/anthropic",
                "extra_envs": {
                    "API_TIMEOUT_MS": "900000",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "ANTHROPIC_SMALL_FAST_MODEL": "{model}" # Placeholder
                }
            }
        else:
            print("输入无效，请重新输入。")

def main():
    print("=== Claude Code API 多模型配置工具 ===")
    
    # 1. Select Provider
    config = get_provider_config()
    
    # 2. Get API Key
    print(f"\n您选择了 {config['name']}。")
    print(f"请前往官网 {config['site']} 申请 API Key。")
    api_key = input(f"请输入您的 API Key (sk-...): ").strip()
    if not api_key:
        print("API Key 不能为空。")
        return

    # 3. Initialize Client to fetch models
    print(f"\n正在连接 {config['name']} API 以获取可用模型列表...")
    try:
        client = OpenAI(
            api_key=api_key,
            base_url=config['list_base_url'],
        )
        
        model_list = client.models.list()
        model_data = model_list.data
        
        if not model_data:
            print("未找到可用模型，请检查您的 API Key 或配置。")
            return

        # 4. List and Select Model
        print(f"\n可用模型列表:")
        sorted_models = sorted(model_data, key=lambda m: m.id)
        for i, model in enumerate(sorted_models):
            print(f"[{i}] {model.id}")
            
        selection = input("\n请输入序号选择默认模型 (例如 0): ").strip()
        try:
            index = int(selection)
            if 0 <= index < len(sorted_models):
                selected_model = sorted_models[index].id
                print(f"已选择模型: {selected_model}")
            else:
                print("无效的序号。")
                return
        except ValueError:
            print("输入无效，请输入数字。")
            return

    except Exception as e:
        print(f"\n❌ API 连接失败: {e}")
        print("无法连接到服务器。请检查网络或 API Key。")
        return

    # 5. Configure Environment Variables
    print("\n正在配置全局环境变量 (Windows User Scope)...")
    
    # Core Anthropic Vars
    set_windows_env_var("ANTHROPIC_BASE_URL", config['anthropic_base_url'])
    set_windows_env_var("ANTHROPIC_AUTH_TOKEN", api_key)
    
    # Model Vars (Standard)
    # Applying selected model to all Standard Roles
    set_windows_env_var("ANTHROPIC_MODEL", selected_model)
    set_windows_env_var("ANTHROPIC_DEFAULT_OPUS_MODEL", selected_model)
    set_windows_env_var("ANTHROPIC_DEFAULT_SONNET_MODEL", selected_model)
    set_windows_env_var("ANTHROPIC_DEFAULT_HAIKU_MODEL", selected_model)
    set_windows_env_var("CLAUDE_CODE_SUBAGENT_MODEL", selected_model)

    # Extra Vars (Provider specific)
    for key, val_template in config['extra_envs'].items():
        val = val_template.format(model=selected_model) # Format if placeholder exists
        set_windows_env_var(key, val)

    print("\n✨ 配置完成！")
    print("************************************************")
    print(f" 提供商: {config['name']}")
    print(f" 模型  : {selected_model}")
    print(f" 接口  : {config['anthropic_base_url']}")
    print("************************************************")
    print("⚠️ 请注意：请务必 关闭并重新打开 您的终端窗口，以应用新的环境变量。")

if __name__ == "__main__":
    main()
