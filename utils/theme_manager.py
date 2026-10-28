class ThemeManager:
    @staticmethod
    def get_stylesheet(theme_name, font_size_name):
        fonts = {"small": "12px", "medium": "14px", "large": "16px"}
        base_font = fonts.get(font_size_name, "14px")

        palettes = {
            "light": {
                "bg_main": "#f0f2f5",      
                "bg_sidebar": "#ffffff",   
                "bg_card": "#ffffff",
                "text_main": "#2c3e50",
                "text_muted": "#64748b",
                "border": "#e2e8f0",
                "border_focus": "#3b82f6",
                "primary": "#3b82f6",
                "primary_hover": "#2563eb",
                "danger": "#ef4444",
                "danger_hover": "#dc2626",
                "input_bg": "#f8fafc",
                "accent": "#0369a1"        # Mocniejszy niebieski dla kontrastu napisów
            },
            "modern": {
                "bg_main": "#0f172a", "bg_sidebar": "#020617", "bg_card": "#1e293b",
                "text_main": "#f8fafc", "text_muted": "#94a3b8",
                "border": "#334155", "border_focus": "#0ea5e9",
                "primary": "#0ea5e9", "primary_hover": "#0284c7",
                "danger": "#e11d48", "danger_hover": "#be123c",
                "input_bg": "#0f172a", "accent": "#38bdf8"
            },
            "dark": {
                "bg_main": "#1a1e29", "bg_sidebar": "#11141d", "bg_card": "#242933",
                "text_main": "#ffffff", "text_muted": "#a0a5b1",
                "border": "#3b4252", "border_focus": "#48dbfb",
                "primary": "#4a69bd", "primary_hover": "#5a79cd",
                "danger": "#8b0000", "danger_hover": "#a10000",
                "input_bg": "#2e3440", "accent": "#8fbcbb"
            }
        }

        p = palettes.get(theme_name, palettes["dark"])

        return f"""
            * {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: {base_font}; outline: none; }}
            QMainWindow, QWidget#central_widget {{ background-color: {p['bg_main']}; color: {p['text_main']}; }}
            
            QFrame {{ background-color: {p['bg_card']}; border: 1px solid {p['border']}; border-radius: 8px; }}
            
            /* Sidebar Styling - teraz dopasowuje się do każdego motywu */
            QFrame#sidebar {{ background-color: {p['bg_sidebar']}; border: none; border-right: 1px solid {p['border']}; border-radius: 0px; }}
            
            QFrame#headers_frame {{ background-color: {p['bg_card']}; border: 1px solid {p['border']}; border-radius: 4px; }}
            QFrame#details_panel {{ background-color: {p['bg_main']}; border: 1px solid {p['border']}; border-radius: 4px; }}
            QFrame#accordion_row {{ background-color: transparent; border: none; border-bottom: 1px solid {p['border']}; border-radius: 0px; }}
            
            QLabel {{ color: {p['text_main']}; background: transparent; border: none; }}
            QLabel#title_label {{ font-size: 18px; font-weight: bold; }}
            
            QLineEdit, QComboBox {{ background-color: {p['input_bg']}; border: 1px solid {p['border']}; border-radius: 5px; padding: 6px; color: {p['text_main']}; }}
            QLineEdit:focus, QComboBox:focus {{ border: 1px solid {p['border_focus']}; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {p['bg_card']}; color: {p['text_main']};
                selection-background-color: {p['accent']};
                selection-color: {p['bg_sidebar']};
                border: 1px solid {p['border']};
            }}
            QComboBox QAbstractItemView::item {{ padding: 4px 6px; }}
            QComboBox QAbstractItemView::item:selected,
            QComboBox QAbstractItemView::item:hover {{
                background-color: {p['accent']}; color: {p['bg_sidebar']};
            }}
            
            QTableWidget {{ background-color: {p['bg_card']}; color: {p['text_main']}; gridline-color: {p['border']}; border: none; }}
            QHeaderView::section {{ background-color: {p['bg_main']}; color: {p['accent']}; font-weight: bold; padding: 5px; border: none; border-bottom: 2px solid {p['border']}; }}
            
            QScrollArea, QScrollArea > QWidget > QWidget {{ background-color: transparent; border: none; }}
            
            QPushButton {{ background-color: {p['border']}; color: {p['text_main']}; border-radius: 5px; padding: 8px; border: none; }}
            QPushButton:hover {{ background-color: {p['input_bg']}; }}
            
            QPushButton#primary_btn {{ background-color: {p['primary']}; color: white; font-weight: bold; }}
            QPushButton#primary_btn:hover {{ background-color: {p['primary_hover']}; }}
            
            QPushButton#danger_btn {{ background-color: {p['danger']}; color: white; font-weight: bold; }}
            QPushButton#danger_btn:hover {{ background-color: {p['danger_hover']}; }}
            
            /* Sidebar Menu Buttons */
            QPushButton#menu_btn {{ background-color: transparent; text-align: left; padding: 10px; color: {p['text_muted']}; border-radius: 0px; font-weight: bold; }}
            QPushButton#menu_btn:hover {{ background-color: {p['bg_main']}; color: {p['accent']}; }}
            
            QPushButton#submenu_btn {{ background-color: transparent; text-align: left; padding: 5px; color: {p['accent']}; border-radius: 0px; font-size: 13px; }}
            QPushButton#submenu_btn:hover {{ color: {p['text_main']}; }}
            
            /* Settings Tab Buttons */
            QPushButton#tab_btn {{ background-color: {p['bg_main']}; color: {p['text_muted']}; border-radius: 15px; padding: 8px 20px; font-weight: bold; border: 1px solid {p['border']}; }}
            QPushButton#tab_btn:checked {{ background-color: {p['primary']}; color: white; border: none; }}
            QPushButton#tab_btn:hover:!checked {{ background-color: {p['border']}; }}
            
            QPushButton#action_btn {{ background-color: transparent; color: {p['accent']}; text-align: left; }}
            QPushButton#action_btn:hover {{ color: {p['text_main']}; }}
            
            QCheckBox {{ color: {p['text_main']}; background: transparent; }}
        """
