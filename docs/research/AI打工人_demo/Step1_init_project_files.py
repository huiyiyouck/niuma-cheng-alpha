import os
import shutil
import sys
import subprocess
from pathlib import Path
import importlib.util

def install_package():
    print("正在安装/更新 cnhkmcp 包...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "cnhkmcp"])
    except subprocess.CalledProcessError as e:
        print(f"安装失败: {e}")
        sys.exit(1)

def get_package_path(package_name):
    # 重新加载 finder 以防刚安装完
    importlib.invalidate_caches()
    spec = importlib.util.find_spec(package_name)
    if spec and spec.origin:
        return Path(spec.origin).parent
    return None

def main():
    # 1. Install CNHKMCP
    install_package()

    # 2. Locate the package
    pkg_path = get_package_path("cnhkmcp")
    if not pkg_path:
        # Fallback: try site-packages directly if spec fails
        import site
        for site_pkg in site.getsitepackages():
             potential_path = Path(site_pkg) / "cnhkmcp"
             if potential_path.exists():
                 pkg_path = potential_path
                 break
    
    if not pkg_path:
        print("错误: 无法找到 cnhkmcp 包安装路径。")
        sys.exit(1)
        
    print(f"cnhkmcp 安装位置: {pkg_path}")

    # 3. Locate 'untracked' folder
    untracked_dir = pkg_path / "untracked"
    if not untracked_dir.exists():
        print(f"错误: 在 {pkg_path} 中未找到 'untracked' 文件夹")
        sys.exit(1)

    # 4. Copy Files
    files_to_copy = [
        "forum_functions.py",
        "platform_functions.py",
        "配置前运行我_安装必要依赖包.py",
        "brain-consultant.md"
    ]
    
    # Copy to current directory
    target_dir = Path.cwd()
    print(f"正在将文件复制到: {target_dir}")
    
    for filename in files_to_copy:
        src = untracked_dir / filename
        dst = target_dir / filename
        
        if src.exists():
            shutil.copy2(src, dst)
            print(f"✅ 已复制: {filename}")
        else:
            print(f"⚠️ 警告: 源文件未找到: {filename}")

    # 4.1 Copy entire 'untracked' folder to current directory for reference
    target_untracked_dir = target_dir / "untracked"
    print(f"\n正在将整个 untracked 文件夹复制到: {target_untracked_dir}")
    try:
        shutil.copytree(untracked_dir, target_untracked_dir, dirs_exist_ok=True)
        print(f"✅ untracked 文件夹已完整复制到当前目录！")
    except Exception as e:
        print(f"❌ 复制 untracked 文件夹失败: {e}")

    # 4.5 Copy 'skills' folder to user home .claude dir
    src_skills = untracked_dir / "skills"
    # Destination: ~/.claude/skills
    dst_skills = Path.home() / ".claude" / "skills"
    
    if src_skills.exists() and src_skills.is_dir():
        print(f"\n正在将 skills 文件夹复制到: {dst_skills}")
        try:
            # Ensure parent .claude dir exists
            if not dst_skills.parent.exists():
                dst_skills.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy recursively
            shutil.copytree(src_skills, dst_skills, dirs_exist_ok=True)
            print(f"✅ Skills 文件夹已同步成功！")
        except Exception as e:
            print(f"❌ 复制 Skills 文件夹失败: {e}")
    else:
        print(f"\n(未在源包中找到 'skills' 文件夹，本次跳过复制)")

    # 4.6 Move 'settings.json' to .claude folder (Config for Claude Code)
    settings_file = target_dir / "settings.json"
    dst_claude_dir = Path.home() / ".claude"
    dst_settings = dst_claude_dir / "settings.json"

    if settings_file.exists():
        print(f"\n正在将 settings.json 移动(剪切)到: {dst_claude_dir}")
        try:
            if not dst_claude_dir.exists():
                dst_claude_dir.mkdir(parents=True, exist_ok=True)
            
            if dst_settings.exists():
                print(f"⚠️ 目标路径已存在同名文件，将被覆盖: {dst_settings}")
                dst_settings.unlink()
                
            shutil.move(str(settings_file), str(dst_settings))
            print(f"✅ settings.json 已成功移动到 .claude 目录")
        except Exception as e:
            print(f"❌ 移动 settings.json 失败: {e}")

    # 4.7 Move 'hooks' folder to .claude folder
    hooks_src = target_dir / "hooks"
    dst_hooks = dst_claude_dir / "hooks"

    if hooks_src.exists() and hooks_src.is_dir():
        print(f"\n正在将 hooks 文件夹移动(剪切)到: {dst_claude_dir}")
        try:
            if not dst_claude_dir.exists():
                dst_claude_dir.mkdir(parents=True, exist_ok=True)

            if dst_hooks.exists():
                print(f"⚠️ 目标路径已存在 hooks 文件夹，将被移除以进行覆盖...")
                shutil.rmtree(dst_hooks)
            
            shutil.move(str(hooks_src), str(dst_hooks))
            print(f"✅ hooks 文件夹已成功移动到 .claude 目录")
        except Exception as e:
            print(f"❌ 移动 hooks 文件夹失败: {e}")

    print("\n所有文件更新完成！")
    
    # 5. Execute the dependency installer script
    installer_script = "配置前运行我_安装必要依赖包.py"
    if (target_dir / installer_script).exists():
        print(f"\n正在运行依赖安装脚本: {installer_script} ...")
        sys.stdout.flush()
        try:
            # Use same python executable to run the installer script
            subprocess.check_call([sys.executable, str(target_dir / installer_script)])
            print("✅ 依赖安装脚本执行成功！")
        except subprocess.CalledProcessError as e:
            print(f"❌ 依赖安装脚本执行失败: {e}")
            sys.exit(1)
    else:
         print(f"⚠️ 未找到 {installer_script}，跳过依赖安装。")

if __name__ == "__main__":
    main()
