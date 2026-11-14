from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QStackedWidget, QFrame, QGridLayout,
    QLineEdit, QComboBox, QCheckBox, QSpacerItem, QSizePolicy,
    QFileDialog, QButtonGroup, QStyledItemDelegate
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox, QMessageBox
from PySide6.QtGui import QFont, QCursor

class SettingsView(QWidget):
    saved = Signal(dict)
    def __init__(self, translator, controller=None):
        super().__init__()
        self.translator = translator
        self.controller = controller
        
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(25, 25, 25, 25)
        self.main_layout.setSpacing(20)

        # 1. Header (Title)
        title = QLabel(self.translator.t("settings_title", "WMS System Settings"))
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setObjectName("title_label")
        self.main_layout.addWidget(title)

        # 2. Horizontal Tab Menu
        self.setup_tabs()

        # 3. Stacked Widget (Pages)
        self.stacked_widget = QStackedWidget()
        self.setup_pages()
        self.main_layout.addWidget(self.stacked_widget)

        # 4. Bottom Bar (Save Button)
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        
        self.save_btn = QPushButton(self.translator.t("settings_save", "Save configuration"))
        self.save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.save_btn.setObjectName("primary_btn")
        self.save_btn.clicked.connect(self.save_settings)
        bottom_layout.addWidget(self.save_btn)
        
        self.main_layout.addLayout(bottom_layout)

    def retranslate_ui(self):
        """Refreshes all text labels in the settings view using the current translator."""
        # This can be called dynamically if language changes on the fly
        pass
    
    def setup_tabs(self):
        tab_layout = QHBoxLayout()
        tab_layout.setSpacing(10)
        
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        
        tabs = [
            (0, self.translator.t("tab_paths", "System Paths")),
            (1, self.translator.t("tab_company", "Company Data")),
            (2, self.translator.t("tab_appearance", "Appearance & Localization")),
            (3, self.translator.t("tab_notifications", "Notifications & System"))
        ]
        
        for index, text in tabs:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            if index == 0:
                btn.setChecked(True)
                
            btn.setObjectName("tab_btn")
            
            # W PySide6 używamy id dla przycisków w grupie
            self.tab_group.addButton(btn, index)
            tab_layout.addWidget(btn)
            
            # Lambdy rozwiązują problem przekazywania argumentu w pętli
            btn.clicked.connect(lambda checked, idx=index: self.stacked_widget.setCurrentIndex(idx))
            
        tab_layout.addStretch()
        self.main_layout.addLayout(tab_layout)

    def _create_card_frame(self):
        """Tworzy panel (kartę) z ciemniejszym tłem i zaokrąglonymi rogami"""
        frame = QFrame()
        frame.setObjectName("settings_card")
        return frame

    def _add_path_row(self, layout, row, label_text, database=False):
        """Dodaje etykietę, pole tekstowe i przycisk 'Browse' do layoutu"""
        lbl = QLabel(label_text)
        line_edit = QLineEdit()
        btn = QPushButton(self.translator.t("btn_browse", "Browse..."))
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setObjectName("browse_btn")
        
        layout.addWidget(lbl, row, 0)
        layout.addWidget(line_edit, row, 1)
        layout.addWidget(btn, row, 2)
        def browse():
            if database:
                value,_ = QFileDialog.getOpenFileName(self,label_text,line_edit.text(),"SQLite (*.db *.sqlite *.sqlite3)")
            else:
                value = QFileDialog.getExistingDirectory(self,label_text,line_edit.text())
            if value:
                line_edit.setText(value)
        btn.clicked.connect(browse)
        return line_edit, btn

    def _add_form_row(self, layout, row, label_text, widget):
        """Dodaje standardowy wiersz formularza (Etykieta + Widget)"""
        lbl = QLabel(label_text)
        layout.addWidget(lbl, row, 0)
        layout.addWidget(widget, row, 1)

    def setup_pages(self):
        self.page_paths = self._create_paths_page()
        self.page_company = self._create_company_page()
        self.page_appearance = self._create_appearance_page()
        self.page_system = self._create_system_page()
        
        self.stacked_widget.addWidget(self.page_paths)
        self.stacked_widget.addWidget(self.page_company)
        self.stacked_widget.addWidget(self.page_appearance)
        self.stacked_widget.addWidget(self.page_system)

    def _create_paths_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        
        card = self._create_card_frame()
        grid = QGridLayout(card)
        grid.setSpacing(15)
        grid.setContentsMargins(20, 20, 20, 20)
        
        # UI Elements for Paths
        self.path_backup, _ = self._add_path_row(grid, 0, self.translator.t("path_backup", "Database Backup Folder:"))
        self.path_export_pick, _ = self._add_path_row(grid, 1, self.translator.t("path_pick", "Pick Lists Export Folder:"))
        self.path_export_inv, _ = self._add_path_row(grid, 2, self.translator.t("path_invoice", "Invoices Export Folder:"))
        self.path_import, _ = self._add_path_row(grid, 3, self.translator.t("path_import", "Default Import Folder:"))
        self.path_templates, _ = self._add_path_row(grid, 4, self.translator.t("path_templates", "Document Templates Folder:"))
        
        self.database_path,_ = self._add_path_row(grid,5,self.translator.t("database_file"),True)
        self.carrier_path,_ = self._add_path_row(grid,6,self.translator.t("carrier_folder"))
        self.template_choices = {}
        for row, kind in enumerate(("email", "pick", "invoice"), 7):
            combo = QComboBox()
            combo.setItemDelegate(QStyledItemDelegate(combo))
            combo.setAccessibleName(self.translator.t("template_" + kind, kind))
            self._add_form_row(grid, row, self.translator.t("template_" + kind, kind), combo)
            self.template_choices[kind] = combo
            combo.currentIndexChanged.connect(self.update_template_notice)
        self.template_refresh = QPushButton(self.translator.t("templates_refresh", "Refresh templates"))
        self.template_refresh.clicked.connect(lambda: self.refresh_templates())
        grid.addWidget(self.template_refresh, 10, 2)
        self.template_notice = QLabel()
        self.template_notice.setWordWrap(True)
        grid.addWidget(self.template_notice, 10, 0, 1, 2)
        self.path_templates.textChanged.connect(lambda: self.refresh_templates())
        grid.setColumnStretch(1, 1)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def refresh_templates(self, saved=None):
        from utils.document_templates import list_templates
        selected = saved or {("pick_list" if kind == "pick" else kind): combo.currentData()
                             for kind, combo in self.template_choices.items()}
        config = {"paths": {"templates": {"base_dir": self.path_templates.text().strip()}}}
        for kind, combo in self.template_choices.items():
            key = "pick_list" if kind == "pick" else kind
            choice = selected.get(key) or f"{kind}-standard.html"
            names = list_templates(config, kind)
            combo.clear()
            for name in names:
                combo.addItem(name, name)
            if choice not in names:
                combo.addItem(choice + " · " + self.translator.t("templates_unavailable", "default fallback"), choice)
            combo.setCurrentIndex(combo.findData(choice))
        self.update_template_notice()

    def update_template_notice(self, *_):
        if not hasattr(self, "template_notice"):
            return
        from utils.document_templates import list_templates
        config = {"paths": {"templates": {"base_dir": self.path_templates.text().strip()}}}
        unavailable = any(combo.currentData() not in list_templates(config, kind)
                          for kind, combo in self.template_choices.items())
        self.template_notice.setText(self.translator.t("templates_fallback_notice", "Unavailable templates use the bundled Standard design.") if unavailable else "")

    def _create_company_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        
        card = self._create_card_frame()
        grid = QGridLayout(card)
        grid.setSpacing(15)
        grid.setContentsMargins(20, 20, 20, 20)
        
        self.comp_name = QLineEdit()
        self.comp_nip = QLineEdit()
        self.comp_street = QLineEdit()
        self.comp_postal_code = QLineEdit()
        self.comp_city = QLineEdit()
        self.comp_email = QLineEdit()
        self.comp_phone = QLineEdit()
        self.smtp_key = QLineEdit()
        self.smtp_key.setEchoMode(QLineEdit.Password) # Ukrywa znaki
        
        self._add_form_row(grid, 0, self.translator.t("comp_name", "Company Name:"), self.comp_name)
        self._add_form_row(grid, 1, self.translator.t("comp_nip", "Tax ID (NIP):"), self.comp_nip)
        self._add_form_row(grid, 2, self.translator.t("comp_street", "Street:"), self.comp_street)
        self._add_form_row(grid, 3, self.translator.t("comp_postal_code", "Postal Code:"), self.comp_postal_code)
        self._add_form_row(grid, 4, self.translator.t("comp_city", "City:"), self.comp_city)
        self._add_form_row(grid, 5, self.translator.t("comp_email", "Email Address:"), self.comp_email)
        self._add_form_row(grid, 6, self.translator.t("comp_phone", "Phone Number:"), self.comp_phone)
        
        lbl_smtp = QLabel(self.translator.t("comp_smtp", "SMTP Mail Key:"))
        lbl_smtp.setObjectName("accent_label")
        grid.addWidget(lbl_smtp, 7, 0)
        grid.addWidget(self.smtp_key, 7, 1)
        self.bank,self.bdo = QLineEdit(),QLineEdit()
        for idx,(key,w) in enumerate((("bank",self.bank),("bdo",self.bdo)),8):
            self._add_form_row(grid,idx,self.translator.t(key),w)
        self.smtp_button=QPushButton(self.translator.t("smtp_account"))
        self.smtp_button.clicked.connect(self.smtp_dialog)
        grid.addWidget(self.smtp_button,10,0,1,2)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _create_appearance_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        
        card = self._create_card_frame()
        grid = QGridLayout(card)
        grid.setSpacing(15)
        grid.setContentsMargins(20, 20, 20, 20)
        
        self.cb_lang = QComboBox()
        self.cb_lang.addItems(["en", "pl"])
        
        self.cb_theme = QComboBox()
        self.cb_theme.addItems(["dark", "light", "modern"])
        
        self.cb_font = QComboBox()
        self.cb_font.addItems(["small", "medium", "large"])
        
        self.cb_date = QComboBox()
        self.cb_date.addItems(["YYYY-MM-DD", "DD.MM.YYYY"])
        self.fullscreen = QCheckBox(self.translator.t("fullscreen"))
        grid.addWidget(self.fullscreen,4,0,1,2)
        for combo in (self.cb_lang, self.cb_theme, self.cb_font, self.cb_date):
            combo.setItemDelegate(QStyledItemDelegate(combo))
        
        self._add_form_row(grid, 0, self.translator.t("app_lang", "System Language:"), self.cb_lang)
        self._add_form_row(grid, 1, self.translator.t("app_theme", "Visual Theme:"), self.cb_theme)
        self._add_form_row(grid, 2, self.translator.t("app_font", "UI Font Size:"), self.cb_font)
        self._add_form_row(grid, 3, self.translator.t("app_date", "Date Format:"), self.cb_date)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _create_system_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        
        card = self._create_card_frame()
        vbox = QVBoxLayout(card)
        vbox.setSpacing(15)
        vbox.setContentsMargins(20, 20, 20, 20)
        
        self.chk_toasts = QCheckBox(self.translator.t("sys_toasts", "Enable Toast Notifications (Action Confirmations)"))
        self.chk_sounds = QCheckBox(self.translator.t("sys_sounds", "Play sound on action success/error"))
        self.chk_autobackup = QCheckBox(self.translator.t("sys_autobackup", "Auto-backup database on application exit"))
        
        vbox.addWidget(self.chk_toasts)
        vbox.addWidget(self.chk_sounds)
        vbox.addWidget(self.chk_autobackup)
        self.restore_prompts=QCheckBox(self.translator.t("restore_prompts"))
        vbox.addWidget(self.restore_prompts)
        
        layout.addWidget(card)
        layout.addStretch()
        return page
    def load_settings(self):
        """Populates the form with data loaded from the config.json file."""
        if not self.controller:
            return
            
        config = self.controller.get_config()
        
        # System paths (mapped to your specific JSON keys)
        paths = config.get("paths", {})
        self.database_path.setText(paths.get("database","warehouse.db"))
        self.carrier_path.setText(paths.get("exports_carriers",""))
        self.path_backup.setText(paths.get("backups", ""))
        self.path_export_pick.setText(paths.get("exports_pick_lists", "")) 
        self.path_export_inv.setText(paths.get("exports_invoices", "")) 
        self.path_import.setText(paths.get("imports_default", ""))
        
        # Templates is a nested dict in your config
        templates = paths.get("templates", {})
        if isinstance(templates, dict):
            self.path_templates.setText(templates.get("base_dir", ""))
            self.refresh_templates(templates)
        self._loaded_template_folder = self.path_templates.text()
        self._loaded_template_choices = {kind: combo.currentData() for kind, combo in self.template_choices.items()}
        
        # Company details (mapped to 'company_info' instead of 'company')
        company = config.get("company_info", {})
        self.bank.setText(company.get("bank",""))
        self.bdo.setText(company.get("bdo",""))
        self.comp_name.setText(company.get("name", ""))
        self.comp_nip.setText(company.get("tax_id", ""))
        
        self.comp_street.setText(company.get("street", ""))
        self.comp_postal_code.setText(company.get("postal_code", ""))
        self.comp_city.setText(company.get("city", ""))
        
        self.comp_email.setText(company.get("email", ""))
        self.comp_phone.setText(company.get("phone", ""))
        
        # SMTP Key is in 'email_smtp'
        smtp = config.get("email_smtp", {})
        self.smtp_options = dict(smtp)
        self.smtp_key.setPlaceholderText("••••••" if smtp.get("credential_id") else self.translator.t("smtp_secret_hint"))
        self.smtp_key.clear()
        
        # Localization and appearance
        loc = config.get("localization", {})
        appr = config.get("appearance", {})
        self.cb_lang.setCurrentText(loc.get("language", "pl"))
        self.cb_date.setCurrentText(loc.get("date_format", "YYYY-MM-DD"))
        self.fullscreen.setChecked(appr.get("fullscreen",False))
        self.cb_theme.setCurrentText(appr.get("theme", "dark"))
        self.cb_font.setCurrentText(appr.get("font_size", "medium"))
        
        # System preferences
        sys_cfg = config.get("system", {})
        notif = sys_cfg.get("notifications", {})
        self.chk_toasts.setChecked(notif.get("show_toasts", True))
        self.chk_sounds.setChecked(notif.get("play_sound", True))
        self.chk_autobackup.setChecked(sys_cfg.get("auto_backup_on_exit", True))

    def smtp_dialog(self):
        dlg=QDialog(self)
        dlg.setWindowTitle(self.translator.t("smtp_account"))
        form=QFormLayout(dlg)
        fields={}
        for key in ("sender","host","port","username","security"):
            if key=="security":
                w=QComboBox()
                w.setItemDelegate(QStyledItemDelegate(w))
                w.addItems(["TLS","STARTTLS","LOCAL"])
                w.setCurrentText(self.smtp_options.get(key,"TLS"))
            else:
                w=QLineEdit(str(self.smtp_options.get(key,"")))
            fields[key]=w
            form.addRow(self.translator.t("smtp_"+key,key),w)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec()==QDialog.Accepted:
            self.smtp_options.update({k:(w.currentText() if k=="security" else w.text().strip()) for k,w in fields.items()})

    def save_settings(self):
        """Collects data from UI and overwrites the config.json file."""
        if not self.controller:
            return
            
        from PySide6.QtWidgets import QMessageBox
            
        config = self.controller.get_config()
        
        # Save paths
        if "paths" not in config: config["paths"] = {}
        config["paths"]["backups"] = self.path_backup.text()
        config["paths"]["exports_pick_lists"] = self.path_export_pick.text() 
        config["paths"]["exports_invoices"] = self.path_export_inv.text()
        config["paths"]["imports_default"] = self.path_import.text()
        
        folder_changed = self.path_templates.text() != getattr(self, "_loaded_template_folder", "")
        choices_changed = {kind: combo.currentData() for kind, combo in self.template_choices.items()
                           if combo.currentData() != getattr(self, "_loaded_template_choices", {}).get(kind)}
        if folder_changed or choices_changed:
            templates = config["paths"].setdefault("templates", {})
            if not isinstance(templates, dict):
                templates = config["paths"]["templates"] = {}
            if folder_changed:
                templates["base_dir"] = self.path_templates.text()
            for kind, choice in choices_changed.items():
                templates["pick_list" if kind == "pick" else kind] = choice
        
        # Save company info
        if "company_info" not in config: config["company_info"] = {}
        config["company_info"]["name"] = self.comp_name.text()
        config["company_info"]["tax_id"] = self.comp_nip.text()
        config["company_info"]["street"] = self.comp_street.text()
        config["company_info"]["postal_code"] = self.comp_postal_code.text()
        config["company_info"]["city"] = self.comp_city.text()
        config["company_info"]["email"] = self.comp_email.text()
        config["company_info"]["phone"] = self.comp_phone.text()
        
        # Save SMTP
        if "email_smtp" not in config: config["email_smtp"] = {}
        config["email_smtp"].update(self.smtp_options)
        if self.smtp_key.text():
            from utils.smtp_secret import store_password
            try:
                config["email_smtp"]["credential_id"]=store_password(self.smtp_key.text())
            except (OSError,AttributeError):
                QMessageBox.warning(self,self.translator.t("smtp_account"),self.translator.t("smtp_setup"))
                return
            config["email_smtp"].pop("smtp_key",None)
        config["paths"]["database"]=self.database_path.text().strip() or "warehouse.db"
        for section,key,widget in (("paths","exports_carriers",self.carrier_path),("company_info","bank",self.bank),("company_info","bdo",self.bdo)):
            if widget.text() or key in config[section]:
                config[section][key]=widget.text()
        if self.fullscreen.isChecked() or "fullscreen" in config["appearance"]:
            config["appearance"]["fullscreen"]=self.fullscreen.isChecked()
        if self.restore_prompts.isChecked():
            config["system"].pop("skip_pick_confirmation",None)
        
        # Localization, appearance, system
        config["localization"]["language"] = self.cb_lang.currentText()
        config["localization"]["date_format"] = self.cb_date.currentText()
        config["appearance"]["theme"] = self.cb_theme.currentText()
        config["appearance"]["font_size"] = self.cb_font.currentText()
        
        if "system" not in config: config["system"] = {}
        config["system"]["auto_backup_on_exit"] = self.chk_autobackup.isChecked()
        if "notifications" not in config["system"]: config["system"]["notifications"] = {}
        config["system"]["notifications"]["show_toasts"] = self.chk_toasts.isChecked()
        config["system"]["notifications"]["play_sound"] = self.chk_sounds.isChecked()
        
        success = self.controller.save_config(config)
        
        if success:
            from PySide6.QtWidgets import QApplication
            from utils.theme_manager import ThemeManager
            app = QApplication.instance()
            if app:
                ThemeManager.apply_theme(app, config["appearance"]["theme"], config["appearance"]["font_size"])

        if success:
            self.smtp_options = dict(config["email_smtp"])
            self.smtp_key.clear()
            self.restore_prompts.setChecked(False)
            self.saved.emit(config)
            QMessageBox.information(
                self, 
                self.translator.t("settings_saved_title", "Settings Saved"),
                self.translator.t("saved_now")
            )
