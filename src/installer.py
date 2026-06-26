import os
import sys
import shutil
import socket
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import winreg
import subprocess

def get_resource_path(relative_path):
    """Obtiene la ruta absoluta para un recurso, funciona en desarrollo y con PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class InstallerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Instalador de monitorPC Agent")
        self.root.geometry("520x380")
        self.root.resizable(False, False)
        
        # Color Palette
        self.bg_color = "#12131C"
        self.surface_color = "#1E1F2E"
        self.accent_green = "#00FF66"
        self.text_white = "#FFFFFF"
        self.text_gray = "#8F909A"
        
        self.root.configure(bg=self.bg_color)
        
        # Set Window Icon
        try:
            icon_path = get_resource_path("app_icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass
        
        # Center Window
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - 520) // 2
        y = (screen_height - 380) // 2
        self.root.geometry(f"520x380+{x}+{y}")
        
        # Installation State Variables
        username = os.environ.get("USERNAME", "Usuario")
        self.default_install_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", f"C:\\Users\\{username}\\AppData\\Local"),
            "Programs", "monitorPC-Agent"
        )
        self.install_dir = tk.StringVar(value=self.default_install_dir)
        self.start_with_windows = tk.BooleanVar(value=True)
        self.create_desktop_shortcut = tk.BooleanVar(value=True)
        self.create_start_menu_shortcut = tk.BooleanVar(value=True)
        self.run_now = tk.BooleanVar(value=True)
        
        # Current screen index (0 to 4)
        self.current_screen = 0
        
        # Main layout containers
        self.header_frame = tk.Frame(self.root, bg=self.surface_color, height=70)
        self.header_frame.pack(fill="x", side="top")
        self.header_frame.pack_propagate(False)
        
        self.header_title = tk.Label(
            self.header_frame, text="Instalador de monitorPC Agent", 
            font=("Helvetica", 14, "bold"), fg=self.accent_green, bg=self.surface_color
        )
        self.header_title.pack(anchor="w", padx=20, pady=(15, 2))
        
        self.header_desc = tk.Label(
            self.header_frame, text="Asistente de instalación del agente de monitoreo",
            font=("Helvetica", 9), fg=self.text_gray, bg=self.surface_color
        )
        self.header_desc.pack(anchor="w", padx=20)
        
        # Separator line
        self.sep1 = tk.Frame(self.root, height=1, bg="#2C2E3E")
        self.sep1.pack(fill="x")
        
        # Content Area
        self.content_frame = tk.Frame(self.root, bg=self.bg_color)
        self.content_frame.pack(fill="both", expand=True, padx=25, pady=20)
        
        # Bottom Separator
        self.sep2 = tk.Frame(self.root, height=1, bg="#2C2E3E")
        self.sep2.pack(fill="x", side="bottom", pady=(0, 60))
        
        # Bottom Navigation Buttons Frame
        self.nav_frame = tk.Frame(self.root, bg=self.bg_color)
        self.nav_frame.place(x=0, y=325, width=520, height=55)
        
        self.btn_back = tk.Button(
            self.nav_frame, text="< Atrás", font=("Helvetica", 10),
            fg=self.text_white, bg="#2C2E3E", activebackground="#3D4057", activeforeground=self.text_white,
            relief="flat", width=10, command=self.go_back
        )
        self.btn_back.pack(side="left", padx=(25, 0), pady=12)
        
        self.btn_cancel = tk.Button(
            self.nav_frame, text="Cancelar", font=("Helvetica", 10),
            fg=self.text_white, bg="#2C2E3E", activebackground="#3D4057", activeforeground=self.text_white,
            relief="flat", width=10, command=self.cancel_install
        )
        self.btn_cancel.pack(side="right", padx=(0, 25), pady=12)
        
        self.btn_next = tk.Button(
            self.nav_frame, text="Siguiente >", font=("Helvetica", 10, "bold"),
            fg="#0C1D0F", bg=self.accent_green, activebackground="#00CC52", activeforeground="#0C1D0F",
            relief="flat", width=12, command=self.go_next
        )
        self.btn_next.pack(side="right", padx=(0, 10), pady=12)
        
        # Show first screen
        self.load_screen()
        
        # Check if already installed in system
        self.root.after(100, self.check_existing_installation)

    def check_existing_installation(self):
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\monitorPC-Agent"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            install_location, _ = winreg.QueryValueEx(key, "InstallLocation")
            winreg.CloseKey(key)
            
            if install_location and os.path.exists(install_location):
                self.root.after(100, lambda: self.prompt_uninstall_existing(install_location))
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Error checking existing installation: {e}")

    def prompt_uninstall_existing(self, install_location):
        ans = messagebox.askyesno(
            "Versión Existente Detectada",
            "Se ha detectado una versión de monitorPC Agent ya instalada en el sistema.\n\n"
            "¿Desea desinstalar la versión existente y borrar todos sus archivos correspondientes antes de continuar con la instalación?",
            parent=self.root
        )
        if ans:
            self.uninstall_existing_version(install_location)
        else:
            self.root.destroy()
            sys.exit(0)

    def uninstall_existing_version(self, install_location):
        try:
            # 1. Kill active processes
            subprocess.run(["taskkill", "/F", "/IM", "monitorPC-Agent.exe"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(0.5)

            # 2. Delete Shortcuts
            desktop_lnk = os.path.join(os.environ["USERPROFILE"], "Desktop", "monitorPC Agent.lnk")
            if os.path.exists(desktop_lnk):
                try:
                    os.remove(desktop_lnk)
                except Exception:
                    pass
            start_menu_lnk = os.path.join(
                os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "monitorPC Agent.lnk"
            )
            if os.path.exists(start_menu_lnk):
                try:
                    os.remove(start_menu_lnk)
                except Exception:
                    pass

            # 3. Delete Startup key
            try:
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
                winreg.DeleteValue(key, "monitorPC-Agent")
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass
            except Exception:
                pass

            # 4. Delete Uninstall key
            try:
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
                winreg.DeleteKey(key, "monitorPC-Agent")
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass
            except Exception:
                pass

            # 5. Delete directory files and folder
            if os.path.exists(install_location):
                for item in os.listdir(install_location):
                    item_path = os.path.join(install_location, item)
                    try:
                        if os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                        else:
                            os.remove(item_path)
                    except Exception as err:
                        print(f"Error al eliminar {item_path}: {err}")
                
                try:
                    os.rmdir(install_location)
                except Exception:
                    pass

            messagebox.showinfo(
                "Desinstalación Completada",
                "La versión anterior se ha desinstalado y sus archivos se han borrado correctamente.\n\n"
                "Ahora se continuará con el asistente de instalación.",
                parent=self.root
            )
        except Exception as e:
            messagebox.showwarning(
                "Advertencia de Desinstalación",
                f"No se pudieron eliminar por completo todos los archivos de la versión anterior:\n{str(e)}\n\n"
                "La instalación continuará.",
                parent=self.root
            )

    def load_screen(self):
        for child in self.content_frame.winfo_children():
            child.destroy()
            
        if self.current_screen == 0:
            self.btn_back.configure(state="disabled")
            self.btn_next.configure(text="Siguiente >", state="normal")
            self.btn_cancel.configure(state="normal")
        elif self.current_screen in (1, 2):
            self.btn_back.configure(state="normal")
            self.btn_next.configure(text="Siguiente >" if self.current_screen == 1 else "Instalar", state="normal")
            self.btn_cancel.configure(state="normal")
        elif self.current_screen == 3:  # Installing
            self.btn_back.configure(state="disabled")
            self.btn_next.configure(state="disabled")
            self.btn_cancel.configure(state="disabled")
        elif self.current_screen == 4:  # Finished
            self.btn_back.configure(state="disabled")
            self.btn_next.configure(text="Finalizar", state="normal")
            self.btn_cancel.configure(state="disabled")
            
        if self.current_screen == 0:
            self.render_welcome()
        elif self.current_screen == 1:
            self.render_directory()
        elif self.current_screen == 2:
            self.render_ready()
        elif self.current_screen == 3:
            self.render_installing()
        elif self.current_screen == 4:
            self.render_finished()

    def go_back(self):
        if self.current_screen > 0:
            self.current_screen -= 1
            self.load_screen()

    def go_next(self):
        if self.current_screen == 2:
            self.current_screen = 3
            self.load_screen()
            threading.Thread(target=self.perform_installation, daemon=True).start()
        elif self.current_screen == 4:
            self.finish_installation()
        else:
            self.current_screen += 1
            self.load_screen()

    def cancel_install(self):
        if messagebox.askyesno("Confirmar Cancelación", "¿Está seguro de que desea salir del instalador?"):
            self.root.destroy()

    # --- Screen Renders ---

    def render_welcome(self):
        self.header_title.configure(text="Bienvenido al Asistente de Instalación")
        self.header_desc.configure(text="Este asistente instalará monitorPC Agent en su computadora.")
        
        lbl_welcome = tk.Label(
            self.content_frame, 
            text="Este asistente de instalación configurará el agente de monitorPC en su sistema.\n\n"
                 "El agente recopila de manera segura métricas de hardware de su PC (CPU, RAM, GPU, Discos, Red y Captura de pantalla) "
                 "y las transmite a la aplicación móvil monitorPC en su red local.\n\n"
                 "Presione Siguiente para continuar.",
            font=("Helvetica", 10), fg=self.text_white, bg=self.bg_color, justify="left", wraplength=460
        )
        lbl_welcome.pack(anchor="w", pady=(10, 0))

    def render_directory(self):
        self.header_title.configure(text="Seleccionar Carpeta de Destino")
        self.header_desc.configure(text="¿Dónde desea instalar monitorPC Agent?")
        
        lbl_desc = tk.Label(
            self.content_frame, 
            text="El programa se instalará en la siguiente carpeta. Para instalar en una carpeta diferente, haga clic en Examinar y selecciónela.",
            font=("Helvetica", 10), fg=self.text_white, bg=self.bg_color, justify="left", wraplength=460
        )
        lbl_desc.pack(anchor="w", pady=(5, 15))
        
        dir_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        dir_frame.pack(fill="x", pady=5)
        
        ent_dir = tk.Entry(
            dir_frame, textvariable=self.install_dir, font=("Consolas", 10),
            bg=self.surface_color, fg=self.text_white, insertbackground=self.text_white,
            bd=1, relief="solid", highlightthickness=0
        )
        ent_dir.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 10))
        
        def browse_folder():
            selected = filedialog.askdirectory(initialdir=self.install_dir.get(), parent=self.root)
            if selected:
                normalized = os.path.normpath(selected)
                self.install_dir.set(normalized)
                
        btn_browse = tk.Button(
            dir_frame, text="Examinar...", font=("Helvetica", 9),
            fg=self.text_white, bg="#2C2E3E", activebackground="#3D4057", activeforeground=self.text_white,
            relief="flat", padx=10, command=browse_folder
        )
        btn_browse.pack(side="right")
        
        lbl_note = tk.Label(
            self.content_frame, 
            text="Nota: Se instalará en su carpeta de usuario local, por lo que no requiere privilegios de administrador para la instalación ni para ejecutarse.",
            font=("Helvetica", 9, "italic"), fg=self.text_gray, bg=self.bg_color, justify="left", wraplength=460
        )
        lbl_note.pack(anchor="w", pady=(20, 0))

    def render_ready(self):
        self.header_title.configure(text="Listo para Instalar")
        self.header_desc.configure(text="El asistente de instalación está listo para comenzar.")
        
        lbl_desc = tk.Label(
            self.content_frame,
            text="Haga clic en Instalar para iniciar el proceso de instalación. Si desea revisar o modificar alguna configuración, haga clic en Atrás.",
            font=("Helvetica", 10), fg=self.text_white, bg=self.bg_color, justify="left", wraplength=460
        )
        lbl_desc.pack(anchor="w", pady=(5, 15))
        
        summary_frame = tk.Frame(self.content_frame, bg=self.surface_color, bd=1, relief="solid", highlightbackground="#2C2E3E")
        summary_frame.pack(fill="x", pady=5)
        
        lbl_summary_title = tk.Label(
            summary_frame, text="Resumen de instalación:", font=("Helvetica", 10, "bold"),
            fg=self.accent_green, bg=self.surface_color
        )
        lbl_summary_title.pack(anchor="w", padx=15, pady=(10, 5))
        
        lbl_summary_path = tk.Label(
            summary_frame, text=f"Directorio: {self.install_dir.get()}", font=("Consolas", 9),
            fg=self.text_white, bg=self.surface_color, justify="left", wraplength=420
        )
        lbl_summary_path.pack(anchor="w", padx=15, pady=(0, 10))
        
        # Options Frame
        opt_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        opt_frame.pack(fill="x", pady=(10, 0))
        
        chk_startup = tk.Checkbutton(
            opt_frame, text="Iniciar monitorPC Agent al arrancar Windows",
            variable=self.start_with_windows, font=("Helvetica", 10),
            bg=self.bg_color, fg=self.text_white, activebackground=self.bg_color, activeforeground=self.text_white,
            selectcolor=self.surface_color, bd=0, highlightthickness=0
        )
        chk_startup.pack(anchor="w", pady=2)
        
        chk_desktop = tk.Checkbutton(
            opt_frame, text="Crear acceso directo en el Escritorio",
            variable=self.create_desktop_shortcut, font=("Helvetica", 10),
            bg=self.bg_color, fg=self.text_white, activebackground=self.bg_color, activeforeground=self.text_white,
            selectcolor=self.surface_color, bd=0, highlightthickness=0
        )
        chk_desktop.pack(anchor="w", pady=2)
        
        chk_start_menu = tk.Checkbutton(
            opt_frame, text="Crear acceso directo en el Menú Inicio",
            variable=self.create_start_menu_shortcut, font=("Helvetica", 10),
            bg=self.bg_color, fg=self.text_white, activebackground=self.bg_color, activeforeground=self.text_white,
            selectcolor=self.surface_color, bd=0, highlightthickness=0
        )
        chk_start_menu.pack(anchor="w", pady=2)

    def render_installing(self):
        self.header_title.configure(text="Instalando Archivos")
        self.header_desc.configure(text="Por favor espere mientras el asistente copia los archivos necesarios...")
        
        self.lbl_status = tk.Label(
            self.content_frame, text="Iniciando copia de archivos...", font=("Helvetica", 10),
            fg=self.text_white, bg=self.bg_color
        )
        self.lbl_status.pack(anchor="w", pady=(15, 5))
        
        progress_bg = tk.Frame(self.content_frame, height=22, bg=self.surface_color, bd=1, relief="solid", highlightbackground="#2C2E3E")
        progress_bg.pack(fill="x", pady=5)
        progress_bg.pack_propagate(False)
        
        self.progress_bar = tk.Frame(progress_bg, width=0, bg=self.accent_green)
        self.progress_bar.pack(side="left", fill="y")
        
        self.lbl_percent = tk.Label(
            self.content_frame, text="0%", font=("Helvetica", 10, "bold"),
            fg=self.accent_green, bg=self.bg_color
        )
        self.lbl_percent.pack(anchor="e", pady=(5, 0))

    def update_progress(self, percent, status_text):
        width = int(470 * (percent / 100.0))
        self.progress_bar.configure(width=width)
        self.lbl_status.configure(text=status_text)
        self.lbl_percent.configure(text=f"{percent}%")
        self.root.update_idletasks()

    def render_finished(self):
        self.header_title.configure(text="Instalación Finalizada")
        self.header_desc.configure(text="monitorPC Agent se ha instalado correctamente.")
        
        lbl_finished = tk.Label(
            self.content_frame,
            text="La instalación de monitorPC Agent en su equipo se ha completado con éxito.\n\n"
                 "El agente se ejecutará silenciosamente en la barra de tareas en la sección de iconos ocultos. "
                 "Haga clic en el acceso directo del escritorio o menú de inicio para iniciarlo si lo cierra.",
            font=("Helvetica", 10), fg=self.text_white, bg=self.bg_color, justify="left", wraplength=460
        )
        lbl_finished.pack(anchor="w", pady=(10, 20))
        
        chk_run = tk.Checkbutton(
            self.content_frame, text="Ejecutar monitorPC Agent ahora mismo",
            variable=self.run_now, font=("Helvetica", 10, "bold"),
            bg=self.bg_color, fg=self.accent_green, activebackground=self.bg_color, activeforeground=self.accent_green,
            selectcolor=self.surface_color, bd=0, highlightthickness=0
        )
        chk_run.pack(anchor="w")

    # --- Installation Actions ---

    def perform_installation(self):
        target_dir = self.install_dir.get()
        source_exe = get_resource_path("monitorPC-Agent.exe")
        
        if not os.path.exists(source_exe):
            source_exe = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dist", "monitorPC-Agent.exe"))
            
        try:
            # 0. Kill existing process if running to unlock file
            self.update_progress(5, "Deteniendo procesos activos...")
            subprocess.run(["taskkill", "/F", "/IM", "monitorPC-Agent.exe"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(0.3)
            
            # 1. Create Folder
            self.update_progress(10, "Creando directorio de instalación...")
            os.makedirs(target_dir, exist_ok=True)
            
            # 2. Check source file
            self.update_progress(20, "Verificando integridad del ejecutable...")
            if not os.path.exists(source_exe):
                raise FileNotFoundError(f"No se pudo encontrar el archivo origen: {source_exe}")
                
            # 3. Copy files
            self.update_progress(35, "Copiando monitorPC-Agent.exe...")
            dest_exe = os.path.join(target_dir, "monitorPC-Agent.exe")
            shutil.copy2(source_exe, dest_exe)
            
            # Copy uninstaller (which is this installer itself!)
            self.update_progress(50, "Copiando desinstalador gráfico...")
            uninstall_exe = os.path.join(target_dir, "uninstall.exe")
            try:
                exe_dir = os.path.dirname(sys.executable)
                is_onedir = False
                if getattr(sys, 'frozen', False):
                    # Check if there are other dependency directories or files (like _internal)
                    for item in os.listdir(exe_dir):
                        if item == "_internal" or item.lower().endswith(".dll") or item.lower().endswith(".pyd"):
                            is_onedir = True
                            break

                if is_onedir:
                    # In onedir mode, we copy all files and folders except the original exe (copied as uninstall.exe)
                    for item in os.listdir(exe_dir):
                        item_path = os.path.join(exe_dir, item)
                        dest_path = os.path.join(target_dir, item)
                        if item.lower() == os.path.basename(sys.executable).lower():
                            shutil.copy2(item_path, uninstall_exe)
                        elif item.lower() in ("monitorpc-agent.exe", "app_icon.ico"):
                            # Skip if they are explicitly handled or copy them anyway
                            shutil.copy2(item_path, dest_path)
                        else:
                            if os.path.isdir(item_path):
                                if os.path.exists(dest_path):
                                    shutil.rmtree(dest_path)
                                shutil.copytree(item_path, dest_path)
                            else:
                                shutil.copy2(item_path, dest_path)
                else:
                    # Onefile mode - copy the standalone executable
                    shutil.copy2(sys.executable, uninstall_exe)
            except Exception as copy_err:
                print(f"Error al copiar desinstalador: {copy_err}")
            
            # Copy app_icon.ico if not already copied
            try:
                dest_icon_path = os.path.join(target_dir, "app_icon.ico")
                if not os.path.exists(dest_icon_path):
                    source_icon = get_resource_path("app_icon.ico")
                    if not os.path.exists(source_icon):
                        source_icon = os.path.abspath(os.path.join(os.path.dirname(__file__), "app_icon.ico"))
                    if os.path.exists(source_icon):
                        shutil.copy2(source_icon, dest_icon_path)
            except Exception as icon_copy_err:
                print(f"Error al copiar icono: {icon_copy_err}")
            
            # 4. Registry Configuration (Startup Run key)
            self.update_progress(65, "Configurando inicio automático...")
            if self.start_with_windows.get():
                try:
                    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                    winreg.SetValueEx(key, "monitorPC-Agent", 0, winreg.REG_SZ, f'"{dest_exe}"')
                    winreg.CloseKey(key)
                except Exception as reg_err:
                    print(f"Error al escribir en el registro de Windows: {reg_err}")
            else:
                try:
                    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                    winreg.DeleteValue(key, "monitorPC-Agent")
                    winreg.CloseKey(key)
                except FileNotFoundError:
                    pass
                except Exception as reg_err:
                    print(f"Error al eliminar del registro: {reg_err}")
                    
            # Register in Windows Add/Remove Programs (Installed Apps)
            self.update_progress(75, "Registrando aplicación en el sistema...")
            try:
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\monitorPC-Agent"
                key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "monitorPC Agent")
                winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstall_exe}"')
                winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, f'"{dest_exe}"')
                winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "monitorPC")
                winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "1.0.0")
                winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, target_dir)
                winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(key)
            except Exception as reg_err:
                print(f"Error al registrar en Uninstall: {reg_err}")
            
            # 5. Create Shortcuts
            self.update_progress(85, "Creando accesos directos...")
            dest_icon = os.path.join(target_dir, "app_icon.ico")
            icon_to_use = dest_icon if os.path.exists(dest_icon) else None
            
            desktop_lnk = None
            if self.create_desktop_shortcut.get():
                desktop_lnk = os.path.join(os.environ["USERPROFILE"], "Desktop", "monitorPC Agent.lnk")
            
            start_menu_lnk = None
            if self.create_start_menu_shortcut.get():
                try:
                    start_menu_dir = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
                    os.makedirs(start_menu_dir, exist_ok=True)
                    start_menu_lnk = os.path.join(start_menu_dir, "monitorPC Agent.lnk")
                except Exception as dir_err:
                    print(f"Error al crear directorio de menú de inicio: {dir_err}")

            if desktop_lnk or start_menu_lnk:
                try:
                    self.create_shortcuts(dest_exe, desktop_lnk, start_menu_lnk, icon_to_use)
                except Exception as lnk_err:
                    print(f"Error al crear accesos directos: {lnk_err}")
                    
            self.update_progress(100, "Instalación completada.")
            
            self.current_screen = 4
            self.root.after(0, self.load_screen)
            
        except Exception as e:
            messagebox.showerror(
                "Error de Instalación",
                f"Ocurrió un error inesperado durante la instalación:\n\n{str(e)}"
            )
            self.current_screen = 2
            self.root.after(0, self.load_screen)

    def finish_installation(self):
        dest_exe = os.path.join(self.install_dir.get(), "monitorPC-Agent.exe")
        if self.run_now.get() and os.path.exists(dest_exe):
            try:
                DETACHED_PROCESS = 0x00000008
                subprocess.Popen(
                    [dest_exe],
                    creationflags=DETACHED_PROCESS,
                    close_fds=True,
                    cwd=self.install_dir.get()
                )
            except Exception as e:
                messagebox.showwarning(
                    "Ejecución Fallida",
                    f"No se pudo iniciar el agente automáticamente:\n{str(e)}"
                )
        
        self.root.destroy()

    def create_shortcuts(self, target_exe, desktop_lnk_path, start_menu_lnk_path, icon_path=None):
        # Prevent command injection by validating no injection characters exist
        for p in (target_exe, desktop_lnk_path, start_menu_lnk_path, icon_path):
            if p and any(c in p for c in (';', '&', '|', '\r', '\n')):
                raise ValueError("Caracteres no permitidos en la ruta")
                
        if not icon_path:
            icon_path = f"{target_exe},0"
            
        # Escape single quotes for PowerShell string literals
        t_exe = target_exe.replace("'", "''")
        t_dir = os.path.dirname(target_exe).replace("'", "''")
        i_path = icon_path.replace("'", "''")
        
        commands = [
            '$WshShell = New-Object -ComObject WScript.Shell;'
        ]
        
        if desktop_lnk_path:
            d_lnk = desktop_lnk_path.replace("'", "''")
            commands.extend([
                f'$Shortcut1 = $WshShell.CreateShortcut(\'{d_lnk}\');',
                f'$Shortcut1.TargetPath = \'{t_exe}\';',
                f'$Shortcut1.WorkingDirectory = \'{t_dir}\';',
                f'$Shortcut1.IconLocation = \'{i_path}\';',
                f'$Shortcut1.Save();'
            ])
            
        if start_menu_lnk_path:
            s_lnk = start_menu_lnk_path.replace("'", "''")
            commands.extend([
                f'$Shortcut2 = $WshShell.CreateShortcut(\'{s_lnk}\');',
                f'$Shortcut2.TargetPath = \'{t_exe}\';',
                f'$Shortcut2.WorkingDirectory = \'{t_dir}\';',
                f'$Shortcut2.IconLocation = \'{i_path}\';',
                f'$Shortcut2.Save();'
            ])
            
        powershell_cmd = " ".join(commands)
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", powershell_cmd],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )


class UninstallerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Desinstalador de monitorPC Agent")
        self.root.geometry("450x260")
        self.root.resizable(False, False)
        
        # Color Palette
        self.bg_color = "#12131C"
        self.surface_color = "#1E1F2E"
        self.accent_green = "#00FF66"
        self.text_white = "#FFFFFF"
        self.text_gray = "#8F909A"
        
        self.root.configure(bg=self.bg_color)
        
        # Set Window Icon
        try:
            icon_path = get_resource_path("app_icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - 450) // 2
        y = (screen_height - 260) // 2
        self.root.geometry(f"450x260+{x}+{y}")
        
        # Determine installation folder (where this uninstall.exe is running)
        self.install_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        
        # Content frame
        self.content_frame = tk.Frame(self.root, bg=self.bg_color)
        self.content_frame.pack(fill="both", expand=True, padx=25, pady=20)
        
        # Nav frame
        self.nav_frame = tk.Frame(self.root, bg=self.bg_color)
        self.nav_frame.pack(fill="x", side="bottom", pady=15)
        
        self.btn_cancel = tk.Button(
            self.nav_frame, text="Cancelar", font=("Helvetica", 10),
            fg=self.text_white, bg="#2C2E3E", activebackground="#3D4057", activeforeground=self.text_white,
            relief="flat", width=12, command=self.root.destroy
        )
        self.btn_cancel.pack(side="right", padx=(0, 25))
        
        self.btn_action = tk.Button(
            self.nav_frame, text="Desinstalar", font=("Helvetica", 10, "bold"),
            fg="#0C1D0F", bg=self.accent_green, activebackground="#00CC52", activeforeground="#0C1D0F",
            relief="flat", width=14, command=self.start_uninstall
        )
        self.btn_action.pack(side="right", padx=(0, 10))
        
        self.show_confirm()

    def show_confirm(self):
        for child in self.content_frame.winfo_children():
            child.destroy()
            
        lbl_title = tk.Label(
            self.content_frame, text="Desinstalar monitorPC Agent", font=("Helvetica", 14, "bold"),
            fg=self.accent_green, bg=self.bg_color
        )
        lbl_title.pack(anchor="w", pady=(5, 10))
        
        lbl_msg = tk.Label(
            self.content_frame, 
            text="¿Está seguro de que desea eliminar por completo monitorPC Agent y todos sus componentes de su computadora?",
            font=("Helvetica", 10), fg=self.text_white, bg=self.bg_color, justify="left", wraplength=400
        )
        lbl_msg.pack(anchor="w", pady=10)

    def start_uninstall(self):
        self.btn_action.configure(state="disabled")
        self.btn_cancel.configure(state="disabled")
        
        for child in self.content_frame.winfo_children():
            child.destroy()
            
        lbl_title = tk.Label(
            self.content_frame, text="Desinstalando...", font=("Helvetica", 12, "bold"),
            fg=self.text_white, bg=self.bg_color
        )
        lbl_title.pack(anchor="w", pady=(10, 5))
        
        self.lbl_status = tk.Label(
            self.content_frame, text="Deteniendo procesos...", font=("Helvetica", 9),
            fg=self.text_gray, bg=self.bg_color
        )
        self.lbl_status.pack(anchor="w", pady=5)
        
        progress_bg = tk.Frame(self.content_frame, height=18, bg=self.surface_color, bd=1, relief="solid", highlightbackground="#2C2E3E")
        progress_bg.pack(fill="x", pady=5)
        progress_bg.pack_propagate(False)
        
        self.progress_bar = tk.Frame(progress_bg, width=0, bg=self.accent_green)
        self.progress_bar.pack(side="left", fill="y")
        
        threading.Thread(target=self.perform_uninstall, daemon=True).start()

    def update_progress(self, percent, text):
        width = int(400 * (percent / 100.0))
        self.progress_bar.configure(width=width)
        self.lbl_status.configure(text=text)
        self.root.update_idletasks()

    def perform_uninstall(self):
        try:
            # 1. Stop process
            time.sleep(0.5)
            self.update_progress(20, "Deteniendo monitorPC-Agent.exe...")
            subprocess.run(["taskkill", "/F", "/IM", "monitorPC-Agent.exe"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(0.5)
            
            # 2. Remove shortcuts
            self.update_progress(40, "Eliminando accesos directos...")
            self.remove_shortcuts()
            time.sleep(0.4)
            
            # 3. Remove Startup Key
            self.update_progress(60, "Eliminando configuración de inicio automático...")
            self.remove_startup_key()
            time.sleep(0.4)
            
            # 4. Remove Uninstall Registry Key
            self.update_progress(80, "Eliminando registros del sistema...")
            self.unregister_uninstall()
            time.sleep(0.5)
            
            self.update_progress(100, "Desinstalación completa.")
            time.sleep(0.3)
            
            self.root.after(0, self.show_finished)
        except Exception as e:
            messagebox.showerror("Error", f"Ocurrió un error al desinstalar:\n{str(e)}", parent=self.root)
            self.root.destroy()

    def show_finished(self):
        for child in self.content_frame.winfo_children():
            child.destroy()
            
        lbl_title = tk.Label(
            self.content_frame, text="Desinstalación Completada", font=("Helvetica", 14, "bold"),
            fg=self.accent_green, bg=self.bg_color
        )
        lbl_title.pack(anchor="w", pady=(10, 10))
        
        lbl_msg = tk.Label(
            self.content_frame, 
            text="monitorPC Agent se ha desinstalado correctamente de su equipo.",
            font=("Helvetica", 10), fg=self.text_white, bg=self.bg_color
        )
        lbl_msg.pack(anchor="w", pady=10)
        
        self.btn_cancel.pack_forget()
        self.btn_action.configure(
            text="Cerrar", state="normal", command=self.do_self_delete
        )
        self.btn_action.pack(side="right", padx=25)

    def do_self_delete(self):
        # Validate folder path to prevent command injection
        if any(c in self.install_dir for c in (';', '&', '|', '\r', '\n')):
            self.root.destroy()
            os._exit(0)
            
        # Escape double quotes just in case
        sanitized_dir = self.install_dir.replace('"', '\\"')
        # Delete folder in background and close
        cmd = f'timeout /t 2 /nobreak > NUL && rmdir /s /q "{sanitized_dir}"'
        subprocess.Popen(
            f'cmd.exe /c {cmd}',
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        self.root.destroy()
        os._exit(0)

    def remove_shortcuts(self):
        desktop_lnk = os.path.join(os.environ["USERPROFILE"], "Desktop", "monitorPC Agent.lnk")
        if os.path.exists(desktop_lnk):
            try:
                os.remove(desktop_lnk)
            except Exception:
                pass
                
        start_menu_lnk = os.path.join(
            os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "monitorPC Agent.lnk"
        )
        if os.path.exists(start_menu_lnk):
            try:
                os.remove(start_menu_lnk)
            except Exception:
                pass

    def remove_startup_key(self):
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            winreg.DeleteValue(key, "monitorPC-Agent")
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Error al eliminar de inicio automático: {e}")

    def unregister_uninstall(self):
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            winreg.DeleteKey(key, "monitorPC-Agent")
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Error al desregistrar desinstalador: {e}")


if __name__ == '__main__':
    is_uninstall = "--uninstall" in sys.argv or os.path.basename(sys.argv[0]).lower() == "uninstall.exe"
    
    root_win = tk.Tk()
    if is_uninstall:
        app = UninstallerApp(root_win)
    else:
        app = InstallerApp(root_win)
    root_win.mainloop()
