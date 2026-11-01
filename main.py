import sys
import json
import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, 
    QVBoxLayout, QPushButton, QStackedWidget, QLabel, QFrame
)
from PySide6.QtCore import Qt

# Import core modules
from models.database import DatabaseManager
from utils.translations import translator
from views.orders.orders_view import OrdersView
from controllers.dashboard_controller import DashboardController
from views.dashboard.dashboard_view import DashboardView
from views.settings.settings_view import SettingsView
from controllers.settings_controller import SettingsController
from controllers.customer_controller import CustomerController
from views.customers.customers_view import CustomersView
from utils.theme_manager import ThemeManager

class MainWindow(QMainWindow):
    """Main application window acting as the router/container for all views."""
    def __init__(self, config, translator):
        super().__init__()
        self.config = config
        self.translator = translator 
        self.t = translator.t 
        
        # Safely retrieve values with fallbacks to prevent missing key errors
        self.lang_code = self.config.get("localization", {}).get("language", "en")
        
        # Safely retrieve database path; fallback to 'warehouse.db' if missing
        self.db_path = self.config.get("paths", {}).get("database", "warehouse.db")
        self.db = DatabaseManager(self.db_path)

        self.setWindowTitle(self.t("app_title", "WMS System"))
        self.resize(1280, 720)

        # Shared stylesheet rules use semantic object names.
        self.setObjectName("main_window")

        # Main layout structure
        self.central_widget = QWidget()
        self.central_widget.setObjectName("central_widget")
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
        self.sidebar_frame.setObjectName("sidebar")
        
        self.sidebar_layout = QVBoxLayout(self.sidebar_frame)
        self.sidebar_layout.setContentsMargins(10, 20, 10, 20)
        self.sidebar_layout.setAlignment(Qt.AlignTop)

        # Main buttons
        self.btn_dashboard = QPushButton(self.t("menu_dashboard", "Dashboard"))
        self.btn_orders = QPushButton(self.t("menu_orders", "Orders"))
        
        # --- ORDERS SUB-MENU ACCORDION ---
        self.orders_submenu = QFrame()
        self.orders_submenu_layout = QVBoxLayout(self.orders_submenu)
        self.orders_submenu_layout.setContentsMargins(30, 0, 0, 0) 
        self.orders_submenu_layout.setSpacing(5)
        
        self.btn_sub_overview = QPushButton(self.t("menu_orders_sub_overview", "Overview"))
        self.btn_sub_picklists = QPushButton(self.t("menu_orders_sub_picklists", "Pick Lists"))
        self.btn_sub_packing = QPushButton(self.t("menu_orders_sub_packing", "Packing"))
        self.btn_sub_lists = QPushButton(self.t("menu_orders_sub_lists", "My Lists"))
        self.btn_sub_confirm = QPushButton(self.t("menu_orders_sub_confirm", "Confirmations"))
        
        for btn in [self.btn_sub_overview, self.btn_sub_picklists, self.btn_sub_packing, self.btn_sub_lists, self.btn_sub_confirm]:
            btn.setObjectName("submenu_btn")
            self.orders_submenu_layout.addWidget(btn)
            
        self.orders_submenu.setVisible(False)
        
        # Rest of the main menu
        self.btn_products = QPushButton(self.t("menu_products", "Products"))
        self.btn_customers = QPushButton(self.t("menu_customers", "Customers"))
        self.btn_settings = QPushButton(self.t("menu_settings", "Settings"))
        self.btn_exit = QPushButton(self.t("menu_exit", "Exit"))
        self.btn_exit.setObjectName("danger_btn")

        for button in (self.btn_dashboard, self.btn_orders, self.btn_products, self.btn_customers, self.btn_settings):
            button.setObjectName("menu_btn")
        self.orders_submenu.setObjectName("orders_submenu")

        # Add everything to the main sidebar layout
        self.sidebar_layout.addWidget(self.btn_dashboard)
        self.sidebar_layout.addWidget(self.btn_orders)
        self.sidebar_layout.addWidget(self.orders_submenu)
        self.sidebar_layout.addWidget(self.btn_products)
        self.sidebar_layout.addWidget(self.btn_customers)
        self.sidebar_layout.addWidget(self.btn_settings)
        self.sidebar_layout.addStretch()
        self.sidebar_layout.addWidget(self.btn_exit)

        # --- ROUTING / SWITCHING LOGIC ---
        self.btn_dashboard.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        self.btn_orders.clicked.connect(lambda: self.orders_submenu.setVisible(not self.orders_submenu.isVisible()))
        self.btn_sub_overview.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))
        self.btn_products.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))
        self.btn_customers.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.view_customers))
        
        # Bind Settings view to index 3
        self.btn_settings.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(3))
        self.btn_exit.clicked.connect(self.close)

        self.main_layout.addWidget(self.sidebar_frame)

    def setup_content_area(self):
        """Sets up the central stacked widget for switching views."""
        self.stacked_widget = QStackedWidget()
        
        # 1. Initialize Dashboard Controller and View
        self.dashboard_ctrl = DashboardController(db_path=self.db_path)
        self.view_dashboard = DashboardView(translator=self.translator, controller=self.dashboard_ctrl)
        self.view_dashboard.load_real_data()
        
        # 2. Initialize Orders View with global translator
        self.view_orders = OrdersView(translator_obj=self.translator, db_path=self.db_path)
        
        # 3. Initialize Products (Placeholder)
        self.view_products = QLabel(f"<h2>{self.t('menu_products', 'Products')}</h2>")
        self.view_products.setAlignment(Qt.AlignCenter)

        # 4. Initialize Settings View and Controller
        self.settings_ctrl = SettingsController()
        self.view_settings = SettingsView(translator=self.translator, controller=self.settings_ctrl)
        self.view_settings.load_settings()

        self.customer_ctrl = CustomerController(self.db_path)
        self.view_customers = CustomersView(self.translator, self.customer_ctrl)

        # Add all views to stack container in exact order of indices
        self.stacked_widget.addWidget(self.view_dashboard) # Index 0
        self.stacked_widget.addWidget(self.view_orders)    # Index 1
        self.stacked_widget.addWidget(self.view_products)  # Index 2
        self.stacked_widget.addWidget(self.view_settings)  # Index 3
        self.stacked_widget.addWidget(self.view_customers)

        self.main_layout.addWidget(self.stacked_widget)


def load_config():
    """Loads application configuration from the root config.json file."""
    if not os.path.exists('config.json'):
        # Return a safe fallback structure if the file is missing
        return {
            "localization": {"language": "en"},
            "paths": {"database": "warehouse.db"}
        }
        
    with open('config.json', 'r', encoding='utf-8') as f:
        return json.load(f)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    config = load_config()
    lang_code = config.get("localization", {}).get("language", "pl")
    lang_translator = translator(lang_code, "utils")
    
    window = MainWindow(config, lang_translator)
    
    theme_name = config.get("appearance", {}).get("theme", "dark")
    font_size = config.get("appearance", {}).get("font_size", "medium")
    
    # Apply the shared widget and chart theme before showing the window.
    ThemeManager.apply_theme(app, theme_name, font_size)
    
    window.show()
    sys.exit(app.exec())
