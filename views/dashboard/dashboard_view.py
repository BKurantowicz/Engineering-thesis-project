from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QFrame
)
from PySide6.QtCharts import (
    QChart, QChartView, QSplineSeries, QPieSeries, 
    QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis,
    QAbstractBarSeries
)
from PySide6.QtCore import Qt, QMargins, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from controllers.dashboard_controller import DashboardController

class DashboardView(QWidget):
    def __init__(self, translator, controller=None):
        super().__init__()
        self.translator = translator
        self.controller = controller 
        
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(25, 25, 25, 25)
        self.main_layout.setSpacing(25)

        self.setup_header()
        self.setup_trend_chart()

        self.bottom_layout = QHBoxLayout()
        self.bottom_layout.setSpacing(25)
        
        self.setup_capacity_chart()
        self.setup_status_chart()
        
        self.main_layout.addLayout(self.bottom_layout)
        
        self.main_layout.setStretch(1, 1)
        self.main_layout.setStretch(2, 1)

    def setup_header(self):
        header_layout = QHBoxLayout()
        
        title = QLabel(self.translator.t("dashboard_title", "Dashboard (WMS Analytics)"))
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
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
                border-radius: 6px;
                padding: 6px 12px;
                font-family: 'Segoe UI';
                font-size: 13px;
            }
            QComboBox::drop-down { border: none; }
        """)
        
        self.time_filter.currentIndexChanged.connect(self._on_filter_changed)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(filter_label)
        header_layout.addWidget(self.time_filter)
        
        self.main_layout.addLayout(header_layout)

    def _on_filter_changed(self, index):
        filter_map = {0: "7_days", 1: "this_month", 2: "this_year"}
        self.update_trend_chart(filter_map.get(index, "7_days"))

    def _create_base_chart(self, title_text):
        chart = QChart()
        chart.setTitle(title_text)
        
        title_font = QFont("Segoe UI", 12, QFont.Bold)
        chart.setTitleFont(title_font)
        chart.setTitleBrush(QColor("#ffffff"))
        
        chart.setBackgroundBrush(QColor("#1e2130"))
        chart.setPlotAreaBackgroundVisible(False)
        
        chart.legend().setLabelColor(QColor("#a0a0a0"))
        chart.legend().setFont(QFont("Segoe UI", 10))
        chart.legend().setAlignment(Qt.AlignTop)
        chart.setMargins(QMargins(10, 10, 10, 10))
        return chart

    def _create_chart_view(self, chart):
        view = QChartView(chart)
        view.setRenderHint(QPainter.Antialiasing) # Key for smooth lines
        view.setStyleSheet("background-color: transparent; border: 1px solid #3a3f58; border-radius: 10px;")
        return view

    def setup_trend_chart(self):
        self.trend_chart = self._create_base_chart("")
        
        # 1. Zmiana na QSplineSeries (gładkie, nowoczesne krzywe) + pogrubienie
        series_prev = QSplineSeries()
        series_prev.setName(self.translator.t("trend_prev", "Previous period"))
        pen_prev = QPen(QColor("#576574")) # Stonowany szary
        pen_prev.setWidth(3)
        series_prev.setPen(pen_prev)
        
        series_curr = QSplineSeries()
        series_curr.setName(self.translator.t("trend_curr", "Current period"))
        pen_curr = QPen(QColor("#48dbfb")) # Nowoczesny, jasny niebieski/cyan
        pen_curr.setWidth(4)
        series_curr.setPen(pen_curr)
        
        series_curr.setPointLabelsVisible(True)
        series_curr.setPointLabelsFormat("@yPoint")
        series_curr.setPointLabelsColor(QColor("white"))
        series_curr.setPointLabelsFont(QFont("Segoe UI", 11, QFont.Bold))
        series_curr.setPointLabelsClipping(False)
        
        self.trend_chart.addSeries(series_prev)
        self.trend_chart.addSeries(series_curr)
        
        # Osie
        axis_font = QFont("Segoe UI", 9)
        grid_color = QColor("#2d3246") # Bardziej subtelna siatka
        
        self.axis_x_trend = QBarCategoryAxis()
        self.axis_x_trend.setLabelsFont(axis_font)
        self.axis_x_trend.setLabelsColor(QColor("#a0a0a0"))
        self.axis_x_trend.setGridLineColor(grid_color)
        self.axis_x_trend.setLinePen(QPen(QColor("#4b526b"), 1))
        self.trend_chart.addAxis(self.axis_x_trend, Qt.AlignBottom)
        series_prev.attachAxis(self.axis_x_trend)
        series_curr.attachAxis(self.axis_x_trend)
        
        self.axis_y_trend = QValueAxis()
        self.axis_y_trend.setLabelsFont(axis_font)
        self.axis_y_trend.setLabelsColor(QColor("#a0a0a0"))
        self.axis_y_trend.setGridLineColor(grid_color)
        self.axis_y_trend.setLinePen(QPen(QColor("#4b526b"), 1))
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
        # 2. Zamiana zwykłego koła na elegancki wykres pierścieniowy (Donut)
        series.setHoleSize(0.45) 
        self.capacity_chart.addSeries(series)
        
        chart_view = self._create_chart_view(self.capacity_chart)
        self.bottom_layout.addWidget(chart_view)

    def setup_status_chart(self):
        self.status_chart = self._create_base_chart(self.translator.t("status_title", "Current Order Fulfillment Status"))
        
        # 3. Zmiana palety kolorów na pastelowe, nowoczesne odcienie
        set_new = QBarSet(self.translator.t("status_new", "New"))
        set_new.append([0])
        set_new.setColor(QColor("#ff6b6b")) # Pastelowy czerwony
        
        set_progress = QBarSet(self.translator.t("status_in_progress", "In Progress"))
        set_progress.append([0])
        set_progress.setColor(QColor("#54a0ff")) # Czysty niebieski
        
        set_packed = QBarSet(self.translator.t("status_packed", "Packed"))
        set_packed.append([0])
        set_packed.setColor(QColor("#feca57")) # Żółty/Pomarańczowy
        
        set_shipped = QBarSet(self.translator.t("status_shipped", "Shipped"))
        set_shipped.append([0])
        set_shipped.setColor(QColor("#1dd1a1")) # Miętowy zielony
        
        series = QBarSeries()
        series.append(set_new)
        series.append(set_progress)
        series.append(set_packed)
        series.append(set_shipped)
        
        series.setLabelsVisible(True)
        series.setLabelsPosition(QAbstractBarSeries.LabelsOutsideEnd)
        
        self.status_chart.addSeries(series)
        
        axis_font = QFont("Segoe UI", 9)
        grid_color = QColor("#2d3246")
        
        axis_x = QBarCategoryAxis()
        axis_x.append([""])
        self.status_chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)
        
        axis_y = QValueAxis()
        axis_y.setLabelsFont(axis_font)
        axis_y.setLabelsColor(QColor("#a0a0a0"))
        axis_y.setGridLineColor(grid_color)
        self.status_chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)

        chart_view = self._create_chart_view(self.status_chart)
        self.bottom_layout.addWidget(chart_view)

    def load_real_data(self):
        if not self.controller:
            return

        status_counts = self.controller.get_order_status_counts()
        series_bar = self.status_chart.series()[0]
        
        series_bar.barSets()[0].replace(0, status_counts.get("NEW", 0))
        series_bar.barSets()[1].replace(0, status_counts.get("IN_PROGRESS", 0))
        series_bar.barSets()[2].replace(0, status_counts.get("PACKED", 0))
        series_bar.barSets()[3].replace(0, status_counts.get("SHIPPED", 0))
        
        max_val = max(status_counts.values()) if status_counts.values() else 10
        self.status_chart.axes(Qt.Vertical)[0].setRange(0, max_val + (max_val * 0.3))

        capacity = self.controller.get_warehouse_capacity()
        series_pie = self.capacity_chart.series()[0]
        series_pie.clear()
        
        lbl_font = QFont("Segoe UI", 10)
        
        lbl_free = f"{self.translator.t('cap_free', 'Free space')} ({capacity['free_space']:.1f}%)"
        slice_free = series_pie.append(lbl_free, capacity['free_space'])
        slice_free.setColor(QColor("#48dbfb"))
        slice_free.setLabelVisible()
        slice_free.setLabelColor(QColor("#c8d6e5"))
        slice_free.setLabelFont(lbl_font)
        
        lbl_racks = f"{self.translator.t('cap_racks', 'Taken on racks')} ({capacity['taken_on_racks']:.1f}%)"
        slice_racks = series_pie.append(lbl_racks, capacity['taken_on_racks'])
        slice_racks.setColor(QColor("#ff9f43"))
        slice_racks.setLabelVisible()
        slice_racks.setLabelColor(QColor("#c8d6e5"))
        slice_racks.setLabelFont(lbl_font)
        
        lbl_pick = f"{self.translator.t('cap_picking', 'In picking')} ({capacity['in_picking']:.1f}%)"
        slice_picking = series_pie.append(lbl_pick, capacity['in_picking'])
        slice_picking.setColor(QColor("#1dd1a1"))
        slice_picking.setLabelVisible()
        slice_picking.setLabelColor(QColor("#c8d6e5"))
        slice_picking.setLabelFont(lbl_font)

        self.update_trend_chart("7_days")

    def update_trend_chart(self, filter_type):
        trend_data = self.controller.get_order_trend(filter_type)
        series_prev = self.trend_chart.series()[0]
        series_curr = self.trend_chart.series()[1] 
        
        if trend_data and trend_data['dates']:
            points_curr = []
            points_prev = []
            formatted_dates = []
            
            for i in range(len(trend_data['dates'])):
                points_curr.append(QPointF(i, trend_data['current'][i]))
                points_prev.append(QPointF(i, trend_data['previous'][i]))
                
                date_str = trend_data['dates'][i]
                if filter_type == "this_year":
                    formatted_dates.append(date_str) 
                else:
                    formatted_dates.append(date_str[-5:]) 
            
            series_curr.replace(points_curr)
            series_prev.replace(points_prev)
            
            self.axis_x_trend.clear()
            self.axis_x_trend.append(formatted_dates)
            
            # Wymuszenie stałego pochylenia dla lepszej estetyki
            self.axis_x_trend.setLabelsAngle(-45)
            
            max_curr = max(trend_data['current']) if trend_data['current'] else 0
            max_prev = max(trend_data['previous']) if trend_data['previous'] else 0
            max_trend = max(max_curr, max_prev)
            
            self.axis_y_trend.setRange(0, max_trend + (max_trend * 0.2) if max_trend > 0 else 10)
            self.trend_chart.update()
        else:
            series_curr.replace([])
            series_prev.replace([])
            self.axis_x_trend.clear()
            self.axis_x_trend.append(["No Data"])