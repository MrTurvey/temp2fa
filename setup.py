#!/usr/bin/env python3
"""
2FA Manager Setup Script
Simple setup script for easy installation
"""

import sys
import subprocess
import os
import platform

def check_python_version():
    """Check if Python version is 3.8 or higher"""
    if sys.version_info < (3, 8):
        print("❌ Error: Python 3.8 or higher is required")
        print(f"   Current version: {sys.version}")
        return False
    print(f"✅ Python {sys.version.split()[0]} is supported")
    return True

def install_tkinter():
    """Attempt to install tkinter automatically"""
    system = platform.system().lower()
    
    if system == "linux":
        print("🔧 Attempting to install tkinter automatically...")
        
        # Try to detect Linux distribution and install
        try:
            with open('/etc/os-release', 'r') as f:
                os_info = f.read().lower()
            
            commands = []
            if 'ubuntu' in os_info or 'debian' in os_info:
                commands = [
                    ["sudo", "apt-get", "update"],
                    ["sudo", "apt-get", "install", "-y", "python3-tk", "python3-dev", "xclip", "wl-clipboard"]
                ]
            elif 'centos' in os_info or 'rhel' in os_info:
                commands = [
                    ["sudo", "yum", "install", "-y", "tkinter", "python3-devel", "xclip", "wl-clipboard"]
                ]
            elif 'fedora' in os_info:
                commands = [
                    ["sudo", "dnf", "install", "-y", "python3-tkinter", "python3-devel", "xclip", "wl-clipboard"]
                ]
            elif 'arch' in os_info:
                commands = [
                    ["sudo", "pacman", "-S", "--noconfirm", "tk", "python", "xclip", "wl-clipboard"]
                ]
            elif 'opensuse' in os_info or 'suse' in os_info:
                commands = [
                    ["sudo", "zypper", "install", "-y", "python3-tk", "python3-devel", "xclip", "wl-clipboard"]
                ]
            
            if commands:
                print("🔧 Installing system packages...")
                for cmd in commands:
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        print(f"   ❌ Failed: {' '.join(cmd)}")
                        print(f"   Error: {result.stderr.strip()}")
                        return False
                print("✅ System packages installed")
                return True
            else:
                print("❌ Could not detect Linux distribution for automatic installation")
                return False
                
        except Exception as e:
            print(f"❌ Automatic installation failed: {e}")
            return False
    
    elif system == "darwin":  # macOS
        print("ℹ️  On macOS, tkinter should be included with Python")
        print("   If missing, please reinstall Python from python.org")
        return False
    
    elif system == "windows":
        print("ℹ️  On Windows, tkinter should be included with Python")
        return True
    
    return False

def check_and_install_tkinter():
    """Check if tkinter is available, attempt installation if not"""
    try:
        import tkinter
        print("✅ tkinter is available")
        return True
    except ImportError:
        print("❌ tkinter not found!")
        
        # Ask user for permission to install
        try:
            response = input("\n🤔 Would you like me to try installing tkinter automatically? (y/N): ").strip().lower()
            if response in ['y', 'yes']:
                if install_tkinter():
                    # Test again after installation
                    try:
                        import tkinter
                        print("✅ tkinter is now available!")
                        return True
                    except ImportError:
                        print("❌ tkinter installation may have failed, please restart terminal/session")
                        return False
                else:
                    print("❌ Automatic installation failed")
                    return False
            else:
                print("❌ tkinter installation skipped by user")
                return False
        except KeyboardInterrupt:
            print("\n❌ Installation cancelled")
            return False

def check_clipboard_tools():
    """Check if clipboard tools are installed on Linux"""
    system = platform.system().lower()
    
    if system == "linux":
        # Check xclip (required)
        try:
            subprocess.run(['xclip', '-version'], capture_output=True)
        except FileNotFoundError:
            print("❌ xclip not found - QR paste from clipboard won't work")
            return False
        
        # Check wl-clipboard (optional, don't report if missing)
        try:
            subprocess.run(['wl-paste', '--version'], capture_output=True)
        except FileNotFoundError:
            pass  # Silent - not critical
        
        return True
    
    return True  # Windows/Mac don't need these tools

def install_requirements():
    """Install required packages"""
    print("📦 Installing required packages...")
    
    # Check if we're in a virtual environment
    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    
    if in_venv:
        print("✅ Virtual environment detected - this is recommended!")
    else:
        print("⚠️  Not in a virtual environment - this may cause issues")
    
    # Try different installation approaches
    install_commands = [
        # Standard pip install (should work in venv)
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        # If that fails, try with --user flag
        [sys.executable, "-m", "pip", "install", "--user", "-r", "requirements.txt"],
        # Last resort: break system packages (with user confirmation)
        None  # Will be handled separately
    ]
    
    for i, cmd in enumerate(install_commands):
        if cmd is None:
            # Last resort option
            try:
                response = input("\n🤔 Standard installation failed. Try --break-system-packages? (y/N): ").strip().lower()
                if response in ['y', 'yes']:
                    cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", "-r", "requirements.txt"]
                else:
                    print("❌ Installation cancelled by user")
                    return False
            except KeyboardInterrupt:
                print("\n❌ Installation cancelled")
                return False
        
        try:
            # Run pip install quietly unless it's the --break-system-packages option
            if "--break-system-packages" in cmd:
                subprocess.check_call(cmd)  # Show output for this one
            else:
                subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("✅ Python packages installed")
            return True
        except subprocess.CalledProcessError:
            if i < len(install_commands) - 1:
                continue  # Try next method silently
            # If we get here, all methods failed
    
    print("❌ All installation methods failed")
    print("\n💡 Manual installation:")
    print("   You can try installing packages manually:")
    print("   pip install pyotp Pillow opencv-python numpy")
    return False

def main():
    """Main setup function"""
    print("🔐 2FA Manager Setup")
    
    # Check Python version
    if not check_python_version():
        sys.exit(1)
    
    # Check and install tkinter if needed
    if not check_and_install_tkinter():
        print("❌ Setup failed - tkinter required")
        sys.exit(1)
    
    # Check if requirements.txt exists
    if not os.path.exists("requirements.txt"):
        print("❌ Error: requirements.txt not found")
        sys.exit(1)
    
    # Install requirements
    if not install_requirements():
        sys.exit(1)
    
    # Check clipboard tools (after system packages are installed)
    if not check_clipboard_tools():
        print("⚠️  Setup complete - clipboard paste may not work (missing xclip)")
    else:
        print("🎉 Setup completed successfully!")
    
    print("\n📝 Run: python temp2fa.py")

if __name__ == "__main__":
    main()