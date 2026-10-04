import sys
import json
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, 
    QVBoxLayout, QPushButton, QStackedWidget, QLabel, QFrame
)
from PySide6.QtCore import Qt

# Import core modules
from models.database import DatabaseManager
from utils.translations import Translator

# Target view imports (to be implemented as we build modules)
# from views.main_dashboard.dashboard_view import DashboardView
# from views.orders.orders_view import OrdersView
# from views.products.products_view import ProductsView
# from views.settings.settings_view import SettingsView

class MainWindow(QMainWindow):
    """Main application window acting as the router/container for all views."""
    def __init__(self, config, translator):
        super().__init__()
        self.config = config
        self.t = translator.t  # Shortcut to translation function
        
        # Initialize database manager
        db_path = self.config.get("paths", {}).get("database", "warehouse.db")
        self.db = DatabaseManager(db_path)

        # Set window title using translation dictionary
        self.setWindowTitle(self.t("app_title"))
        self.resize(1280, 720)

        # Basic dark theme stylesheet
        self.setStyleSheet("""
            QMainWindow { background-color: #1a1e29; color: #ffffff; }
            QPushButton { 
                background-color: transparent; color: #a0a5b1; 
                text-align: left; padding: 10px; border: none; font-size: 14px;
            }
            QPushButton:hover { color: #ffffff; background-color: #2a2f3a; }
            QLabel { color: #ffffff; }
        """)

        # Main layout structure
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Build UI components
        self.setup_sidebar()
        self.setup_content_area()

    def setup_sidebar(self):
        """Creates the left navigation panel with menu buttons."""
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setFixedWidth(250)
        self.sidebar_frame.setStyleSheet("background-color: #11141d;")
        
        self.sidebar_layout = QVBoxLayout(self.sidebar_frame)
        self.sidebar_layout.setContentsMargins(10, 20, 10, 20)
        self.sidebar_layout.setAlignment(Qt.AlignTop)

        # Initialize sidebar buttons using translation keys
        self.btn_dashboard = QPushButton(self.t("menu_dashboard"))
        self.btn_orders = QPushButton(self.t("menu_orders"))
        self.btn_products = QPushButton(self.t("menu_products"))
        self.btn_settings = QPushButton(self.t("menu_settings"))
        self.btn_exit = QPushButton(self.t("menu_exit"))
        
        # Style exit button differently
        self.btn_exit.setStyleSheet("background-color: #8b0000; color: white; text-align: center;")

        # Add widgets to sidebar layout
        self.sidebar_layout.addWidget(self.btn_dashboard)
        self.sidebar_layout.addWidget(self.btn_orders)
        self.sidebar_layout.addWidget(self.btn_products)
        self.sidebar_layout.addWidget(self.btn_settings)
        self.sidebar_layout.addStretch()
        self.sidebar_layout.addWidget(self.btn_exit)

        # Connect button signals to stacked widget index switcher
        self.btn_dashboard.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        self.btn_orders.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))
        self.btn_products.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))
        self.btn_settings.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(3))
        self.btn_exit.clicked.connect(self.close)

        self.main_layout.addWidget(self.sidebar_frame)

    def setup_content_area(self):
        """Sets up the central stacked widget for switching views."""
        self.stacked_widget = QStackedWidget()
        
        # Temporary placeholder views (to be replaced with actual view classes)
        self.view_dashboard = QLabel(f"<h2>{self.t('menu_dashboard')}</h2>")
        self.view_orders = QLabel(f"<h2>{self.t('menu_orders')}</h2>")
        self.view_products = QLabel(f"<h2>{self.t('menu_products')}</h2>")
        self.view_settings = QLabel(f"<h2>{self.t('menu_settings')}</h2>")

        # Add placeholders to stack container
        for view in [self.view_dashboard, self.view_orders, self.view_products, self.view_settings]:
            view.setAlignment(Qt.AlignCenter)
            self.stacked_widget.addWidget(view)

        self.main_layout.addWidget(self.stacked_widget)


def load_config():
    """Loads application configuration from the root config.json file."""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("Warning: config.json not found! Falling back to defaults.")
        return {"appearance": {"language": "pl"}}


if __name__ == "__main__":
    # Initialize Qt Application instance
    app = QApplication(sys.argv)
    
    # Load configuration and language translator prior to UI rendering
    config = load_config()
    lang_code = config.get("appearance", {}).get("language", "pl")
    translator = Translator(lang_code)
    
    # Instantiate and display the main window
    window = MainWindow(config, translator)
    window.show()
    
    # Execute application event loop
    sys.exit(app.exec())