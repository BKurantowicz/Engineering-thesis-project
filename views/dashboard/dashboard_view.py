from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QFrame, QGridLayout
)
from PySide6.QtCharts import (
    QChart, QChartView, QLineSeries, QPieSeries, 
    QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis
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
        # Main vertical layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)

        # 1. Header (Title and filters)
        self.setup_header()

        # 2. Top chart (Trend line)
        self.setup_trend_chart()

        # 3. Bottom section (Pie and Bar charts)
        self.bottom_layout = QHBoxLayout()
        self.bottom_layout.setSpacing(20)
        
        self.setup_capacity_chart()
        self.setup_status_chart()
        
        self.main_layout.addLayout(self.bottom_layout)
        
        # Vertical proportions: Top chart takes 50% of the space, bottom charts 50%
        self.main_layout.setStretch(1, 1)
        self.main_layout.setStretch(2, 1)

    def setup_header(self):
        header_layout = QHBoxLayout()
        
        title = QLabel("Dashboard (WMS Analytics)")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setStyleSheet("color: white;")
        
        filter_label = QLabel("Order inflow trend analysis:")
        filter_label.setStyleSheet("color: #a0a0a0; font-size: 14px;")
        
        self.time_filter = QComboBox()
        self.time_filter.addItems(["Last 7 days", "This month", "This year"])
        self.time_filter.setStyleSheet("""
            QComboBox {
                background-color: #1e2130;
                color: white;
                border: 1px solid #3a3f58;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(filter_label)
        header_layout.addWidget(self.time_filter)
        
        self.main_layout.addLayout(header_layout)

    def _create_base_chart(self, title_text):
        """Helper function to create consistent charts for the dark theme"""
        chart = QChart()
        chart.setTitle(title_text)
        chart.setTitleBrush(QColor("white"))
        chart.setBackgroundBrush(QColor("#1e2130")) # Background color matching the UI
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
        
        # Temporary data series (to be replaced with SQL queries)
        series_prev = QLineSeries()
        series_prev.setName("Previous period")
        series_prev.setColor(QColor("#5a5a5a"))
        
        series_curr = QLineSeries()
        series_curr.setName("Current period")
        series_curr.setColor(QColor("#4a69bd"))
        
        # Add empty/sample points to draw the grid
        for i in range(7):
            series_prev.append(i, 0)
            series_curr.append(i, 0)
            
        self.trend_chart.addSeries(series_prev)
        self.trend_chart.addSeries(series_curr)
        
        self.trend_chart.createDefaultAxes()
        
        # Axis styling
        for axis in self.trend_chart.axes():
            axis.setLabelsColor(QColor("#a0a0a0"))
            axis.setGridLineColor(QColor("#3a3f58"))
            axis.setLinePenColor(QColor("#a0a0a0"))

        chart_view = self._create_chart_view(self.trend_chart)
        self.main_layout.addWidget(chart_view)

    def setup_capacity_chart(self):
        self.capacity_chart = self._create_base_chart("Warehouse Capacity")
        self.capacity_chart.legend().hide() # In the original, legends are directly on the pie slices
        
        series = QPieSeries()
        slice_free = series.append("Free space", 9.0)
        slice_free.setColor(QColor("#87CEFA"))
        slice_free.setLabelVisible()
        slice_free.setLabelColor(QColor("#a0a0a0"))
        
        slice_racks = series.append("Taken on racks", 89.4)
        slice_racks.setColor(QColor("#FF7F50"))
        slice_racks.setLabelVisible()
        slice_racks.setLabelColor(QColor("#a0a0a0"))
        
        slice_picking = series.append("In picking", 1.5)
        slice_picking.setColor(QColor("#98FB98"))
        slice_picking.setLabelVisible()
        slice_picking.setLabelColor(QColor("#a0a0a0"))

        self.capacity_chart.addSeries(series)
        
        chart_view = self._create_chart_view(self.capacity_chart)
        self.bottom_layout.addWidget(chart_view)

    def setup_status_chart(self):
        self.status_chart = self._create_base_chart("Current Order Fulfillment Status")
        
        set_new = QBarSet("New")
        set_new.append([0])
        set_new.setColor(QColor("#FF4500"))
        
        set_progress = QBarSet("In Progress")
        set_progress.append([56]) # Approximate value from the initial mockup
        set_progress.setColor(QColor("#1E90FF"))
        
        set_partial = QBarSet("Partially packed")
        set_partial.append([0])
        set_partial.setColor(QColor("#FFA500"))
        
        set_packed = QBarSet("Packed")
        set_packed.append([0])
        set_packed.setColor(QColor("#32CD32"))
        
        series = QBarSeries()
        series.append(set_new)
        series.append(set_progress)
        series.append(set_partial)
        series.append(set_packed)
        
        self.status_chart.addSeries(series)
        
        # Hidden X axis, as we only have one set of bars
        axis_x = QBarCategoryAxis()
        axis_x.append([""])
        self.status_chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)
        
        axis_y = QValueAxis()
        axis_y.setRange(0, 58)
        axis_y.setLabelsColor(QColor("#a0a0a0"))
        axis_y.setGridLineColor(QColor("#3a3f58"))
        self.status_chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)

        chart_view = self._create_chart_view(self.status_chart)
        self.bottom_layout.addWidget(chart_view)

    def load_real_data(self):
        """Fetches real statistics from the controller and draws them on the view"""
        if not self.controller:
            return

        # --- 1. Bar chart update (Order Statuses) ---
        status_counts = self.controller.get_order_status_counts()
        
        # Get the first data series from the bar chart
        series = self.status_chart.series()[0]
        
        # Replace artificial zeros with actual database values
        series.barSets()[0].replace(0, status_counts.get("New", 0))
        series.barSets()[1].replace(0, status_counts.get("In Progress", 0))
        series.barSets()[2].replace(0, status_counts.get("Partially packed", 0))
        series.barSets()[3].replace(0, status_counts.get("Packed", 0))
        
        # Dynamically scale the vertical Y axis to the highest bar
        max_val = max(status_counts.values()) if status_counts.values() else 10
        self.status_chart.axes(Qt.Vertical)[0].setRange(0, max_val + (max_val * 0.2))

        # --- 2. Pie chart update (Warehouse Capacity) ---
        capacity = self.controller.get_warehouse_capacity()
        series_pie = self.capacity_chart.series()[0]
        
        # Clear old (mock) data from the pie chart
        series_pie.clear()
        
        # Add new pie slices, translating their names via the i18n system
        lbl_free = f"{self.translator.t('cap_free')} ({capacity['free_space']:.1f}%)"
        slice_free = series_pie.append(lbl_free, capacity['free_space'])
        slice_free.setColor(QColor("#87CEFA"))
        slice_free.setLabelVisible()
        slice_free.setLabelColor(QColor("#a0a0a0"))
        
        lbl_racks = f"{self.translator.t('cap_racks')} ({capacity['taken_on_racks']:.1f}%)"
        slice_racks = series_pie.append(lbl_racks, capacity['taken_on_racks'])
        slice_racks.setColor(QColor("#FF7F50"))
        slice_racks.setLabelVisible()
        slice_racks.setLabelColor(QColor("#a0a0a0"))
        
        lbl_pick = f"{self.translator.t('cap_picking')} ({capacity['in_picking']:.1f}%)"
        slice_picking = series_pie.append(lbl_pick, capacity['in_picking'])
        slice_picking.setColor(QColor("#98FB98"))
        slice_picking.setLabelVisible()
        slice_picking.setLabelColor(QColor("#a0a0a0"))

        # --- 3. Trend line update (Order Inflow) ---
        trend_data = self.controller.get_order_trend()
        if trend_data:
            series_curr = self.trend_chart.series()[1] # Current period is the second series
            series_curr.clear()
            
            # Map the dates and counts to the line series
            for i, (date_str, count) in enumerate(trend_data.items()):
                series_curr.append(i, count)
                
            # Adjust X and Y axis ranges dynamically for the trend line
            self.trend_chart.axes(Qt.Horizontal)[0].setRange(0, max(1, len(trend_data) - 1))
            max_trend_val = max(trend_data.values()) if trend_data.values() else 10
            self.trend_chart.axes(Qt.Vertical)[0].setRange(0, max_trend_val + (max_trend_val * 0.2))