from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFrame, 
    QLabel, QScrollArea, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox
)
from PySide6.QtCore import Qt, QDate

# Import core modules
from utils.translations import translator

class ClickableRow(QFrame):
    """Frame that responds to clicks to expand the accordion."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_expanded = False
        self.details_panel = None

    def set_details_panel(self, panel):
        self.details_panel = panel

    def mousePressEvent(self, event):
        if self.details_panel:
            self.is_expanded = not self.is_expanded
            self.details_panel.setVisible(self.is_expanded)
            
            if self.is_expanded:
                self.setStyleSheet("QFrame { background-color: #3b4252; border-bottom: 1px solid #4c566a; } QLabel { color: white; }")
            else:
                self.setStyleSheet("QFrame { background-color: #2e3440; border-bottom: 1px solid #4c566a; } QLabel { color: #d8dee9; }")
        super().mousePressEvent(event)


class OrderAccordionItem(QWidget):
    """A single order row with an expandable details panel."""
    def __init__(self, data, translator_obj, parent=None):
        super().__init__(parent)
        self.t = translator_obj.t
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # --- MAIN ROW (Order Header) ---
        self.summary_row = ClickableRow()
        self.summary_row.setStyleSheet("QFrame { background-color: #2e3440; border-bottom: 1px solid #4c566a; } QLabel { color: #d8dee9; padding: 5px; }")
        self.summary_row.setCursor(Qt.PointingHandCursor)
        self.summary_layout = QHBoxLayout(self.summary_row)
        self.summary_layout.setContentsMargins(5, 5, 5, 5)

        columns = [
            (data['no'], 1), (data['date_in'], 2), (data['date_out'], 2), 
            (data['status'], 2), (data['net'], 1), (data['gross'], 1), 
            (data['pay'], 1), (data['pkg'], 1), (data['ship'], 1), (data['name'], 2)
        ]

        for text, stretch in columns:
            lbl = QLabel(text)
            self.summary_layout.addWidget(lbl, stretch)

        # --- DETAILS PANEL ---
        self.details_panel = QFrame()
        self.details_panel.setStyleSheet("background-color: #242933; border: 1px solid #3b4252;")
        self.details_layout = QHBoxLayout(self.details_panel)
        self.details_layout.setContentsMargins(15, 15, 15, 15)

        # Left side: Action buttons
        self.actions_layout = QVBoxLayout()
        self.actions_layout.setAlignment(Qt.AlignTop)
        
        actions = [
            self.t('act_edit'), self.t('act_pkg'), self.t('act_split'), 
            self.t('act_hold'), self.t('act_cancel')
        ]
        for act in actions:
            btn = QPushButton(act)
            btn.setStyleSheet("background-color: transparent; color: #8fbcbb; border: none; padding: 5px; text-align: left;")
            self.actions_layout.addWidget(btn)

        # Right side: Products table
        self.products_table = QTableWidget(3, 6)
        self.products_table.setHorizontalHeaderLabels([
            self.t('tbl_sku'), self.t('tbl_name'), self.t('tbl_qty'), 
            self.t('tbl_net'), self.t('tbl_gross'), self.t('tbl_weight')
        ])
        self.products_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.products_table.setStyleSheet("""
            QTableWidget { background-color: #2e3440; color: white; border: none; gridline-color: #4c566a; }
            QHeaderView::section { background-color: #242933; color: #8fbcbb; border: none; font-weight: bold; }
        """)
        
        mock_prod = ["GPU-0091", "Karta graficzna", "1 szt.", "2400.00 zł", "2952.00 zł", "1.70 kg"]
        for col, text in enumerate(mock_prod):
            self.products_table.setItem(0, col, QTableWidgetItem(text))

        self.details_layout.addLayout(self.actions_layout, 1)
        self.details_layout.addWidget(self.products_table, 5)

        self.details_panel.setVisible(False)
        self.summary_row.set_details_panel(self.details_panel)

        self.layout.addWidget(self.summary_row)
        self.layout.addWidget(self.details_panel)


class OrdersView(QWidget):
    def __init__(self, lang_code):
        super().__init__()
        self.translator = translator(lang_code, "translations_orders.json")
        self.t = self.translator.t
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 20, 20, 20)

        title_lbl = QLabel(f"<h2>{self.t('ord_title')}</h2>")
        title_lbl.setStyleSheet("color: white;")
        self.layout.addWidget(title_lbl)

        # --- TOP TOOLBAR (Filters, Dates, Global Actions) ---
        self.toolbar_layout = QHBoxLayout()
        
        # 1. Search boxes
        for ph in [self.t('ord_search_id'), self.t('ord_search_addr'), self.t('ord_search_sku')]:
            box = QLineEdit()
            box.setPlaceholderText(ph)
            box.setStyleSheet("background-color: #2e3440; color: white; border: 1px solid #4c566a; padding: 8px;")
            self.toolbar_layout.addWidget(box)
            
        # 2. Dropdown Date Filter (QComboBox)
        self.date_filter = QComboBox()
        self.date_filter.setStyleSheet("""
            QComboBox { background-color: #2e3440; color: white; border: 1px solid #4c566a; padding: 8px; font-weight: bold; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background-color: #2e3440; color: white; selection-background-color: #3b82f6; outline: none; border: 1px solid #4c566a; }
        """)
        
        self.date_filter.addItem(self.t('ord_filter_last_7'), "last_7")
        self.date_filter.addItem(self.t('ord_filter_this_week'), "this_week")
        self.date_filter.addItem(self.t('ord_filter_last_30'), "last_30")
        self.date_filter.addItem(self.t('ord_filter_this_month'), "this_month")
        self.date_filter.addItem(self.t('ord_filter_last_90'), "last_90")
        self.date_filter.addItem(self.t('ord_filter_this_year'), "this_year")
        self.date_filter.addItem(self.t('ord_filter_last_365'), "last_365")
        
        current_year = QDate.currentDate().year()
        oldest_order_year = 2024 
        for year in range(current_year, oldest_order_year - 1, -1):
            self.date_filter.addItem(f"{year}", f"year_{year}")

        self.toolbar_layout.addWidget(self.date_filter)

        # 3. Global Actions & Pagination Limits
        btn_add = QPushButton(self.t('act_add'))
        btn_add.setStyleSheet("background-color: #3b4252; color: white; border: 1px solid #4c566a; padding: 8px;")
        
        btn_import = QPushButton(self.t('act_import'))
        btn_import.setStyleSheet("background-color: #3b82f6; color: white; border: none; padding: 8px; font-weight: bold;")
        
        btn_markets = QPushButton(self.t('ord_btn_markets'))
        btn_markets.setStyleSheet("background-color: #3b4252; color: white; border: 1px solid #4c566a; padding: 8px;")

        # Dropdown Pagination Filter
        self.limit_filter = QComboBox()
        self.limit_filter.setStyleSheet("""
            QComboBox { background-color: #2e3440; color: white; border: 1px solid #4c566a; padding: 8px; font-weight: bold; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background-color: #2e3440; color: white; selection-background-color: #3b82f6; outline: none; border: 1px solid #4c566a; }
        """)
        
        # Add numeric limits WITH the translated unit (e.g. "50 zamówień"), but keep the raw integer as data
        unit = self.t('ord_limit_unit')
        for limit in ["50", "100", "250", "500"]:
            display_text = f"{limit} {unit}"
            self.limit_filter.addItem(display_text, int(limit))
            
        self.limit_filter.addItem(self.t('ord_limit_all'), 0)
        
        # Dodawanie elementów do układu jeden po drugim
        self.toolbar_layout.addWidget(btn_add)
        self.toolbar_layout.addWidget(btn_import)
        self.toolbar_layout.addWidget(btn_markets)
        
        limit_lbl = QLabel(f"<span style='color: white; margin-left: 10px;'>{self.t('ord_limit_label')}</span>")
        self.toolbar_layout.addWidget(limit_lbl)
        
        self.toolbar_layout.addWidget(self.limit_filter)

        self.layout.addLayout(self.toolbar_layout)

        # --- COLUMN HEADERS ---
        self.headers_frame = QFrame()
        self.headers_frame.setStyleSheet("background-color: #242933; border: 1px solid #4c566a; font-weight: bold;")
        self.headers_layout = QHBoxLayout(self.headers_frame)
        self.headers_layout.setContentsMargins(5, 10, 5, 10)

        header_labels = [
            (self.t('col_no'), 1), (self.t('col_date_in'), 2), (self.t('col_date_out'), 2), 
            (self.t('col_status'), 2), (self.t('col_net'), 1), (self.t('col_gross'), 1), 
            (self.t('col_pay'), 1), (self.t('col_pkg'), 1), (self.t('col_ship'), 1), (self.t('col_name'), 2)
        ]

        for text, stretch in header_labels:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #8fbcbb; border: none;")
            self.headers_layout.addWidget(lbl, stretch)

        self.layout.addWidget(self.headers_frame)

        # --- ORDERS LIST (ScrollArea) ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background-color: transparent;")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(0)

        for i in range(1, 15):
            mock_data = {
                'no': f"ORD-164{i:02d}", 'date_in': "2026-04-26 09:04", 'date_out': "-", 
                'status': "W realizacji", 'net': "13350", 'gross': "16420,5", 
                'pay': "-", 'pkg': "-", 'ship': "0", 'name': "Sylwester"
            }
            item = OrderAccordionItem(mock_data, self.translator)
            self.scroll_layout.addWidget(item)

        self.scroll_area.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll_area)