"""Shared colors and widget rules for runtime theme changes."""


class ThemeManager:
    PALETTES = {
        "light": {
            "bg_main": "#f0f2f5", "bg_sidebar": "#ffffff", "bg_card": "#ffffff",
            "text_main": "#2c3e50", "text_muted": "#64748b", "border": "#e2e8f0",
            "border_focus": "#3b82f6", "primary": "#2563eb", "primary_hover": "#1d4ed8",
            "danger": "#dc2626", "danger_hover": "#b91c1c", "input_bg": "#f8fafc",
            "accent": "#0369a1", "warning": "#b45309", "success": "#047857",
            "chart_new": "#dc2626", "chart_progress": "#2563eb",
            "chart_packed": "#b45309", "chart_shipped": "#047857",
        },
        "modern": {
            "bg_main": "#0f172a", "bg_sidebar": "#020617", "bg_card": "#1e293b",
            "text_main": "#f8fafc", "text_muted": "#94a3b8", "border": "#334155",
            "border_focus": "#0ea5e9", "primary": "#0369a1", "primary_hover": "#075985",
            "danger": "#be123c", "danger_hover": "#9f1239", "input_bg": "#0f172a",
            "accent": "#38bdf8", "warning": "#fbbf24", "success": "#34d399",
            "chart_new": "#fb7185", "chart_progress": "#38bdf8",
            "chart_packed": "#fbbf24", "chart_shipped": "#34d399",
        },
        "dark": {
            "bg_main": "#1a1e29", "bg_sidebar": "#11141d", "bg_card": "#242933",
            "text_main": "#ffffff", "text_muted": "#a0a5b1", "border": "#3b4252",
            "border_focus": "#48dbfb", "primary": "#4a69bd", "primary_hover": "#3f5da8",
            "danger": "#8b0000", "danger_hover": "#a10000", "input_bg": "#2e3440",
            "accent": "#8fbcbb", "warning": "#feca57", "success": "#1dd1a1",
            "chart_new": "#ff6b6b", "chart_progress": "#54a0ff",
            "chart_packed": "#feca57", "chart_shipped": "#1dd1a1",
        },
    }

    @staticmethod
    def get_palette(theme_name=None):
        return ThemeManager.PALETTES.get(theme_name, ThemeManager.PALETTES["dark"]).copy()

    @staticmethod
    def apply_theme(app, theme_name, font_size_name):
        theme_name = theme_name if theme_name in ThemeManager.PALETTES else "dark"
        app.setProperty("theme_name", theme_name)
        app.setProperty("font_size_name", font_size_name)
        # Qt sends StyleChange to existing widgets; charts refresh their API colors.
        app.setStyleSheet(ThemeManager.get_stylesheet(theme_name, font_size_name))

    @staticmethod
    def get_stylesheet(theme_name, font_size_name):
        base_font = {"small": "12px", "medium": "14px", "large": "16px"}.get(font_size_name, "14px")
        p = ThemeManager.get_palette(theme_name)
        return f"""
            * {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: {base_font}; }}
            QMainWindow, QDialog, QWidget#central_widget {{ background-color: {p['bg_main']}; color: {p['text_main']}; }}
            QFrame {{ background-color: {p['bg_card']}; border: 1px solid {p['border']}; border-radius: 8px; }}
            QFrame#sidebar {{ background-color: {p['bg_sidebar']}; border: none; border-right: 1px solid {p['border']}; border-radius: 0; }}
            QFrame#orders_submenu {{ background: transparent; border: none; }}
            QFrame#settings_card {{ background-color: {p['bg_card']}; border-radius: 10px; }}
            QFrame#headers_frame {{ background-color: {p['bg_card']}; border-radius: 4px; font-weight: bold; }}
            QFrame#details_panel {{ background-color: {p['bg_card']}; border-radius: 4px; }}
            QFrame#accordion_row {{ background-color: {p['input_bg']}; border: none; border-bottom: 1px solid {p['border']}; border-radius: 0; }}
            QFrame#accordion_row[expanded="true"] {{ background-color: {p['border']}; }}
            QFrame#accordion_row QLabel {{ padding: 5px; }}
            QLabel {{ color: {p['text_main']}; background: transparent; border: none; }}
            QLabel#title_label {{ font-size: 18px; font-weight: bold; }}
            QLabel#muted_label {{ color: {p['text_muted']}; }}
            QLabel#accent_label, QLabel#column_label {{ color: {p['accent']}; }}
            QLabel#accent_label {{ margin-top: 15px; }}
            QLineEdit, QComboBox {{ background-color: {p['input_bg']}; color: {p['text_main']}; border: 1px solid {p['border']}; border-radius: 5px; padding: 6px; }}
            QLineEdit:focus, QComboBox:focus {{ border: 1px solid {p['border_focus']}; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background-color: {p['bg_card']}; color: {p['text_main']}; selection-background-color: {p['accent']}; selection-color: {p['bg_sidebar']}; border: 1px solid {p['border']}; outline: none; }}
            QComboBox QAbstractItemView::item {{ padding: 4px 6px; }}
            QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover {{ background-color: {p['accent']}; color: {p['bg_sidebar']}; }}
            QTableWidget {{ background-color: {p['bg_card']}; color: {p['text_main']}; gridline-color: {p['border']}; border: none; selection-background-color: {p['accent']}; selection-color: {p['bg_sidebar']}; }}
            QHeaderView::section {{ background-color: {p['bg_main']}; color: {p['accent']}; font-weight: bold; padding: 5px; border: none; border-bottom: 2px solid {p['border']}; }}
            QTableCornerButton::section {{ background-color: {p['bg_main']}; border: none; }}
            QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
            QChartView#chart_view {{ background: transparent; border: 1px solid {p['border']}; border-radius: 10px; }}
            QPushButton {{ background-color: {p['border']}; color: {p['text_main']}; border-radius: 5px; padding: 8px; border: none; }}
            QPushButton:hover {{ background-color: {p['input_bg']}; }}
            QPushButton:focus {{ border: 1px solid {p['border_focus']}; }}
            QPushButton#primary_btn {{ background-color: {p['primary']}; color: white; font-weight: bold; }}
            QPushButton#primary_btn:hover {{ background-color: {p['primary_hover']}; }}
            QPushButton#danger_btn {{ background-color: {p['danger']}; color: white; font-weight: bold; }}
            QPushButton#danger_btn:hover {{ background-color: {p['danger_hover']}; }}
            QPushButton#menu_btn {{ background: transparent; text-align: left; padding: 10px; color: {p['text_muted']}; border-radius: 0; font-weight: bold; }}
            QPushButton#menu_btn:hover {{ background-color: {p['bg_main']}; color: {p['accent']}; }}
            QPushButton#submenu_btn {{ background: transparent; text-align: left; padding: 5px; color: {p['accent']}; border-radius: 0; font-size: 13px; }}
            QPushButton#submenu_btn:hover {{ color: {p['text_main']}; }}
            QPushButton#tab_btn {{ background-color: {p['bg_main']}; color: {p['text_muted']}; border-radius: 15px; padding: 8px 20px; font-weight: bold; border: 1px solid {p['border']}; }}
            QPushButton#tab_btn:checked {{ background-color: {p['primary']}; color: white; border: none; }}
            QPushButton#tab_btn:hover:!checked {{ background-color: {p['border']}; }}
            QPushButton#action_btn {{ background: transparent; color: {p['accent']}; text-align: left; }}
            QPushButton#action_btn:hover {{ color: {p['text_main']}; }}
            QCheckBox {{ color: {p['text_main']}; background: transparent; }}
        """
