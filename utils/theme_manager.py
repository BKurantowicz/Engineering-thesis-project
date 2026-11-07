"""Shared colors and widget rules for runtime theme changes."""

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractItemView, QTableWidget


class _TableSelectionStyle(QObject):
    """Apply row selection to tables created after the application's theme."""

    @staticmethod
    def prepare(table):
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Polish and isinstance(watched, QTableWidget):
            self.prepare(watched)
        return False


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
        if not hasattr(app, "_table_selection_style"):
            app._table_selection_style = _TableSelectionStyle(app)
            app.installEventFilter(app._table_selection_style)
        for widget in app.allWidgets():
            if isinstance(widget, QTableWidget):
                app._table_selection_style.prepare(widget)
        p = ThemeManager.get_palette(theme_name)
        palette = QPalette(app.palette())
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            for role, color in ((QPalette.Window, p['bg_main']), (QPalette.WindowText, p['text_main']),
                                (QPalette.Base, p['input_bg']), (QPalette.AlternateBase, p['bg_card']),
                                (QPalette.Text, p['text_main']), (QPalette.Button, p['border']),
                                (QPalette.ButtonText, p['text_main']), (QPalette.Highlight, p['primary']),
                                (QPalette.HighlightedText, '#ffffff'), (QPalette.ToolTipBase, p['bg_card']),
                                (QPalette.ToolTipText, p['text_main']), (QPalette.PlaceholderText, p['text_muted'])):
                palette.setColor(group, role, QColor(color))
        for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, QColor(p['text_muted']))
        app.setPalette(palette)
        # Qt sends StyleChange to existing widgets; charts refresh their API colors.
        app.setStyleSheet(ThemeManager.get_stylesheet(theme_name, font_size_name))

    @staticmethod
    def get_stylesheet(theme_name, font_size_name):
        base_font = {"small": "12px", "medium": "14px", "large": "16px"}.get(font_size_name, "14px")
        p = ThemeManager.get_palette(theme_name)
        return f"""
            * {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: {base_font}; }}
            QMainWindow, QDialog, QWidget#central_widget, QWidget#customers_view, QWidget#products_view, QWidget#picking_view {{ background-color: {p['bg_main']}; color: {p['text_main']}; }}
            QFrame {{ background-color: {p['bg_card']}; border: 1px solid {p['border']}; border-radius: 8px; }}
            QFrame#sidebar {{ background-color: {p['bg_sidebar']}; border: none; border-right: 1px solid {p['border']}; border-radius: 0; }}
            QFrame#orders_submenu {{ background: transparent; border: none; }}
            QFrame#settings_card {{ background-color: {p['bg_card']}; border-radius: 10px; }}
            QFrame#headers_frame {{ background-color: {p['bg_card']}; border-radius: 4px; font-weight: bold; }}
            QFrame#details_panel {{ background-color: {p['bg_card']}; border-radius: 4px; }}
            QFrame#accordion_row {{ background-color: {p['input_bg']}; border: 1px solid transparent; border-bottom: 1px solid {p['border']}; border-radius: 0; }}
            QFrame#accordion_row[expanded="true"] {{ background-color: {p['border']}; }}
            QFrame#accordion_row:hover {{ background-color: {p['border']}; }}
            QFrame#accordion_row:focus {{ border: 1px solid {p['border_focus']}; }}
            QFrame#accordion_row[selected="true"] {{ background-color: {p['primary']}; }}
            QFrame#accordion_row[selected="true"] QLabel {{ color: white; }}
            QFrame#accordion_row QLabel {{ padding: 5px; }}
            QLabel {{ color: {p['text_main']}; background: transparent; border: none; }}
            QLabel#title_label {{ font-size: 18px; font-weight: bold; }}
            QLabel#muted_label {{ color: {p['text_muted']}; }}
            QLabel#error_label {{ color: {p['chart_new']}; }}
            QLabel#accent_label, QLabel#column_label {{ color: {p['accent']}; }}
            QLabel#accent_label {{ margin-top: 15px; }}
            QLineEdit, QComboBox, QAbstractSpinBox, QTextEdit, QPlainTextEdit {{ background-color: {p['input_bg']}; color: {p['text_main']}; border: 1px solid {p['border']}; border-radius: 5px; padding: 6px; selection-background-color: {p['primary']}; selection-color: white; }}
            QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover, QTextEdit:hover, QPlainTextEdit:hover {{ border-color: {p['text_muted']}; }}
            QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {p['border_focus']}; }}
            QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{ background-color: {p['bg_card']}; color: {p['text_muted']}; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background-color: {p['bg_card']}; color: {p['text_main']}; selection-background-color: {p['accent']}; selection-color: {p['bg_sidebar']}; border: 1px solid {p['border']}; outline: none; }}
            QComboBox QAbstractItemView::item {{ padding: 4px 6px; }}
            QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover {{ background-color: {p['accent']}; color: {p['bg_sidebar']}; }}
            QTableWidget {{ background-color: {p['bg_card']}; alternate-background-color: {p['input_bg']}; color: {p['text_main']}; gridline-color: {p['border']}; border: 1px solid transparent; outline: none; selection-background-color: {p['primary']}; selection-color: white; }}
            QTableWidget:focus {{ border-color: {p['border_focus']}; }}
            QTableWidget::item {{ border: none; }}
            QTableWidget::item:hover:!selected {{ background-color: {p['border']}; color: {p['text_main']}; }}
            QTableWidget::item:selected, QTableWidget::item:selected:active, QTableWidget::item:selected:!active {{ background-color: {p['primary']}; color: white; }}
            QHeaderView::section {{ background-color: {p['bg_main']}; color: {p['accent']}; font-weight: bold; padding: 5px; border: none; border-bottom: 2px solid {p['border']}; }}
            QTableCornerButton::section {{ background-color: {p['bg_main']}; border: none; }}
            QProgressBar#capacity_bar {{ background-color: {p['input_bg']}; border: 1px solid {p['border']}; border-radius: 4px; }}
            QProgressBar#capacity_bar::chunk {{ background-color: {p['accent']}; border-radius: 3px; }}
            QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
            QChartView#chart_view {{ background: transparent; border: 1px solid {p['border']}; border-radius: 10px; }}
            QPushButton {{ background-color: {p['border']}; color: {p['text_main']}; border-radius: 5px; padding: 8px; border: 1px solid transparent; }}
            QPushButton:hover {{ background-color: {p['input_bg']}; color: {p['text_main']}; border-color: {p['text_muted']}; }}
            QPushButton:pressed, QPushButton:checked {{ background-color: {p['primary']}; color: white; }}
            QPushButton:focus {{ border-color: {p['border_focus']}; }}
            QPushButton#primary_btn {{ background-color: {p['primary']}; color: white; font-weight: bold; }}
            QPushButton#primary_btn:hover {{ background-color: {p['primary_hover']}; }}
            QPushButton#danger_btn {{ background-color: {p['danger']}; color: white; font-weight: bold; }}
            QPushButton#danger_btn:hover {{ background-color: {p['danger_hover']}; }}
            QPushButton#menu_btn {{ background: transparent; text-align: left; padding: 10px; color: {p['text_muted']}; border-radius: 0; font-weight: bold; }}
            QPushButton#menu_btn:hover {{ background-color: {p['bg_main']}; color: {p['accent']}; }}
            QPushButton#submenu_btn {{ background: transparent; text-align: left; padding: 5px; color: {p['accent']}; border-radius: 0; font-size: 13px; }}
            QPushButton#submenu_btn:hover {{ color: {p['text_main']}; }}
            QPushButton#tab_btn {{ background-color: {p['bg_main']}; color: {p['text_main']}; border-radius: 15px; padding: 8px 20px; font-weight: bold; border: 1px solid {p['border']}; }}
            QPushButton#tab_btn:checked {{ background-color: {p['primary']}; color: white; }}
            QPushButton#tab_btn:hover:!checked {{ background-color: {p['border']}; color: {p['text_main']}; }}
            QPushButton#tab_btn:pressed, QPushButton#tab_btn:hover:pressed:!checked {{ background-color: {p['primary_hover']}; color: white; }}
            QPushButton#tab_btn:focus {{ border-color: {p['border_focus']}; }}
            QPushButton#action_btn {{ background: transparent; color: {p['accent']}; text-align: left; }}
            QPushButton#action_btn:hover {{ color: {p['text_main']}; }}
            QPushButton#primary_btn:pressed {{ background-color: {p['primary_hover']}; color: white; }}
            QPushButton#danger_btn:pressed {{ background-color: {p['danger_hover']}; color: white; }}
            QPushButton#menu_btn:pressed, QPushButton#submenu_btn:pressed, QPushButton#action_btn:pressed {{ background-color: {p['primary']}; color: white; }}
            QPushButton:disabled, QPushButton#primary_btn:disabled, QPushButton#danger_btn:disabled, QPushButton#menu_btn:disabled, QPushButton#submenu_btn:disabled, QPushButton#tab_btn:disabled, QPushButton#action_btn:disabled {{ background-color: {p['bg_card']}; color: {p['text_muted']}; border: 1px solid {p['border']}; }}
            QTabWidget::pane {{ background-color: {p['bg_card']}; border: 1px solid {p['border']}; }}
            QTabBar::tab {{ background-color: {p['input_bg']}; color: {p['text_main']}; padding: 9px 14px; border: 1px solid {p['border']}; }}
            QTabBar::tab:hover:!selected {{ background-color: {p['border']}; color: {p['text_main']}; }}
            QTabBar::tab:selected {{ background-color: {p['primary']}; color: white; }}
            QTabBar::tab:focus {{ border-color: {p['border_focus']}; }}
            QTabBar::tab:disabled {{ background-color: {p['bg_card']}; color: {p['text_muted']}; }}
            QToolTip {{ background-color: {p['bg_card']}; color: {p['text_main']}; border: 1px solid {p['border']}; padding: 5px; }}
            QCheckBox {{ color: {p['text_main']}; background: transparent; }}
            QCheckBox:disabled {{ color: {p['text_muted']}; }}
        """
