from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFrame, 
    QLabel, QScrollArea, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QStyledItemDelegate
)
from PySide6.QtCore import Qt, QDate

import csv
import json
import sqlite3
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox
from controllers.sales_controller import SalesController
from controllers.order_import import read_groups, import_group
from controllers.settings_controller import SettingsController
from views.orders.order_dialog import OrderDialog
from utils.translations import translator
from controllers.order_controller import OrderController

class ClickableRow(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_expanded = False
        self.setProperty("expanded", False)
        self.details_panel = None

    def set_details_panel(self, panel):
        self.details_panel = panel

    def mousePressEvent(self, event):
        if self.details_panel:
            self.is_expanded = not self.is_expanded
            self.details_panel.setVisible(self.is_expanded)
            self.setProperty("expanded", self.is_expanded)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
        super().mousePressEvent(event)


class OrderAccordionItem(QWidget):
    def __init__(self, order_data, translator_obj, controller, parent=None, action=None):
        super().__init__(parent)
        self.t = translator_obj.t
        self.controller = controller
        
        # Store values for in-memory filtering
        self.order_id_str = order_data['no'].lower()
        self.customer_str = order_data['name'].lower()
        self.status_str = order_data['status'].lower()
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Main summary row
        self.summary_row = ClickableRow()
        self.summary_row.setObjectName("accordion_row")
        self.summary_row.setCursor(Qt.PointingHandCursor)
        self.summary_layout = QHBoxLayout(self.summary_row)
        self.summary_layout.setContentsMargins(5, 5, 5, 5)

        columns = [
            (order_data['no'], 1), (order_data['date_in'], 2), (order_data['date_out'], 2), 
            (order_data['status'], 2), (order_data['net'], 1), (order_data['gross'], 1), 
            (order_data['pay'], 1), (order_data['pkg'], 1), (order_data['ship'], 1), (order_data['name'], 2)
        ]

        for text, stretch in columns:
            lbl = QLabel(str(text))
            self.summary_layout.addWidget(lbl, stretch)

        # Expanded details panel
        self.details_panel = QFrame()
        self.details_panel.setObjectName("details_panel")
        self.details_layout = QHBoxLayout(self.details_panel)
        self.details_layout.setContentsMargins(15, 15, 15, 15)

        self.actions_layout = QVBoxLayout()
        self.actions_layout.setAlignment(Qt.AlignTop)
        
        actions = [
            self.t('act_edit'), self.t('act_pkg'), self.t('act_split'), 
            self.t('act_hold'), self.t('act_cancel')
        ]
        for key, act in zip(('edit','packages','split','hold','cancel'), actions):
            btn = QPushButton(act)
            if key == "hold" and order_data.get("held"):
                btn.setText(self.t("resume"))
            if action:
                btn.clicked.connect(lambda checked=False,k=key: action(k,order_data["raw_id"]))
            btn.setObjectName("action_btn")
            self.actions_layout.addWidget(btn)

        items_data = self.controller.get_order_items(order_data['raw_id'])
        
        self.products_table = QTableWidget(len(items_data), 6)
        self.products_table.setHorizontalHeaderLabels([
            self.t('tbl_sku'), self.t('tbl_name'), self.t('tbl_qty'), 
            self.t('tbl_net'), self.t('tbl_gross'), self.t('tbl_weight')
        ])
        self.products_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.products_table.setObjectName("order_items_table")
        
        for row_idx, item in enumerate(items_data):
            sku = item['sku']
            name = item['name_pl']
            qty = item['quantity']
            gross_price = item['unit_price']
            unit_weight = item['weight']
            snapshot = json.loads(item["sale_snapshot"] or "{}")
            sku = snapshot.get("sku",sku)
            name = snapshot.get("name_"+translator_obj.lang_code,item["name_"+translator_obj.lang_code])
            unit_weight = snapshot.get("weight",unit_weight) or 0
            net_text = f"{snapshot['net_cents']/100:.2f} PLN" if snapshot else "-"
            total_gross = gross_price * qty
            total_weight = unit_weight * qty
            
            self.products_table.setItem(row_idx, 0, QTableWidgetItem(sku))
            self.products_table.setItem(row_idx, 1, QTableWidgetItem(name))
            self.products_table.setItem(row_idx, 2, QTableWidgetItem(f"{qty} {self.t('units_short','pcs')}"))
            self.products_table.setItem(row_idx, 3, QTableWidgetItem(net_text))
            self.products_table.setItem(row_idx, 4, QTableWidgetItem(f"{total_gross:.2f} PLN"))
            self.products_table.setItem(row_idx, 5, QTableWidgetItem(f"{total_weight:.2f} kg"))

        self.details_layout.addLayout(self.actions_layout, 1)
        self.details_layout.addWidget(self.products_table, 5)

        self.details_panel.setVisible(False)
        self.summary_row.set_details_panel(self.details_panel)

        self.layout.addWidget(self.summary_row)
        self.layout.addWidget(self.details_panel)


class OrdersView(QWidget):
    def __init__(self, translator_obj, db_path="warehouse.db"):
        super().__init__()
        # Use the global translator object passed from MainWindow instead of creating a new one
        self.translator = translator_obj
        self.t = self.translator.t
        self.controller = OrderController(db_path=db_path)
        
        self.sales = SalesController(db_path)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 20, 20, 20)

        title_lbl = QLabel(f"<h2>{self.t('ord_title')}</h2>")
        title_lbl.setObjectName("title_label")
        self.layout.addWidget(title_lbl)

        # --- TOP TOOLBAR ---
        self.toolbar_layout = QHBoxLayout()
        
        # Search fields with dynamic in-memory filtering
        self.search_id = QLineEdit()
        self.search_id.setPlaceholderText(self.t('ord_search_id'))
        
        self.search_addr = QLineEdit()
        self.search_addr.setPlaceholderText(self.t('ord_search_addr'))
        
        for box in [self.search_id, self.search_addr]:
            box.setObjectName("order_search")
            box.textChanged.connect(self.load_orders)
            self.toolbar_layout.addWidget(box)
            
        extra = QHBoxLayout()
        self.search_product = QLineEdit()
        self.search_channel = QLineEdit()
        for box,key in ((self.search_product,"product"),(self.search_channel,"channel")):
            box.setPlaceholderText(self.t(key,key))
            extra.addWidget(box)
            box.textChanged.connect(self.load_orders)
        self.date_filter = QComboBox()
        self.date_filter.setItemDelegate(QStyledItemDelegate(self.date_filter))
        self.date_filter.setObjectName("order_date_filter")
        
        # Default empty option to prevent immediate filtering
        self.date_filter.addItem(self.t("filter_date"), "")
        self.date_filter.addItem(self.t('ord_filter_last_7'), "last_7")
        self.date_filter.addItem(self.t('ord_filter_this_week'), "this_week")
        self.date_filter.addItem(self.t('ord_filter_last_30'), "last_30")
        self.date_filter.addItem(self.t('ord_filter_this_month'), "this_month")
        self.date_filter.addItem(self.t('ord_filter_last_90'), "last_90")
        self.date_filter.addItem(self.t('ord_filter_this_year'), "this_year")
        self.date_filter.addItem(self.t('ord_filter_last_365'), "last_365")
        
        current_year = QDate.currentDate().year()
        oldest_order_year = 2024 
        
        # Offset by -1 to prevent duplicating 'this_year' logic
        for year in range(current_year - 1, oldest_order_year - 1, -1):
            self.date_filter.addItem(str(year), f"year_{year}")
            
        self.date_filter.currentIndexChanged.connect(self.load_orders)
        self.toolbar_layout.addWidget(self.date_filter)

        # Global Actions
        btn_add = QPushButton(self.t('act_add'))
        btn_add.setObjectName("secondary_btn")
        
        btn_import = QPushButton(self.t('act_import'))
        btn_import.setObjectName("primary_btn")
        
        self.limit_filter = QComboBox()
        self.limit_filter.setItemDelegate(QStyledItemDelegate(self.limit_filter))
        self.limit_filter.setObjectName("order_limit_filter")
        
        unit = self.t('ord_limit_unit')
        for limit in ["50", "100", "250", "500"]:
            self.limit_filter.addItem(f"{limit} {unit}", int(limit))
        self.limit_filter.addItem(self.t('ord_limit_all'), 0)
        
        self.limit_filter.currentIndexChanged.connect(self.load_orders)

        self.toolbar_layout.addWidget(btn_add)
        self.toolbar_layout.addWidget(btn_import)
        self.toolbar_layout.addWidget(QLabel(self.t('ord_limit_label')))
        self.toolbar_layout.addWidget(self.limit_filter)

        btn_add.clicked.connect(lambda: self.order_action("edit",None))
        btn_import.clicked.connect(self.import_orders)
        self.layout.addLayout(self.toolbar_layout)
        self.layout.addLayout(extra)
        self.empty = QLabel(self.t("no_orders"))
        self.layout.addWidget(self.empty)

        # --- COLUMN HEADERS ---
        self.headers_frame = QFrame()
        self.headers_frame.setObjectName("headers_frame")
        self.headers_layout = QHBoxLayout(self.headers_frame)
        self.headers_layout.setContentsMargins(5, 10, 5, 10)

        header_labels = [
            (self.t('col_no'), 1), (self.t('col_date_in'), 2), (self.t('col_date_out'), 2), 
            (self.t('col_status'), 2), (self.t('col_net'), 1), (self.t('col_gross'), 1), 
            (self.t('col_pay'), 1), (self.t('col_pkg'), 1), (self.t('col_ship'), 1), (self.t('col_name'), 2)
        ]

        for text, stretch in header_labels:
            lbl = QLabel(text)
            lbl.setObjectName("column_label")
            self.headers_layout.addWidget(lbl, stretch)

        self.layout.addWidget(self.headers_frame)

        # --- ORDERS LIST (ScrollArea) ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        # Fix layout shifts by enforcing scrollbar visibility
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll_area.setObjectName("orders_scroll")

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("orders_scroll_content")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(0)

        self.scroll_area.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll_area)
        
        self.load_orders()

    def filter_orders_in_memory(self):
        """Locally filters UI items based on search input."""
        search_id_text = self.search_id.text().lower()
        search_addr_text = self.search_addr.text().lower()
        
        for i in range(self.scroll_layout.count()):
            widget = self.scroll_layout.itemAt(i).widget()
            if isinstance(widget, OrderAccordionItem):
                match_id = search_id_text in widget.order_id_str or search_id_text in widget.status_str
                match_addr = search_addr_text in widget.customer_str
                
                widget.setVisible(match_id and match_addr)

    def load_orders(self):
        """Fetches data from DB and rebuilds the scroll area."""
        while self.scroll_layout.count():
            child = self.scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
        limit = self.limit_filter.currentData()
        date_filter = self.date_filter.currentData()
        
        orders = self.controller.get_orders(limit=limit, date_filter=date_filter, identity=self.search_id.text(),
            destination=self.search_addr.text(), product=self.search_product.text(), channel=self.search_channel.text(), detailed=True)
        self.empty.setVisible(not orders)
        
        for order in orders:
            order_id = order['order_id']
            order_date = order['order_date']
            status_code = order['status_code']
            total_amount = order['total_amount']
            first_name = order['first_name']
            last_name = order['last_name']
            payment = order['payment_en'] if self.translator.lang_code == 'en' else order['payment']
            box_type = order['package_code']
            snapshot = json.loads(order["sales_snapshot"] or "{}")
            shipping = order["delivery_cents"]/100 if order["delivery_cents"] is not None else order["final_shipping_cost"]
            
            if order["sent_count"] and order["sent_count"] < order["parcel_count"]:
                status_code = f"{self.t('partially_sent')} {order['sent_count']}/{order['parcel_count']}"
            formatted_data = {
                'raw_id': order_id, 
                'no': f"ORD-{order_id:05d}",
                'date_in': order_date[:16], 
                'date_out': (order['dispatched_at'] or '-')[:16],
                'held': order['held'], 'status': self.t('held') if order['held'] else status_code,
                'net': f"{order['net_cents']/100:.2f}" if order["net_cents"] is not None else "-",
                'gross': f"{total_amount:.2f}", 
                'pay': payment or "-", 
                'pkg': box_type or snapshot.get('package_type') or "-",
                'ship': f"{shipping:.2f}" if shipping is not None else "-",
                'name': snapshot.get("customer_name",f"{first_name or ''} {last_name or ''}")
            }
            item = OrderAccordionItem(formatted_data, self.translator, self.controller, action=self.order_action)
            if snapshot:
                values = [order["channel"],order["external_ref"],*snapshot["recipient"].values(),*snapshot.get("billing",{}).values()]
                info = QLabel(" · ".join(str(v) for v in values if v))
                info.setTextFormat(Qt.PlainText)
                info.setWordWrap(True)
                item.actions_layout.addWidget(info)
            self.scroll_layout.addWidget(item)

    def order_action(self, action, order_id):
        try:
            if action == "edit":
                if OrderDialog(self.translator,self.sales,order_id,self).exec() != QDialog.Accepted:
                    return
            elif action in ("packages","split"):
                from views.orders.dispatch_view import DispatchDialog
                DispatchDialog(self.translator,self.controller.db_path,order_id,self).exec()
            else:
                order,_ = self.sales.details(order_id)
                if action == "cancel" and QMessageBox.question(self,self.t("act_cancel"),self.t("confirm_cancel")) != QMessageBox.Yes:
                    return
                self.sales.change_state(order_id,"resume" if action=="hold" and order["held"] else action)
            self.load_orders()
        except (sqlite3.Error, ValueError, OSError) as e:
            QMessageBox.warning(self,self.t("sale_order"),self.t(str(e),str(e)))

    def import_orders(self):
        folder = SettingsController().get_config().get("paths",{}).get("imports_default","")
        path,_ = QFileDialog.getOpenFileName(self,self.t("act_import"),folder,"CSV / JSON (*.csv *.json)")
        if not path:
            return
        try:
            groups = read_groups(path)
            preview = "\n".join(f"{k[0]} · {k[1]} · {len(rows)}" for k,rows in groups.items())
            if QMessageBox.question(self,self.t("act_import"),f"{self.t('orders_count')}: {len(groups)} · {self.t('lines_count')}: {sum(map(len,groups.values()))}\n{preview}") != QMessageBox.Yes:
                return
            choices = self.sales.choices()
            report = []
            for key,rows in groups.items():
                choice = None
                if not rows[0].get("Email"):
                    labels = [self.t("new_customer")] + [f"{r['customer_id']} · {r['first_name']} {r['last_name']}" for r in choices["customers"]]
                    selected,ok = QInputDialog.getItem(self,self.t("customer_id")," / ".join(key),labels,0,False)
                    if ok:
                        index = labels.index(selected)
                        choice = choices["customers"][index-1]["customer_id"] if index else "new"
                try:
                    oid = import_group(self.sales,rows,choices,choice)
                    result = f"{self.t('added')} ORD-{oid:05d}"
                except (ValueError,sqlite3.Error) as e:
                    result = self.t(str(e),self.t("rejected")+" · "+self.t(getattr(e,"field",None) or str(e),str(e)))
                report.append(" / ".join(key)+" · "+result)
            QMessageBox.information(self,self.t("act_import"),"\n".join(report))
            self.load_orders()
        except (ValueError,OSError,sqlite3.Error,csv.Error) as e:
            QMessageBox.warning(self,self.t("act_import"),self.t(str(e),str(e)))
