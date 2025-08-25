#!/usr/bin/env python3
"""
Temporary 2FA Manager - Clean and Efficient Version
A modern GUI for managing 2FA codes with QR scanning and secure storage.
"""

import os
import json
import time
import base64
import threading
import logging
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from typing import Dict, Optional, Any
import pyotp
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import cv2
import numpy as np

# Configure logging - quiet console, detailed file
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# File handler - detailed logging
file_handler = logging.FileHandler('2fa_manager.log')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# Console handler - only warnings and errors
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)
console_formatter = logging.Formatter('%(levelname)s: %(message)s')
console_handler.setFormatter(console_formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

try:
    from PIL import ImageGrab
    CLIPBOARD_AVAILABLE = True
    logger.info("Clipboard functionality available")
except ImportError:
    CLIPBOARD_AVAILABLE = False
    logger.warning("Clipboard functionality not available")

def get_clipboard_image():
    """Cross-platform clipboard image retrieval"""
    import platform
    system = platform.system().lower()
    logger.info(f"Attempting clipboard retrieval on {system}")
    
    if system == "linux":
        # Try multiple methods for Linux
        try:
            # Method 1: Try PIL ImageGrab first
            logger.info("Trying PIL ImageGrab...")
            image = ImageGrab.grabclipboard()
            if image:
                logger.info("PIL ImageGrab succeeded")
                return image
            else:
                logger.info("PIL ImageGrab returned None")
        except Exception as e:
            logger.warning(f"PIL ImageGrab failed on Linux: {e}")
        
        try:
            # Method 2: Use xclip for X11 - try multiple image formats
            import subprocess
            import tempfile
            import os
            
            logger.info("Trying xclip method...")
            # Try different image MIME types that might be in clipboard
            for mime_type in ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/bmp']:
                try:
                    logger.debug(f"Trying xclip with {mime_type}")
                    result = subprocess.run(['xclip', '-selection', 'clipboard', '-t', mime_type, '-o'], 
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    logger.debug(f"xclip returned: code={result.returncode}, stdout_len={len(result.stdout)}")
                    if result.returncode == 0 and len(result.stdout) > 0:
                        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                            tmp.write(result.stdout)
                            tmp.flush()
                            image = Image.open(tmp.name)
                            os.unlink(tmp.name)
                            logger.info(f"Clipboard image found with MIME type: {mime_type}")
                            return image
                except Exception as e:
                    logger.debug(f"Failed to get clipboard with {mime_type}: {e}")
                    continue
        except Exception as e:
            logger.warning(f"xclip method failed: {e}")
        
        try:
            # Method 3: Use wl-clipboard for Wayland
            import subprocess
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                result = subprocess.run(['wl-paste', '--type', 'image/png'], 
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode == 0:
                    tmp.write(result.stdout)
                    tmp.flush()
                    image = Image.open(tmp.name)
                    os.unlink(tmp.name)
                    return image
        except Exception as e:
            logger.warning(f"wl-paste method failed: {e}")
        
        return None
    else:
        # Windows/macOS
        try:
            return ImageGrab.grabclipboard()
        except Exception:
            return None

# Constants
TOTP_PERIOD = 30  # Standard TOTP period in seconds
MIN_SECRET_LENGTH = 16  # Minimum secret key length
DEFAULT_STORAGE_FILE = "totp_secrets.json"
APP_VERSION = "2.0.0"

def get_system_font():
    """Get appropriate font for the current system"""
    import platform
    system = platform.system().lower()
    
    if system == "windows":
        return ("Segoe UI", 10)
    elif system == "darwin":  # macOS
        return ("SF Pro Display", 10)
    else:  # Linux
        # For Linux, just return standard fallback fonts that exist
        # Don't try to test them as it can cause issues
        return ("sans-serif", 10)  # This will use system default sans-serif

class QRDecoder:
    """QR code decoder using OpenCV"""
    
    def __init__(self):
        self.detector = cv2.QRCodeDetector()
    
    def decode_qr(self, image_pil: Image.Image) -> Optional[str]:
        """Decode QR code from PIL Image"""
        try:
            opencv_image = cv2.cvtColor(np.array(image_pil), cv2.COLOR_RGB2BGR)
            data, _, _ = self.detector.detectAndDecode(opencv_image)
            
            if data:
                logger.info("QR code decoded successfully")
                return data
            
            # Try with grayscale
            gray = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2GRAY)
            data, _, _ = self.detector.detectAndDecode(gray)
            if data:
                logger.info("QR code decoded successfully (grayscale)")
            return data if data else None
            
        except Exception as e:
            logger.error(f"QR decode error: {e}")
            return None

class TOTPManager:
    """Manages TOTP secrets with simple file storage"""
    
    def __init__(self, storage_file: str = DEFAULT_STORAGE_FILE):
        self.storage_file = storage_file
        self.secrets: Dict[str, Any] = {}
        self.qr_decoder = QRDecoder()
        logger.info(f"TOTPManager initialized with storage: {storage_file}")
        
    def load_secrets(self) -> bool:
        """Load secrets from file"""
        try:
            if not os.path.exists(self.storage_file):
                self.secrets = {}
                return True
                
            with open(self.storage_file, 'r') as f:
                data = json.load(f)
            
            # Check if this is encrypted data (old format with salt/data keys)
            if isinstance(data, dict) and 'salt' in data and 'data' in data:
                # This is encrypted data from old version, start fresh
                self.secrets = {}
                return True
            
            self.secrets = data
            return True
            
        except Exception as e:
            logger.error(f"Failed to load secrets: {e}")
            return False
    
    def save_secrets(self) -> bool:
        """Save secrets to file"""
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(self.secrets, f, indent=2)
            return True
            
        except Exception as e:
            logger.error(f"Failed to save secrets: {e}")
            return False
    
    def extract_secret_from_image(self, image: Image.Image) -> Optional[Dict[str, str]]:
        """Extract TOTP secret from PIL Image"""
        try:
            qr_data = self.qr_decoder.decode_qr(image)
            
            if not qr_data or not qr_data.startswith('otpauth://totp/'):
                return None
            
            parsed_url = urlparse(qr_data)
            params = parse_qs(parsed_url.query)
            
            secret = params.get('secret', [None])[0]
            issuer = params.get('issuer', ['Unknown'])[0]
            
            account_name = parsed_url.path.lstrip('/')
            if ':' in account_name:
                issuer_from_path, account_name = account_name.split(':', 1)
                if issuer == 'Unknown':
                    issuer = issuer_from_path
            
            if not secret:
                return None
            
            return {
                'secret': secret,
                'account': account_name,
                'issuer': issuer
            }
            
        except Exception as e:
            logger.error(f"Failed to extract secret from image: {e}")
            return None
    
    def add_account_from_qr(self, qr_data: Dict[str, str]) -> bool:
        """Add account from QR data"""
        try:
            # Validate secret
            totp = pyotp.TOTP(qr_data['secret'])
            totp.now()
            
            # Create unique name
            base_name = f"{qr_data['issuer']}_{qr_data['account']}"
            name = base_name
            counter = 1
            while name in self.secrets:
                name = f"{base_name}_{counter}"
                counter += 1
            
            self.secrets[name] = {
                'secret': qr_data['secret'],
                'account': qr_data['account'],
                'issuer': qr_data['issuer'],
                'added': time.time()
            }
            return True
            
        except Exception as e:
            logger.error(f"Failed to add account from QR: {e}")
            return False
    
    def add_account_manual(self, name: str, secret: str, issuer: str = "Manual") -> bool:
        """Add account manually"""
        try:
            # Clean and validate secret
            clean_secret = secret.replace(' ', '').replace('-', '').upper()
            totp = pyotp.TOTP(clean_secret)
            totp.now()
            
            # Create unique key
            key = f"{issuer}_{name}"
            counter = 1
            while key in self.secrets:
                key = f"{issuer}_{name}_{counter}"
                counter += 1
            
            self.secrets[key] = {
                'secret': clean_secret,
                'account': name,
                'issuer': issuer,
                'added': time.time()
            }
            return True
            
        except Exception as e:
            logger.error(f"Failed to add manual account: {e}")
            return False
    
    def generate_code(self, account_key: str) -> Optional[str]:
        """Generate current TOTP code"""
        if account_key not in self.secrets:
            logger.warning(f"Account key not found: {account_key}")
            return None
        
        data = self.secrets[account_key]
        # Handle case where data might be a string instead of dict
        if isinstance(data, dict):
            secret = data['secret']
        else:
            # If data is a string, assume it's the secret itself
            secret = data
        
        totp = pyotp.TOTP(secret)
        return totp.now()
    
    def get_time_remaining(self) -> int:
        """Get seconds remaining until next code generation"""
        return TOTP_PERIOD - (int(time.time()) % TOTP_PERIOD)
    
    def list_accounts(self) -> Dict[str, Dict[str, Any]]:
        """List all accounts"""
        result = {}
        for key, data in self.secrets.items():
            # Handle case where data might be a string instead of dict
            if isinstance(data, dict):
                result[key] = {
                    'account': data.get('account', key),
                    'issuer': data.get('issuer', 'Unknown'),
                    'added': data.get('added', 0)
                }
            else:
                # If data is not a dict (likely a string), create a basic entry
                result[key] = {
                    'account': key,
                    'issuer': 'Unknown',
                    'added': 0
                }
        return result
    
    def remove_account(self, account_key: str) -> bool:
        """Remove an account"""
        if account_key in self.secrets:
            del self.secrets[account_key]
            return True
        return False

class ModernButton(tk.Canvas):
    """Custom modern button with hover effects"""
    
    def __init__(self, parent, text="", command=None, bg_color="#4CAF50", 
                 hover_color="#45a049", text_color="white", width=120, height=35, **kwargs):
        super().__init__(parent, width=width, height=height, highlightthickness=0, **kwargs)
        
        self.command = command
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.text_color = text_color
        self.text = text
        
        self.draw_button()
        self.bind("<Button-1>", self.on_click)
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        
    def draw_button(self, hover=False):
        """Draw button with optional hover state"""
        self.delete("all")
        color = self.hover_color if hover else self.bg_color
        
        self.create_rectangle(2, 2, self.winfo_reqwidth()-2, self.winfo_reqheight()-2, 
                            fill=color, outline="")
        
        base_font = get_system_font()
        button_font = (base_font[0], base_font[1], "bold")
        self.create_text(self.winfo_reqwidth()//2, self.winfo_reqheight()//2, 
                        text=self.text, fill=self.text_color, font=button_font)
    
    def on_enter(self, event):
        self.draw_button(hover=True)
    
    def on_leave(self, event):
        self.draw_button(hover=False)
    
    def on_click(self, event):
        if self.command:
            self.command()

class TOTPManagerGUI:
    """Main GUI application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("🔒 Temporary 2FA Manager")
        self.root.geometry("900x650")
        self.root.configure(bg="#f0f0f0")
        
        # Set icon and styles
        self.set_window_icon()
        self.setup_styles()
        
        # Initialize manager and state
        self.manager = TOTPManager()
        self.account_mapping = {}
        self.update_thread = None
        self.running = False
        
        # Create interface
        self.create_widgets()
        
        # Load secrets immediately without password prompt
        self.manager.load_secrets()
        self.refresh_accounts_list()
        self.start_update_thread()
        
    def set_window_icon(self):
        """Set custom window icon"""
        try:
            # Try external icon files first
            for icon_file in ["icon.ico", "2fa_icon.ico", "app_icon.ico"]:
                if os.path.exists(icon_file):
                    self.root.iconbitmap(icon_file)
                    return
            
            # Try creating a simple bitmap icon that works on Windows
            self.create_windows_icon()
                
        except Exception:
            # Fallback: just add emoji to title
            if not self.root.title().startswith("🔒"):
                self.root.title("🔒 " + self.root.title())
    
    def create_windows_icon(self):
        """Create a Windows-compatible icon"""
        try:
            # Create a simple 32x32 icon using PIL
            from PIL import Image, ImageDraw
            
            # Create a simple lock icon
            img = Image.new('RGBA', (32, 32), (255, 255, 255, 0))
            draw = ImageDraw.Draw(img)
            
            # Draw lock shape
            # Lock body (rectangle)
            draw.rectangle([8, 16, 24, 28], fill=(52, 73, 94, 255))
            
            # Lock shackle (top U-shape)
            draw.arc([10, 8, 22, 20], start=0, end=180, fill=(52, 73, 94, 255), width=3)
            draw.arc([11, 7, 21, 19], start=0, end=180, fill=(52, 73, 94, 255), width=2)
            
            # Keyhole
            draw.ellipse([14, 19, 18, 23], fill=(255, 255, 255, 255))
            draw.rectangle([15, 22, 17, 26], fill=(255, 255, 255, 255))
            
            # Save as temporary ICO file
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(suffix='.ico', delete=False) as tmp:
                # Convert to ICO format
                img.save(tmp.name, format='ICO', sizes=[(32, 32)])
                tmp.flush()
                
                # Set as window icon
                self.root.iconbitmap(tmp.name)
                
                # Schedule cleanup of temp file
                self.root.after(1000, lambda: self._cleanup_temp_file(tmp.name))
            
        except Exception:
            # Final fallback
            if not self.root.title().startswith("🔒"):
                self.root.title("🔒 " + self.root.title())
    
    def _cleanup_temp_file(self, filepath):
        """Clean up temporary icon file"""
        try:
            if os.path.exists(filepath):
                os.unlink(filepath)
        except:
            pass
    
    def setup_styles(self):
        """Configure modern ttk styles"""
        style = ttk.Style()
        base_font = get_system_font()
        
        style.configure("Title.TLabel", font=(base_font[0], base_font[1] + 10, "bold"), 
                       background="#f0f0f0", foreground="#2c3e50")
        style.configure("Header.TLabel", font=(base_font[0], base_font[1] + 2, "bold"), 
                       background="#ffffff", foreground="#34495e")
        style.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        
        style.configure("Modern.Treeview", background="#ffffff", foreground="#2c3e50",
                       rowheight=35, fieldbackground="#ffffff", font=base_font)
        style.configure("Modern.Treeview.Heading", background="#ecf0f1", 
                       foreground="#2c3e50", font=(base_font[0], base_font[1] + 1, "bold"))
        style.map("Modern.Treeview", background=[('selected', '#3498db')],
                 foreground=[('selected', 'white')])
    
    def create_widgets(self):
        """Create all GUI widgets"""
        # Create notification system first
        self.create_notification_system()
        
        # Main container
        main_container = tk.Frame(self.root, bg="#f0f0f0")
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Title
        title_frame = tk.Frame(main_container, bg="#f0f0f0")
        title_frame.pack(fill=tk.X, pady=(0, 30))
        
        ttk.Label(title_frame, text="🔐 Temporary 2FA Manager", style="Title.TLabel").pack()
        
        # Action buttons card
        actions_card = ttk.Frame(main_container, style="Card.TFrame", padding="20")
        actions_card.pack(fill=tk.X, pady=(0, 20))
        
        # Button container
        button_container = tk.Frame(actions_card, bg="#ffffff")
        button_container.pack()
        
        # Create only the 5 action buttons
        buttons_config = [
            ("📋 Paste QR Code", self.paste_qr_from_clipboard, "#3498db", "#2980b9", 140),
            ("📁 Load from File", self.load_qr_from_file, "#9b59b6", "#8e44ad", 140),
            ("✏️ Manual Entry", self.show_manual_entry, "#e67e22", "#d35400", 140),
            ("📤 Export", self.export_accounts, "#17a2b8", "#138496", 100),
            ("📥 Import", self.import_accounts, "#28a745", "#218838", 100)
        ]
        
        for i, (text, command, bg, hover, width) in enumerate(buttons_config):
            btn = ModernButton(button_container, text=text, command=command,
                             bg_color=bg, hover_color=hover, width=width)
            btn.pack(side=tk.LEFT, padx=(0, 15 if i < len(buttons_config)-1 else 0))
        
        # QR processing area (initially hidden)
        self.qr_frame = tk.Frame(actions_card, bg="#ffffff")
        self.qr_label = tk.Label(self.qr_frame, bg="#ffffff")
        self.qr_label.pack()
        base_font = get_system_font()
        self.qr_status = tk.Label(actions_card, bg="#ffffff", fg="#27ae60", 
                                 font=(base_font[0], base_font[1] + 1, "bold"))
        
        # Accounts list
        self.create_accounts_section(main_container)
        
        # Status bar
        self.create_status_bar(main_container)
    
    def create_accounts_section(self, parent):
        """Create the accounts list section"""
        list_card = ttk.Frame(parent, style="Card.TFrame", padding="25")
        list_card.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header_frame = tk.Frame(list_card, bg="#ffffff")
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(header_frame, text="💎 Your Accounts", style="Header.TLabel").pack(side=tk.LEFT)
        
        base_font = get_system_font()
        self.account_counter = ttk.Label(header_frame, text="0 accounts", 
                                        font=base_font, background="#ffffff", 
                                        foreground="#7f8c8d")
        self.account_counter.pack(side=tk.RIGHT)
        
        # Treeview
        tree_frame = tk.Frame(list_card, bg="#ffffff")
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ('Service', 'Account', 'Code', 'Time Left', 'Added', 'Actions')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings', 
                                style="Modern.Treeview", height=12)
        
        # Configure columns
        column_config = {
            'Service': (150, 'Service'),
            'Account': (150, 'Account'),
            'Code': (120, 'Current Code', 'center'),
            'Time Left': (80, 'Time Left', 'center'),
            'Added': (120, 'Date Added', 'center'),
            'Actions': (120, 'Actions', 'center')
        }
        
        for col, config in column_config.items():
            self.tree.heading(col, text=config[1])
            anchor = config[2] if len(config) > 2 else 'w'
            self.tree.column(col, width=config[0], minwidth=config[0]//2, anchor=anchor)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Event bindings
        self.tree.bind('<Double-1>', self.copy_code_to_clipboard)
        self.tree.bind('<Button-1>', self.handle_tree_click)
        self.tree.bind('<ButtonRelease-1>', self.on_single_click)
    
    def create_status_bar(self, parent):
        """Create status bar"""
        status_frame = tk.Frame(parent, bg="#34495e", height=35)
        status_frame.pack(fill=tk.X, pady=(15, 0))
        status_frame.pack_propagate(False)
        
        self.status_var = tk.StringVar(value="🚀 Ready - Click accounts to copy codes")
        base_font = get_system_font()
        status_label = tk.Label(status_frame, textvariable=self.status_var, 
                               bg="#34495e", fg="white", font=base_font)
        status_label.pack(expand=True)
    
    def create_notification_system(self):
        """Create permanent blue status bar at the top"""
        self.notification_frame = tk.Frame(self.root, bg="#3498db", height=35)
        self.notification_frame.pack(side=tk.TOP, fill=tk.X)
        self.notification_frame.pack_propagate(False)
        
        base_font = get_system_font()
        self.notification_label = tk.Label(self.notification_frame, 
                                          bg="#3498db", fg="white", 
                                          font=(base_font[0], base_font[1] + 1, "bold"),
                                          text="🚀 Ready - Click accounts to copy codes")
        self.notification_label.pack(expand=True)
    
    def show_notification(self, message, duration=2000, color="#3498db"):
        """Update the permanent notification bar"""
        try:
            self.notification_label.configure(text=message, bg=color)
            self.notification_frame.configure(bg=color)
            
            # Auto-revert to default message after duration
            self.root.after(duration, lambda: self.notification_label.configure(
                text="🚀 Ready - Click accounts to copy codes", bg="#3498db"))
            self.root.after(duration, lambda: self.notification_frame.configure(bg="#3498db"))
        except Exception as e:
            logger.error(f"Notification error: {e}")
    
    def hide_notification(self):
        """Hide the notification"""
        self.notification_frame.configure(height=0)
        self.notification_label.configure(text="")
    
    def prompt_password(self):
        """No longer needed - removed password functionality"""
        pass
    
    def paste_qr_from_clipboard(self):
        """Paste and process QR code from clipboard"""
        try:
            self.status_var.set("🔍 Getting image from clipboard...")
            self.root.update()
            
            image = get_clipboard_image()
            if image is None:
                messagebox.showwarning("⚠️ No Image", 
                    "No image found in clipboard.\n\n"
                    "On Linux, make sure you have xclip or wl-clipboard installed:\n"
                    "sudo apt-get install xclip wl-clipboard")
                return
                
            self.process_qr_image(image)
            
        except Exception as e:
            logger.error(f"Clipboard paste error: {e}")
            messagebox.showerror("❌ Error", f"Failed to paste from clipboard: {str(e)}\n\n"
                "Try using 'Load from File' instead, or install clipboard tools:\n"
                "sudo apt-get install xclip wl-clipboard")
    
    def load_qr_from_file(self):
        """Load and process QR code from file"""
        file_path = filedialog.askopenfilename(
            title="Select QR Code Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp *.tiff")]
        )
        
        if file_path:
            try:
                image = Image.open(file_path)
                self.process_qr_image(image)
            except Exception as e:
                messagebox.showerror("❌ Error", f"Failed to load image: {str(e)}")
    
    def process_qr_image(self, image):
        """Process QR code image and add account"""
        try:
            # Show preview
            self.show_qr_preview(image)
            self.status_var.set("🔍 Scanning QR code...")
            self.root.update()
            
            # Extract and add account
            qr_data = self.manager.extract_secret_from_image(image)
            
            if qr_data and self.manager.add_account_from_qr(qr_data):
                if self.manager.save_secrets():
                    account_name = f"{qr_data['issuer']} - {qr_data['account']}"
                    self.show_success_message(f"✅ Added: {account_name}")
                    self.refresh_accounts_list()
                else:
                    messagebox.showerror("❌ Error", "Failed to save account")
                    
            else:
                messagebox.showerror("❌ QR Error", "No valid 2FA QR code found")
                
        except Exception as e:
            messagebox.showerror("❌ Error", f"Failed to process QR code: {str(e)}")
        finally:
            self.clear_qr_display()
    
    def show_manual_entry(self):
        """Show manual entry dialog"""
        logger.info("Creating ManualEntryDialog...")
        try:
            dialog = ManualEntryDialog(self.root)
            logger.info(f"Dialog created, result: {dialog.result}")
            if dialog.result:
                data = dialog.result
                if self.manager.add_account_manual(data['account'], data['secret'], data['issuer']):
                    if self.manager.save_secrets():
                        self.refresh_accounts_list()
                        self.status_var.set(f"✅ Added: {data['issuer']} - {data['account']}")
                        self.root.after(3000, lambda: self.status_var.set("🚀 Ready - Click accounts to copy codes"))
                    else:
                        messagebox.showerror("❌ Error", "Failed to save account")
                else:
                    messagebox.showerror("❌ Error", "Invalid secret data")
            else:
                logger.info("Dialog was cancelled or closed without input")
        except Exception as e:
            logger.error(f"Error creating/showing manual entry dialog: {e}")
            messagebox.showerror("Dialog Error", f"Failed to show dialog: {e}")
    
    def show_qr_preview(self, image):
        """Show QR code preview"""
        display_image = image.copy()
        display_image.thumbnail((150, 150), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(display_image)
        
        self.qr_frame.pack(pady=(15, 10))
        self.qr_label.configure(image=photo, text="")
        self.qr_label.image = photo  # Keep reference
    
    def show_success_message(self, message):
        """Show success message in QR area"""
        self.qr_status.configure(text=message)
        self.qr_status.pack(pady=(5, 10))
        self.status_var.set("🎉 Account added successfully!")
        self.root.after(3000, self.clear_qr_display)
    
    def clear_qr_display(self):
        """Clear QR display area"""
        self.qr_frame.pack_forget()
        self.qr_status.pack_forget()
        self.qr_label.configure(image="", text="")
        if hasattr(self.qr_label, 'image'):
            delattr(self.qr_label, 'image')
        self.status_var.set("🚀 Ready - Click accounts to copy codes")
    
    def export_accounts(self):
        """Export accounts to file"""
        if not self.manager.secrets:
            messagebox.showinfo("ℹ️ No Accounts", "No accounts to export")
            return
            
        file_path = filedialog.asksaveasfilename(
            title="Export Accounts",
            defaultextension=".2fa",
            filetypes=[("2FA Files", "*.2fa"), ("All Files", "*.*")]
        )
        
        if not file_path:
            return
            
        try:
            export_data = {
                'version': '1.0',
                'accounts': self.manager.secrets,
                'exported_at': time.time()
            }
            
            with open(file_path, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            messagebox.showinfo("🎉 Export Complete", 
                               f"Exported {len(self.manager.secrets)} accounts")
            
        except Exception as e:
            messagebox.showerror("❌ Export Error", f"Failed to export: {str(e)}")
    
    def import_accounts(self):
        """Import accounts from file"""
        file_path = filedialog.askopenfilename(
            title="Import Accounts",
            filetypes=[("2FA Files", "*.2fa"), ("All Files", "*.*")]
        )
        
        if not file_path:
            return
            
        try:
            with open(file_path, 'r') as f:
                import_data = json.load(f)
            
            imported_accounts = import_data['accounts']
            conflicts = [name for name in imported_accounts if name in self.manager.secrets]
            
            if conflicts:
                result = messagebox.askyesnocancel(
                    "🔄 Import Conflicts", 
                    f"Found {len(conflicts)} conflicts.\n\n"
                    f"Yes = Replace conflicts\nNo = Skip conflicts\nCancel = Abort"
                )
                
                if result is None:
                    return
                elif not result:  # Skip conflicts
                    imported_accounts = {k: v for k, v in imported_accounts.items() 
                                       if k not in self.manager.secrets}
            
            self.manager.secrets.update(imported_accounts)
            
            if self.manager.save_secrets():
                messagebox.showinfo("🎉 Import Complete", 
                                   f"Imported {len(imported_accounts)} accounts")
                self.refresh_accounts_list()
            else:
                messagebox.showerror("❌ Error", "Failed to save imported accounts")
                
        except Exception as e:
            messagebox.showerror("❌ Import Error", f"Failed to import: {str(e)}")
    
    def refresh_accounts_list(self):
        """Refresh the accounts list"""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        self.account_mapping.clear()
        
        # Add accounts
        accounts = self.manager.list_accounts()
        self.account_counter.configure(text=f"{len(accounts)} accounts")
        
        for account_key, info in accounts.items():
            code = self.manager.generate_code(account_key)
            time_left = self.manager.get_time_remaining()
            added_date = datetime.fromtimestamp(info['added']).strftime("%m/%d/%Y") if info['added'] else "Unknown"
            
            values = (
                info['issuer'],
                info['account'],
                code,
                f"{time_left}s",
                added_date,
                "📝🗑️"
            )
            
            item = self.tree.insert('', 'end', values=values)
            self.account_mapping[item] = account_key
    
    def handle_tree_click(self, event):
        """Handle clicks on tree items for rename/delete buttons"""
        region = self.tree.identify_region(event.x, event.y)
        if region == "cell":
            column = self.tree.identify_column(event.x)
            if column == '#6':  # Actions column
                item = self.tree.identify_row(event.y)
                if item and item in self.account_mapping:
                    bbox = self.tree.bbox(item, column)
                    if bbox:
                        relative_x = event.x - bbox[0]
                        if relative_x < bbox[2] / 2:
                            self.rename_account(item)
                        else:
                            self.delete_account(item)
                        # Prevent single click copy for action buttons
                        return "break"
        # Return None to allow single click copy for other areas
        return None
    
    def on_single_click(self, event):
        """Handle single click to copy code"""
        region = self.tree.identify_region(event.x, event.y)
        column = self.tree.identify_column(event.x)
        
        # Don't copy if clicked on Actions column (handled by handle_tree_click)
        if column == '#6':
            return
            
        # Only copy if clicked on a valid row (not header or empty space)
        if region == "cell":
            item = self.tree.identify_row(event.y)
            if item and item in self.account_mapping:
                # Get the code from the row
                values = self.tree.item(item)['values']
                if len(values) >= 3:  # Make sure code exists
                    code = values[2]  # Code is in 3rd column
                    if code and code != "":
                        self.root.clipboard_clear()
                        self.root.clipboard_append(code)
                        
                        # Get account info for status message
                        service = values[0]
                        account = values[1]
                        
                        # Show subtle notification
                        self.show_notification(f"📋 Copied: {code} ({service})", 2000, "#3498db")
                        
                        self.status_var.set(f"📋 Code {code} copied! ({service} - {account})")
                        self.root.after(3000, lambda: self.status_var.set("🚀 Ready - Click accounts to copy codes"))
    
    def rename_account(self, item):
        """Enhanced rename dialog for both service and account"""
        account_key = self.account_mapping.get(item)
        if not account_key:
            return
            
        values = self.tree.item(item)['values']
        current_service = values[0]
        current_account = values[1]
        
        # Create custom rename dialog
        dialog = RenameDialog(self.root, current_service, current_account)
        
        if dialog.result:
            new_service = dialog.result['service']
            new_account = dialog.result['account']
            
            # Update the account data
            if account_key in self.manager.secrets:
                account_data = self.manager.secrets[account_key].copy()
                account_data['issuer'] = new_service
                account_data['account'] = new_account
                
                # Create new unique key
                new_key = f"{new_service}_{new_account}"
                counter = 1
                while new_key in self.manager.secrets and new_key != account_key:
                    new_key = f"{new_service}_{new_account}_{counter}"
                    counter += 1
                
                # Update or replace the account
                if new_key != account_key:
                    del self.manager.secrets[account_key]
                self.manager.secrets[new_key] = account_data
                
                # Save and refresh
                if self.manager.save_secrets():
                    self.refresh_accounts_list()
                    self.status_var.set(f"✏️ Renamed to '{new_service} - {new_account}'")
                    self.root.after(3000, lambda: self.status_var.set("🚀 Ready - Click accounts to copy codes"))
                else:
                    messagebox.showerror("❌ Error", "Failed to save changes")
            else:
                messagebox.showerror("❌ Error", "Account not found")
    
    def delete_account(self, item):
        """Delete an account"""
        account_key = self.account_mapping.get(item)
        if not account_key:
            return
            
        values = self.tree.item(item)['values']
        display_name = f"{values[0]} - {values[1]}"
        
        if messagebox.askyesno("🗑️ Confirm Removal", 
                              f"Remove '{display_name}'?\n\nThis cannot be undone."):
            if self.manager.remove_account(account_key):
                if self.manager.save_secrets():
                    self.refresh_accounts_list()
                    self.status_var.set(f"🗑️ Removed '{display_name}'")
                    self.root.after(3000, lambda: self.status_var.set("🚀 Ready - Click accounts to copy codes"))
                else:
                    messagebox.showerror("❌ Error", "Failed to save changes")
    
    def copy_code_to_clipboard(self, event):
        """Copy code to clipboard on double-click"""
        selection = self.tree.selection()
        if not selection:
            return
            
        item = self.tree.item(selection[0])
        code = item['values'][2]
        
        self.root.clipboard_clear()
        self.root.clipboard_append(code)
        self.status_var.set(f"📋 Code {code} copied!")
        self.root.after(3000, lambda: self.status_var.set("🚀 Ready - Click accounts to copy codes"))
    
    def start_update_thread(self):
        """Start background thread for updating codes"""
        self.running = True
        self.update_thread = threading.Thread(target=self.update_codes_loop, daemon=True)
        self.update_thread.start()
    
    def update_codes_loop(self):
        """Background loop to update codes every second"""
        while self.running:
            try:
                self.root.after(0, self.update_codes)
                time.sleep(1)
            except:
                break
    
    def update_codes(self):
        """Update displayed codes and time remaining"""
        if not self.running:
            return
            
        for item in self.tree.get_children():
            account_key = self.account_mapping.get(item)
            if account_key and account_key in self.manager.secrets:
                code = self.manager.generate_code(account_key)
                time_left = self.manager.get_time_remaining()
                
                values = list(self.tree.item(item)['values'])
                values[2] = code
                values[3] = f"{time_left}s"
                self.tree.item(item, values=values)
    
    def on_closing(self):
        """Handle window closing"""
        self.running = False
        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=1)
        self.root.destroy()

class RenameDialog:
    """Enhanced dialog for renaming both service and account"""
    
    def __init__(self, parent, current_service, current_account):
        self.result = None
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("✏️ Rename Account")
        self.dialog.geometry("650x500")
        self.dialog.configure(bg="#f8f9fa")
        self.dialog.transient(parent)
        # Don't grab_set until after widgets are created and dialog is visible
        self.dialog.resizable(True, True)
        self.dialog.minsize(550, 400)
        
        # Center dialog
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        
        dialog_width = 650
        dialog_height = 500
        
        x = parent_x + (parent_width // 2) - (dialog_width // 2)
        y = parent_y + (parent_height // 2) - (dialog_height // 2)
        
        self.dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        
        # Linux compatibility fixes
        self.dialog.lift()
        self.dialog.attributes('-topmost', True)
        self.dialog.focus_force()
        
        self.current_service = current_service
        self.current_account = current_account
        
        self.create_widgets()
        
        # Ensure dialog is properly displayed on Linux
        self.dialog.update_idletasks()
        self.dialog.attributes('-topmost', False)
        
        # Now that dialog is fully created and visible, set grab
        try:
            self.dialog.grab_set()
            logger.info("RenameDialog grab set successfully")
        except Exception as e:
            logger.warning(f"RenameDialog could not set grab: {e}")
        
        parent.wait_window(self.dialog)
    
    def create_widgets(self):
        """Create dialog widgets with proper expansion"""
        # Get system-appropriate font
        base_font = get_system_font()
        title_font = (base_font[0], base_font[1] + 6, "bold")
        subtitle_font = (base_font[0], base_font[1] + 1)
        
        # Force dialog to render properly
        self.dialog.update()
        
        main_frame = tk.Frame(self.dialog, bg="#ffffff", relief="solid", bd=1)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Configure grid weights for expansion
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(3, weight=1)  # Make middle section expandable
        
        # Title
        title_label = tk.Label(main_frame, text="Rename Account", 
                              font=title_font, bg="#ffffff", fg="#2c3e50")
        title_label.grid(row=0, column=0, pady=(15, 8), sticky="ew")
        
        # Subtitle
        subtitle_label = tk.Label(main_frame, text="Update both service name and account name", 
                                 font=subtitle_font, bg="#ffffff", fg="#7f8c8d")
        subtitle_label.grid(row=1, column=0, pady=(0, 20), sticky="ew")
        
        # Fields container
        fields_frame = tk.Frame(main_frame, bg="#ffffff")
        fields_frame.grid(row=2, column=0, sticky="ew", pady=(0, 15))
        fields_frame.grid_columnconfigure(0, weight=1)
        
        # Service name field
        field_font = (base_font[0], base_font[1] + 1, "bold")
        entry_font = (base_font[0], base_font[1] + 1)
        
        service_label = tk.Label(fields_frame, text="Service/Issuer:", 
                               font=field_font, bg="#ffffff", fg="#34495e")
        service_label.grid(row=0, column=0, sticky="w", pady=(0, 5))
        
        self.service_var = tk.StringVar(value=self.current_service)
        self.service_entry = tk.Entry(fields_frame, textvariable=self.service_var,
                                    font=entry_font, relief="solid", bd=1,
                                    highlightthickness=1, highlightcolor="#3498db")
        self.service_entry.grid(row=1, column=0, sticky="ew", pady=(0, 15), ipady=8)
        
        # Account name field
        account_label = tk.Label(fields_frame, text="Account Name:", 
                               font=field_font, bg="#ffffff", fg="#34495e")
        account_label.grid(row=2, column=0, sticky="w", pady=(0, 5))
        
        self.account_var = tk.StringVar(value=self.current_account)
        self.account_entry = tk.Entry(fields_frame, textvariable=self.account_var,
                                    font=entry_font, relief="solid", bd=1,
                                    highlightthickness=1, highlightcolor="#3498db")
        self.account_entry.grid(row=3, column=0, sticky="ew", pady=(0, 15), ipady=8)
        
        # Expandable spacer
        spacer_frame = tk.Frame(main_frame, bg="#ffffff")
        spacer_frame.grid(row=3, column=0, sticky="nsew")
        
        # Buttons at bottom
        button_frame = tk.Frame(main_frame, bg="#ffffff")
        button_frame.grid(row=4, column=0, pady=(15, 15))
        
        save_btn = ModernButton(button_frame, text="✅ Save Changes", command=self.accept,
                               bg_color="#27ae60", hover_color="#229954", width=140, height=40)
        save_btn.pack(side=tk.LEFT, padx=(0, 15))
        
        cancel_btn = ModernButton(button_frame, text="❌ Cancel", command=self.cancel,
                                 bg_color="#e74c3c", hover_color="#c0392b", width=100, height=40)
        cancel_btn.pack(side=tk.LEFT)
        
        # Focus service entry and select all
        self.service_entry.focus()
        self.service_entry.select_range(0, tk.END)
    
    def accept(self):
        """Accept dialog input"""
        service = self.service_var.get().strip()
        account = self.account_var.get().strip()
        
        if not service:
            messagebox.showerror("❌ Error", "Please enter a service name")
            return
            
        if not account:
            messagebox.showerror("❌ Error", "Please enter an account name")
            return
        
        # Check if anything actually changed
        if service == self.current_service and account == self.current_account:
            self.dialog.destroy()
            return
        
        self.result = {
            'service': service,
            'account': account
        }
        self.dialog.destroy()
    
    def cancel(self):
        """Cancel dialog"""
        self.dialog.destroy()

class ManualEntryDialog:
    """Dialog for manual 2FA entry"""
    
    def __init__(self, parent):
        logger.info("ManualEntryDialog.__init__ started")
        self.result = None
        
        self.dialog = tk.Toplevel(parent)
        logger.info("Toplevel created")
        self.dialog.title("✏️ Manual 2FA Entry")
        self.dialog.geometry("650x600")  # Increased height from 500 to 600
        self.dialog.configure(bg="#f8f9fa")
        self.dialog.transient(parent)
        # Don't grab_set until after widgets are created and dialog is visible
        self.dialog.resizable(True, True)
        self.dialog.minsize(550, 500)  # Increased minimum height too
        logger.info("Dialog basic setup complete")
        
        # Center dialog - EXACTLY like rename dialog
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        
        dialog_width = 650
        dialog_height = 600  # Updated to match new size
        
        x = parent_x + (parent_width // 2) - (dialog_width // 2)
        y = parent_y + (parent_height // 2) - (dialog_height // 2)
        
        self.dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        logger.info(f"Dialog positioned at {x},{y}")
        
        # Linux compatibility fixes
        self.dialog.lift()
        self.dialog.attributes('-topmost', True)
        self.dialog.focus_force()
        logger.info("Dialog visibility setup complete")
        
        self.create_widgets()
        logger.info("Widgets created")
        
        # Ensure dialog is properly displayed on Linux
        self.dialog.update_idletasks()
        self.dialog.attributes('-topmost', False)
        
        # Now that dialog is fully created and visible, set grab
        try:
            self.dialog.grab_set()
            logger.info("Grab set successfully")
        except Exception as e:
            logger.warning(f"Could not set grab: {e}")
        
        logger.info("About to wait for dialog...")
        
        parent.wait_window(self.dialog)
        logger.info("Dialog closed")
    
    def create_widgets(self):
        """Create dialog widgets - Linux compatible version"""
        # Get system-appropriate font
        base_font = get_system_font()
        title_font = (base_font[0], base_font[1] + 6, "bold")
        subtitle_font = (base_font[0], base_font[1] + 1)
        field_font = (base_font[0], base_font[1] + 1, "bold")
        entry_font = (base_font[0], base_font[1] + 1)
        
        # Force dialog to render properly
        self.dialog.update()
        
        # Main frame with visible border for debugging
        main_frame = tk.Frame(self.dialog, bg="#ffffff", relief="solid", bd=1)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Configure grid weights
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(3, weight=1)  # Make middle section expandable
        
        # Title
        title_label = tk.Label(main_frame, text="Manual 2FA Setup", 
                              font=title_font, bg="#ffffff", fg="#2c3e50")
        title_label.grid(row=0, column=0, pady=(15, 8), sticky="ew")
        
        # Subtitle
        subtitle_label = tk.Label(main_frame, text="Enter your 2FA secret key manually", 
                                 font=subtitle_font, bg="#ffffff", fg="#7f8c8d")
        subtitle_label.grid(row=1, column=0, pady=(0, 20), sticky="ew")
        
        # Fields container - EXACTLY like rename dialog
        fields_frame = tk.Frame(main_frame, bg="#ffffff")
        fields_frame.grid(row=2, column=0, sticky="ew", pady=(0, 15))
        fields_frame.grid_columnconfigure(0, weight=1)
        
        # Service field
        service_label = tk.Label(fields_frame, text="Service/Issuer:", 
                               font=field_font, bg="#ffffff", fg="#34495e")
        service_label.grid(row=0, column=0, sticky="w", pady=(0, 5))
        
        self.service_var = tk.StringVar()
        self.service_entry = tk.Entry(fields_frame, textvariable=self.service_var,
                                    font=entry_font, relief="solid", bd=1,
                                    highlightthickness=1, highlightcolor="#3498db")
        self.service_entry.grid(row=1, column=0, sticky="ew", pady=(0, 15), ipady=8)
        
        # Account field
        account_label = tk.Label(fields_frame, text="Account Name:", 
                               font=field_font, bg="#ffffff", fg="#34495e")
        account_label.grid(row=2, column=0, sticky="w", pady=(0, 5))
        
        self.account_var = tk.StringVar()
        self.account_entry = tk.Entry(fields_frame, textvariable=self.account_var,
                                    font=entry_font, relief="solid", bd=1,
                                    highlightthickness=1, highlightcolor="#3498db")
        self.account_entry.grid(row=3, column=0, sticky="ew", pady=(0, 15), ipady=8)
        
        # Secret field
        secret_label = tk.Label(fields_frame, text="Secret Key:", 
                              font=field_font, bg="#ffffff", fg="#34495e")
        secret_label.grid(row=4, column=0, sticky="w", pady=(0, 5))
        
        self.secret_var = tk.StringVar()
        self.secret_entry = tk.Entry(fields_frame, textvariable=self.secret_var,
                                   font=entry_font, show="*", relief="solid", bd=1,
                                   highlightthickness=1, highlightcolor="#3498db")
        self.secret_entry.grid(row=5, column=0, sticky="ew", pady=(0, 10), ipady=8)
        
        # Show/hide toggle
        checkbox_font = (base_font[0], base_font[1])
        self.show_var = tk.BooleanVar()
        show_check = tk.Checkbutton(fields_frame, text="Show secret key", variable=self.show_var,
                                   font=checkbox_font, bg="#ffffff", fg="#7f8c8d",
                                   command=lambda: self.secret_entry.configure(
                                       show="" if self.show_var.get() else "*"))
        show_check.grid(row=6, column=0, sticky="w", pady=(0, 15))
        
        
        # Expandable spacer - EXACTLY like rename dialog
        spacer_frame = tk.Frame(main_frame, bg="#ffffff")
        spacer_frame.grid(row=3, column=0, sticky="nsew")
        
        # Buttons at bottom - EXACTLY like rename dialog
        button_frame = tk.Frame(main_frame, bg="#ffffff")
        button_frame.grid(row=4, column=0, pady=(15, 15))
        
        save_btn = ModernButton(button_frame, text="✅ Add Account", command=self.accept,
                               bg_color="#27ae60", hover_color="#229954", width=140, height=40)
        save_btn.pack(side=tk.LEFT, padx=(0, 15))
        
        cancel_btn = ModernButton(button_frame, text="❌ Cancel", command=self.cancel,
                                 bg_color="#e74c3c", hover_color="#c0392b", width=100, height=40)
        cancel_btn.pack(side=tk.LEFT)
        
        # Focus first entry and select all - EXACTLY like rename dialog
        self.service_entry.focus()
        self.service_entry.select_range(0, tk.END)
    
    def accept(self):
        """Accept dialog input"""
        service = self.service_var.get().strip() or "Manual"
        account_name = self.account_var.get().strip()
        secret = self.secret_var.get().strip()
        
        if not account_name:
            messagebox.showerror("❌ Error", "Please enter an account name")
            return
            
        if not secret:
            messagebox.showerror("❌ Error", "Please enter the secret key")
            return
        
        if len(secret.replace(' ', '').replace('-', '')) < MIN_SECRET_LENGTH:
            messagebox.showerror("❌ Error", "Secret key seems too short. Make sure you copied the full key.")
            return
        
        self.result = {
            'issuer': service,
            'account': account_name,
            'secret': secret
        }
        self.dialog.destroy()
    
    def cancel(self):
        """Cancel dialog"""
        self.dialog.destroy()

def main():
    """Main application entry point"""
    try:
        logger.info(f"Starting 2FA Manager v{APP_VERSION}")
        root = tk.Tk()
        app = TOTPManagerGUI(root)
        root.protocol("WM_DELETE_WINDOW", app.on_closing)
        root.mainloop()
        logger.info("Application closed successfully")
    except Exception as e:
        logger.error(f"Application startup failed: {e}")
        messagebox.showerror("Fatal Error", f"Failed to start application:\n{e}")

if __name__ == "__main__":
    main()