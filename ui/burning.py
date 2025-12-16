from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFileDialog, QProgressBar, 
    QMessageBox, QGroupBox, QSpinBox, QColorDialog, QLineEdit,
    QFontComboBox, QComboBox, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QColor, QFont
import signal
import os
import subprocess
import shutil
import tempfile

class BurningWorker(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, video_path, subtitle_path, output_path, config):
        super().__init__()
        self.video_path = video_path
        self.subtitle_path = subtitle_path
        self.output_path = output_path
        self.config = config # Dict containing all style params
        self.is_running = True

    def run(self):
        try:
            self.log.emit("Starting subtitle burning...")
            
            font_color = self.config.get('font_color')
            # Convert color to FFmpeg format: &HBBGGRR&
            ffmpeg_color = f"&H{font_color.blue():02X}{font_color.green():02X}{font_color.red():02X}&"
            
            # Escape paths
            srt_path_escaped = self.subtitle_path.replace(":", "\\:").replace("'", "'\\''")
            
            # Escape font name
            font_family = self.config.get('font_family', 'Arial')
            font_family_safe = font_family.replace(":", "\\:").replace("'", "")
            
            # Extract other params
            font_size = self.config.get('font_size', 24)
            alignment = self.config.get('alignment', 2)
            margin_v = self.config.get('margin_v', 10)
            outline = self.config.get('outline', 1)
            shadow = self.config.get('shadow', 1)
            
            # Construct Filter string
            style = (f"FontName={font_family_safe},FontSize={font_size},PrimaryColour={ffmpeg_color},"
                     f"Alignment={alignment},MarginV={margin_v},Outline={outline},Shadow={shadow}")
            
            vf_string = f"subtitles='{srt_path_escaped}':force_style='{style}'"
            
            self.log.emit(f"Using Font: {font_family}")
            self.log.emit(f"Font Size: {font_size}")
            self.log.emit(f"Style Config: {style}")
            
            # Auto-detect encoder based on architecture
            import platform
            arch = platform.machine()
            if arch == 'arm64':
                encoder = "h264_videotoolbox"
                encoder_opts = ["-b:v", "6000k"]
                self.log.emit("Detected Apple Silicon (arm64): Using Hardware Acceleration")
            else:
                encoder = "libx264"
                # CRF 23 is standard for high quality, preset fast for speed
                encoder_opts = ["-crf", "23", "-preset", "fast"] 
                self.log.emit(f"Detected Intel ({arch}): Using CPU Software Encoding (Compatibility Mode)")
            
            cmd = [
                "ffmpeg",
                "-y", # Overwrite output
                "-i", self.video_path,
                "-vf", vf_string,
                "-c:v", encoder,
            ] + encoder_opts + [
                "-pix_fmt", "yuv420p", # Essential for compatibility
                "-c:a", "aac", # Re-encode audio to AAC
                self.output_path
            ]
            
            self.log.emit(f"Executing: {' '.join(cmd)}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            # Monitor process
            self.process = process
            for line in process.stdout:
                if not self.is_running:
                    # Kill gracefully then forceful
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    self.log.emit("Process stopped by user.")
                    return # Exit run()

                if "frame=" in line or "time=" in line:
                    self.log.emit(line.strip())
                
            ret_code = process.wait()
            if ret_code == 0:
                self.finished.emit()
            elif ret_code != -15 and ret_code != -9: # != SIGTERM/SIGKILL (user stop)
                self.error.emit(f"FFmpeg finished with error code {ret_code}")

        except Exception as e:
            if self.is_running: # Only emit error if not manually stopped
                self.error.emit(str(e))

    def stop(self):
        self.is_running = False
        # If waiting on IO, we might need to kill from here too if thread is blocked
        if hasattr(self, 'process') and self.process.poll() is None:
             self.process.terminate()

class SubtitleBurningPage(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("MacWhisper", "Burning") # Persistence
        self.font_color = QColor(255, 255, 255) # Default White
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("Burn Subtitles to Video")
        title.setObjectName("header")
        layout.addWidget(title)

        # --- Inputs ---
        input_group = QGroupBox("Input Files")
        input_layout = QVBoxLayout()
        
        # Video File
        video_layout = QHBoxLayout()
        self.video_label = QLabel("No video selected")
        self.video_label.setStyleSheet("color: #888;")
        video_btn = QPushButton("Select Video")
        video_btn.clicked.connect(self.select_video)
        video_layout.addWidget(video_btn)
        video_layout.addWidget(self.video_label)
        input_layout.addLayout(video_layout)
        
        # Subtitle File
        sub_layout = QHBoxLayout()
        self.sub_label = QLabel("No subtitle selected")
        self.sub_label.setStyleSheet("color: #888;")
        sub_btn = QPushButton("Select Subtitle")
        sub_btn.clicked.connect(self.select_subtitle)
        sub_layout.addWidget(sub_btn)
        sub_layout.addWidget(self.sub_label)
        input_layout.addLayout(sub_layout)
        
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # --- Styling ---
        style_group = QGroupBox("Subtitle Style")
        # Use Grid Layout for more controls
        from PyQt6.QtWidgets import QGridLayout
        style_layout = QGridLayout()
        style_layout.setSpacing(15)
        
        # Row 0: Font & Size
        style_layout.addWidget(QLabel("Font:"), 0, 0)
        self.font_combo = QFontComboBox()
        style_layout.addWidget(self.font_combo, 0, 1)
        
        style_layout.addWidget(QLabel("Size:"), 0, 2)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 400) # Increased range for 4k
        self.font_spin.setValue(24)
        style_layout.addWidget(self.font_spin, 0, 3)

        # Row 1: Color & Alignment
        style_layout.addWidget(QLabel("Color:"), 1, 0)
        color_layout = QHBoxLayout()
        self.color_sample = QLabel("   ")
        self.color_sample.setFixedSize(30, 20)
        self.color_sample.setStyleSheet(f"background-color: {self.font_color.name()}; border: 1px solid #555;")
        color_layout.addWidget(self.color_sample)
        color_btn = QPushButton("Pick")
        color_btn.clicked.connect(self.pick_color)
        color_layout.addWidget(color_btn)
        style_layout.addLayout(color_layout, 1, 1)

        style_layout.addWidget(QLabel("Align:"), 1, 2)
        self.align_combo = QComboBox()
        self.align_map = {
            "Bottom Center": 2,
            "Bottom Left": 1,
            "Bottom Right": 3,
            "Top Center": 6,
            "Top Left": 5,
            "Top Right": 7,
            "Center": 10
        }
        self.align_combo.addItems(list(self.align_map.keys()))
        style_layout.addWidget(self.align_combo, 1, 3)

        # Row 2: Margins & Effects
        style_layout.addWidget(QLabel("Margin V:"), 2, 0)
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 1000)
        self.margin_spin.setValue(10)
        self.margin_spin.setSuffix(" px")
        style_layout.addWidget(self.margin_spin, 2, 1)
        
        style_layout.addWidget(QLabel("Outline:"), 2, 2)
        self.outline_spin = QSpinBox()
        self.outline_spin.setRange(0, 20)
        self.outline_spin.setValue(1)
        style_layout.addWidget(self.outline_spin, 2, 3)
        
        style_layout.addWidget(QLabel("Shadow:"), 3, 2)
        self.shadow_spin = QSpinBox()
        self.shadow_spin.setRange(0, 20)
        self.shadow_spin.setValue(1)
        style_layout.addWidget(self.shadow_spin, 3, 3)
        
        style_group.setLayout(style_layout)
        layout.addWidget(style_group)

        # --- Actions ---
        action_layout = QHBoxLayout()
        
        self.burn_btn = QPushButton("Start Burning")
        self.burn_btn.setObjectName("primaryButton")
        self.burn_btn.clicked.connect(self.start_burning)
        self.burn_btn.setEnabled(False)
        action_layout.addWidget(self.burn_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.stop_burning)
        self.cancel_btn.setEnabled(False)
        action_layout.addWidget(self.cancel_btn)
        
        self.save_btn = QPushButton("Save Video")
        self.save_btn.setObjectName("downloadBtn")
        self.save_btn.clicked.connect(self.save_video)
        self.save_btn.setEnabled(False)
        action_layout.addWidget(self.save_btn)
        
        layout.addLayout(action_layout)
        
        # Progress & Status
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)
        
        self.log_output = QLineEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Ready...")
        layout.addWidget(self.log_output)
        
        # Load saved settings
        self.load_settings()

    def select_video(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Video Files (*.mp4 *.mov *.mkv *.avi)")
        if f:
            self.video_path = f
            self.video_label.setText(os.path.basename(f))
            self.check_ready()

    def select_subtitle(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Subtitle", "", "Subtitle Files (*.srt *.ass *.vtt)")
        if f:
            self.subtitle_path = f
            self.sub_label.setText(os.path.basename(f))
            self.check_ready()

    def check_ready(self):
        if hasattr(self, 'video_path') and hasattr(self, 'subtitle_path'):
            self.burn_btn.setEnabled(True)

    def pick_color(self):
        color = QColorDialog.getColor(self.font_color, self, "Choose Subtitle Color")
        if color.isValid():
            self.font_color = color
            self.color_sample.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #555;")

    def start_burning(self):
        # Save current settings
        self.save_settings()
        
        # Use temp dir for intermediate file
        _, ext = os.path.splitext(self.video_path)
        self.temp_output = os.path.join(tempfile.gettempdir(), f"macwhisper_burn_{os.getpid()}{ext}")
        
        self.progress_bar.setVisible(True)
        self.burn_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.log_output.setText("Burning in progress...")
        
        # Gather Config
        config = {
            'font_family': self.font_combo.currentFont().family(),
            'font_size': self.font_spin.value(),
            'font_color': self.font_color,
            'alignment': self.align_map.get(self.align_combo.currentText(), 2),
            'margin_v': self.margin_spin.value(),
            'outline': self.outline_spin.value(),
            'shadow': self.shadow_spin.value()
        }
        
        self.worker = BurningWorker(
            self.video_path, 
            self.subtitle_path, 
            self.temp_output, 
            config
        )
        self.worker.log.connect(self.log_output.setText)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def save_settings(self):
        self.settings.setValue("font_family", self.font_combo.currentFont().family())
        self.settings.setValue("font_size", self.font_spin.value())
        self.settings.setValue("font_color", self.font_color.name())
        self.settings.setValue("alignment_idx", self.align_combo.currentIndex())
        self.settings.setValue("margin_v", self.margin_spin.value())
        self.settings.setValue("outline", self.outline_spin.value())
        self.settings.setValue("shadow", self.shadow_spin.value())

    def load_settings(self):
        # Font Family
        fam = self.settings.value("font_family")
        if fam:
            self.font_combo.setCurrentFont(QFont(fam))
        else:
             # Default Fallback if no setting
             default_font = QFont("PingFang SC")
             if default_font.exactMatch():
                self.font_combo.setCurrentFont(default_font)
             else:
                self.font_combo.setCurrentFont(QFont("Arial Unicode MS"))

        # Font Size
        size = self.settings.value("font_size", 24)
        self.font_spin.setValue(int(size))
        
        # Color
        col_name = self.settings.value("font_color", "#FFFFFF")
        self.font_color = QColor(col_name)
        self.color_sample.setStyleSheet(f"background-color: {self.font_color.name()}; border: 1px solid #555;")
        
        # Alignment
        idx = self.settings.value("alignment_idx", 0)
        self.align_combo.setCurrentIndex(int(idx))
        
        # Margins & Effects
        self.margin_spin.setValue(int(self.settings.value("margin_v", 10)))
        self.outline_spin.setValue(int(self.settings.value("outline", 1)))
        self.shadow_spin.setValue(int(self.settings.value("shadow", 1)))

    def stop_burning(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            self.worker.quit()
            self.log_output.setText("Stopping...")
            self.cancel_btn.setEnabled(False)
            self.burn_btn.setEnabled(True)
            self.progress_bar.setVisible(False)

    def on_finished(self):
        self.progress_bar.setVisible(False)
        self.burn_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.save_btn.setEnabled(True)
        self.log_output.setText("Processing Complete!")
        QMessageBox.information(self, "Success", "Burning complete. Click 'Save Video' to save the file.")

    def on_error(self, msg):
        self.progress_bar.setVisible(False)
        self.burn_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        QMessageBox.critical(self, "Error", f"Burning failed:\n{msg}")

    def save_video(self):
        if not hasattr(self, 'temp_output') or not os.path.exists(self.temp_output):
             return
        
        default_name = os.path.splitext(os.path.basename(self.video_path))[0] + "_subbed" + os.path.splitext(self.video_path)[1]
        target_path, _ = QFileDialog.getSaveFileName(self, "Save Video", default_name, "Video Files (*.mp4 *.mov *.mkv *.avi)")
        
        if target_path:
            try:
                shutil.copy2(self.temp_output, target_path)
                QMessageBox.information(self, "Saved", f"Video saved to:\n{target_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not save file: {e}")
