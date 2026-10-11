from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QFrame, QGridLayout
)
from PySide6.QtCharts import (
    QChart, QChartView, QLineSeries, QPieSeries, 
    QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis,
    QAbstractBarSeries
)
from PySide6.QtCore import Qt, QMargins
from PySide6.QtGui import QPainter, QColor, QFont
from controllers.dashboard_controller import DashboardController

class DashboardView(QWidget):
    def __init__(self, translator, controller=None):
        super().__init__()
        self.translator = translator
        self.controller = controller 
        
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)

        self.setup_header()
        self.setup_trend_chart()

        self.bottom_layout = QHBoxLayout()
        self.bottom_layout.setSpacing(20)
        
        self.setup_capacity_chart()
        self.setup_status_chart()
        
        self.main_layout.addLayout(self.bottom_layout)
        
        self.main_layout.setStretch(1, 1)
        self.main_layout.setStretch(2, 1)

    def setup_header(self):
        header_layout = QHBoxLayout()
        
        title = QLabel(self.translator.t("dashboard_title", "Dashboard (WMS Analytics)"))
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setStyleSheet("color: white;")
        
        filter_label = QLabel(self.translator.t("dashboard_trend_label", "Order inflow trend analysis:"))
        filter_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
        
        self.time_filter = QComboBox()
        self.time_filter.addItems([
            self.translator.t("filter_7_days", "Last 7 days"), 
            self.translator.t("filter_month", "This month"), 
            self.translator.t("filter_year", "This year")
        ])
        self.time_filter.setStyleSheet("""
            QComboBox {
                background-color: #1e2130;
                color: white;
                border: 1px solid #3a3f58;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        
        # Connect the combobox to dynamically update the trend chart
        self.time_filter.currentIndexChanged.connect(self._on_filter_changed)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(filter_label)
        header_layout.addWidget(self.time_filter)
        
        self.main_layout.addLayout(header_layout)

    def _on_filter_changed(self, index):
        """Maps combobox index to a strict controller filter identifier"""
        filter_map = {0: "7_days", 1: "this_month", 2: "this_year"}
        self.update_trend_chart(filter_map.get(index, "7_days"))

    def _create_base_chart(self, title_text):
        chart = QChart()
        chart.setTitle(title_text)
        chart.setTitleBrush(QColor("white"))
        chart.setBackgroundBrush(QColor("#1e2130"))
        chart.setPlotAreaBackgroundVisible(False)
        chart.legend().setLabelColor(QColor("#a0a0a0"))
        chart.legend().setAlignment(Qt.AlignTop)
        chart.setMargins(QMargins(0, 0, 0, 0))
        return chart

    def _create_chart_view(self, chart):
        view = QChartView(chart)
        view.setRenderHint(QPainter.Antialiasing)
        view.setStyleSheet("background-color: transparent; border: 1px solid #3a3f58; border-radius: 8px;")
        return view

    def setup_trend_chart(self):
        self.trend_chart = self._create_base_chart("")
        
        series_prev = QLineSeries()
        series_prev.setName(self.translator.t("trend_prev", "Previous period"))
        series_prev.setColor(QColor("#5a5a5a"))
        
        series_curr = QLineSeries()
        series_curr.setName(self.translator.t("trend_curr", "Current period"))
        series_curr.setColor(QColor("#4a69bd"))
        
        series_curr.setPointLabelsVisible(True)
        series_curr.setPointLabelsFormat("@yPoint")
        series_curr.setPointLabelsColor(QColor("white"))
        series_curr.setPointLabelsClipping(False)
        
        self.trend_chart.addSeries(series_prev)
        self.trend_chart.addSeries(series_curr)
        
        self.axis_x_trend = QBarCategoryAxis()
        self.axis_x_trend.setLabelsColor(QColor("#a0a0a0"))
        self.axis_x_trend.setGridLineColor(QColor("#3a3f58"))
        self.trend_chart.addAxis(self.axis_x_trend, Qt.AlignBottom)
        series_prev.attachAxis(self.axis_x_trend)
        series_curr.attachAxis(self.axis_x_trend)
        
        self.axis_y_trend = QValueAxis()
        self.axis_y_trend.setLabelsColor(QColor("#a0a0a0"))
        self.axis_y_trend.setGridLineColor(QColor("#3a3f58"))
        self.axis_y_trend.setLabelFormat("%d") 
        self.trend_chart.addAxis(self.axis_y_trend, Qt.AlignLeft)
        series_prev.attachAxis(self.axis_y_trend)
        series_curr.attachAxis(self.axis_y_trend)

        chart_view = self._create_chart_view(self.trend_chart)
        self.main_layout.addWidget(chart_view)

    def setup_capacity_chart(self):
        self.capacity_chart = self._create_base_chart(self.translator.t("cap_title", "Warehouse Capacity"))
        self.capacity_chart.legend().hide() 
        series = QPieSeries()
        self.capacity_chart.addSeries(series)
        chart_view = self._create_chart_view(self.capacity_chart)
        self.bottom_layout.addWidget(chart_view)

    def setup_status_chart(self):
        self.status_chart = self._create_base_chart(self.translator.t("status_title", "Current Order Fulfillment Status"))
        
        set_new = QBarSet(self.translator.t("status_new", "New"))
        set_new.append([0])
        set_new.setColor(QColor("#FF4500"))
        
        set_progress = QBarSet(self.translator.t("status_in_progress", "In Progress"))
        set_progress.append([0])
        set_progress.setColor(QColor("#1E90FF"))
        
        set_packed = QBarSet(self.translator.t("status_packed", "Packed"))
        set_packed.append([0])
        set_packed.setColor(QColor("#FFA500"))
        
        set_shipped = QBarSet(self.translator.t("status_shipped", "Shipped"))
        set_shipped.append([0])
        set_shipped.setColor(QColor("#32CD32"))
        
        series = QBarSeries()
        series.append(set_new)
        series.append(set_progress)
        series.append(set_packed)
        series.append(set_shipped)
        
        series.setLabelsVisible(True)
        series.setLabelsPosition(QAbstractBarSeries.LabelsOutsideEnd)
        
        self.status_chart.addSeries(series)
        
        axis_x = QBarCategoryAxis()
        axis_x.append([""])
        self.status_chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)
        
        axis_y = QValueAxis()
        axis_y.setLabelsColor(QColor("#a0a0a0"))
        axis_y.setGridLineColor(QColor("#3a3f58"))
        axis_y.setLabelFormat("%d")
        self.status_chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)

        chart_view = self._create_chart_view(self.status_chart)
        self.bottom_layout.addWidget(chart_view)

    def load_real_data(self):
        """Initial data load during startup"""
        if not self.controller:
            return

        # --- 1. Bar chart update (Backlog + Latest Shipped) ---
        status_counts = self.controller.get_order_status_counts()
        series_bar = self.status_chart.series()[0]
        
        # Replace data instead of appending to prevent UI glitches
        series_bar.barSets()[0].replace(0, status_counts.get("NEW", 0))
        series_bar.barSets()[1].replace(0, status_counts.get("IN_PROGRESS", 0))
        series_bar.barSets()[2].replace(0, status_counts.get("PACKED", 0))
        series_bar.barSets()[3].replace(0, status_counts.get("SHIPPED", 0))
        
        max_val = max(status_counts.values()) if status_counts.values() else 10
        self.status_chart.axes(Qt.Vertical)[0].setRange(0, max_val + (max_val * 0.3))

        # --- 2. Pie chart update ---
        capacity = self.controller.get_warehouse_capacity()
        series_pie = self.capacity_chart.series()[0]
        series_pie.clear()
        
        lbl_free = f"{self.translator.t('cap_free', 'Free space')} ({capacity['free_space']:.1f}%)"
        slice_free = series_pie.append(lbl_free, capacity['free_space'])
        slice_free.setColor(QColor("#87CEFA"))
        slice_free.setLabelVisible()
        slice_free.setLabelColor(QColor("#a0a0a0"))
        
        lbl_racks = f"{self.translator.t('cap_racks', 'Taken on racks')} ({capacity['taken_on_racks']:.1f}%)"
        slice_racks = series_pie.append(lbl_racks, capacity['taken_on_racks'])
        slice_racks.setColor(QColor("#FF7F50"))
        slice_racks.setLabelVisible()
        slice_racks.setLabelColor(QColor("#a0a0a0"))
        
        lbl_pick = f"{self.translator.t('cap_picking', 'In picking')} ({capacity['in_picking']:.1f}%)"
        slice_picking = series_pie.append(lbl_pick, capacity['in_picking'])
        slice_picking.setColor(QColor("#98FB98"))
        slice_picking.setLabelVisible()
        slice_picking.setLabelColor(QColor("#a0a0a0"))

        # --- 3. Trend line initial load ---
        self.update_trend_chart("7_days")

    def update_trend_chart(self, filter_type):
        """Re-fetches and redraws only the trend chart based on combobox filter"""
        trend_data = self.controller.get_order_trend(filter_type)
        series_curr = self.trend_chart.series()[1] 
        series_curr.clear()
        
        if trend_data:
            dates = []
            for i, (date_str, count) in enumerate(trend_data.items()):
                series_curr.append(i, count)
                if filter_type == "this_year":
                    dates.append(date_str) # Shows YYYY-MM
                else:
                    dates.append(date_str[-5:]) # Shows MM-DD
            
            self.axis_x_trend.clear()
            self.axis_x_trend.append(dates)
            
            # Tilt X-axis labels if there are many data points (e.g., 30 days) to prevent overlapping
            if len(dates) > 10:
                self.axis_x_trend.setLabelsAngle(-45)
            else:
                self.axis_x_trend.setLabelsAngle(0)
            
            max_trend = max(trend_data.values()) if trend_data.values() else 10
            self.axis_y_trend.setRange(0, max_trend + (max_trend * 0.2))
        else:
            self.axis_x_trend.clear()
            self.axis_x_trend.append(["No Data"])