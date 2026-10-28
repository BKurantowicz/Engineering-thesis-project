from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QFrame, QApplication, QStyledItemDelegate
)
from PySide6.QtCharts import (
    QChart, QChartView, QSplineSeries, QPieSeries, 
    QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis,
    QAbstractBarSeries
)
from PySide6.QtCore import Qt, QMargins, QPointF, QEvent
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from controllers.dashboard_controller import DashboardController
from utils.theme_manager import ThemeManager

class DashboardView(QWidget):
    def __init__(self, translator, controller=None):
        super().__init__()
        self.translator = translator
        self.controller = controller 
        
        self.setup_ui()
        self.apply_chart_theme()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.StyleChange and hasattr(self, "status_chart"):
            self.apply_chart_theme()

    def apply_chart_theme(self):
        """Refresh existing chart objects without replacing their data or state."""
        app = QApplication.instance()
        palette = ThemeManager.get_palette(app.property("theme_name") if app else None)
        for chart in (self.trend_chart, self.capacity_chart, self.status_chart):
            chart.setBackgroundBrush(QColor(palette["bg_card"]))
            chart.setPlotAreaBackgroundBrush(QColor(palette["bg_card"]))
            chart.setTitleBrush(QColor(palette["text_main"]))
            chart.legend().setLabelColor(QColor(palette["text_main"]))
            for axis in chart.axes():
                axis.setLabelsColor(QColor(palette["text_main"]))
                axis.setTitleBrush(QColor(palette["text_main"]))
                axis.setGridLineColor(QColor(palette["border"]))
                axis.setLinePen(QPen(QColor(palette["text_muted"]), 1))
        for series, color in zip(self.trend_chart.series(), ("text_muted", "accent")):
            pen = series.pen()
            pen.setColor(QColor(palette[color]))
            series.setPen(pen)
            series.setPointLabelsColor(QColor(palette["text_main"]))
        for bar, color in zip(self.status_chart.series()[0].barSets(),
                              ("chart_new", "chart_progress", "chart_packed", "chart_shipped")):
            bar.setColor(QColor(palette[color]))
            bar.setBorderColor(QColor(palette[color]))
            bar.setLabelColor(QColor(palette["text_main"]))
        for section, color in zip(self.capacity_chart.series()[0].slices(),
                                  ("accent", "warning", "success")):
            section.setColor(QColor(palette[color]))
            section.setBorderColor(QColor(palette["bg_card"]))
            section.setLabelColor(QColor(palette["text_main"]))

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
        title.setObjectName("title_label")
        
        filter_label = QLabel(self.translator.t("dashboard_trend_label", "Order inflow trend analysis:"))
        filter_label.setObjectName("muted_label")
        
        self.time_filter = QComboBox()
        self.time_filter.setItemDelegate(QStyledItemDelegate(self.time_filter))
        self.time_filter.addItems([
            self.translator.t("filter_7_days", "Last 7 days"), 
            self.translator.t("filter_month", "This month"), 
            self.translator.t("filter_year", "This year")
        ])
        self.time_filter.setObjectName("dashboard_period")
        
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
        
        chart.setPlotAreaBackgroundVisible(False)
        
        chart.legend().setFont(QFont("Segoe UI", 10))
        chart.legend().setAlignment(Qt.AlignTop)
        chart.setMargins(QMargins(10, 10, 10, 10))
        return chart

    def _create_chart_view(self, chart):
        view = QChartView(chart)
        view.setRenderHint(QPainter.Antialiasing) # Key for smooth lines
        view.setObjectName("chart_view")
        return view

    def setup_trend_chart(self):
        self.trend_chart = self._create_base_chart("")
        
        # 1. Zmiana na QSplineSeries (gładkie, nowoczesne krzywe) + pogrubienie
        series_prev = QSplineSeries()
        series_prev.setName(self.translator.t("trend_prev", "Previous period"))
        pen_prev = QPen() # Stonowany szary
        pen_prev.setWidth(3)
        series_prev.setPen(pen_prev)
        
        series_curr = QSplineSeries()
        series_curr.setName(self.translator.t("trend_curr", "Current period"))
        pen_curr = QPen() # Nowoczesny, jasny niebieski/cyan
        pen_curr.setWidth(4)
        series_curr.setPen(pen_curr)
        
        series_curr.setPointLabelsVisible(True)
        series_curr.setPointLabelsFormat("@yPoint")
        series_curr.setPointLabelsFont(QFont("Segoe UI", 11, QFont.Bold))
        series_curr.setPointLabelsClipping(False)
        
        self.trend_chart.addSeries(series_prev)
        self.trend_chart.addSeries(series_curr)
        
        # Osie
        axis_font = QFont("Segoe UI", 9)
        
        self.axis_x_trend = QBarCategoryAxis()
        self.axis_x_trend.setLabelsFont(axis_font)
        self.trend_chart.addAxis(self.axis_x_trend, Qt.AlignBottom)
        series_prev.attachAxis(self.axis_x_trend)
        series_curr.attachAxis(self.axis_x_trend)
        
        self.axis_y_trend = QValueAxis()
        self.axis_y_trend.setLabelsFont(axis_font)
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
        
        set_progress = QBarSet(self.translator.t("status_in_progress", "In Progress"))
        set_progress.append([0])
        
        set_packed = QBarSet(self.translator.t("status_packed", "Packed"))
        set_packed.append([0])
        
        set_shipped = QBarSet(self.translator.t("status_shipped", "Shipped"))
        set_shipped.append([0])
        
        series = QBarSeries()
        series.append(set_new)
        series.append(set_progress)
        series.append(set_packed)
        series.append(set_shipped)
        
        series.setLabelsVisible(True)
        series.setLabelsPosition(QAbstractBarSeries.LabelsOutsideEnd)
        
        self.status_chart.addSeries(series)
        
        axis_font = QFont("Segoe UI", 9)
        
        axis_x = QBarCategoryAxis()
        axis_x.append([""])
        self.status_chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)
        
        axis_y = QValueAxis()
        axis_y.setLabelsFont(axis_font)
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
        slice_free.setLabelVisible()
        slice_free.setLabelFont(lbl_font)
        
        lbl_racks = f"{self.translator.t('cap_racks', 'Taken on racks')} ({capacity['taken_on_racks']:.1f}%)"
        slice_racks = series_pie.append(lbl_racks, capacity['taken_on_racks'])
        slice_racks.setLabelVisible()
        slice_racks.setLabelFont(lbl_font)
        
        lbl_pick = f"{self.translator.t('cap_picking', 'In picking')} ({capacity['in_picking']:.1f}%)"
        slice_picking = series_pie.append(lbl_pick, capacity['in_picking'])
        slice_picking.setLabelVisible()
        slice_picking.setLabelFont(lbl_font)

        self.update_trend_chart("7_days")
        self.apply_chart_theme()

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