"""Date-axis regression at the QA window size and after resizing."""
import os
from datetime import date, timedelta
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout
from PySide6.QtGui import QFontMetricsF, QFontDatabase
from utils.translations import translator
from utils.theme_manager import ThemeManager
from views.dashboard.dashboard_view import DashboardView

ROOT = Path(__file__).resolve().parents[1]


class TrendFixture:
    def get_order_trend(self, period):
        count = {"7_days": 7, "this_month": 30, "this_year": 12}[period]
        dates = ([(date(2026, 10, 17) + timedelta(days=i)).isoformat() for i in range(count)]
                 if period != "this_year" else [f"2026-{i+1:02}" for i in range(count)])
        return {"dates": dates, "current": [i % 6 + 1 for i in range(count)],
                "previous": [i % 4 for i in range(count)]}


class DashboardDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # Windows offscreen Qt does not discover installed fonts automatically.
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf"):
            if (fonts / name).exists():
                QFontDatabase.addApplicationFont(str(fonts / name))

    def test_dates_remain_readable_without_dropping_values(self):
        for language in ("pl", "en"):
            for theme in ("light", "dark"):
                with self.subTest(language=language, theme=theme):
                    ThemeManager.apply_theme(self.app, theme, "medium")
                    window = QWidget()
                    layout = QHBoxLayout(window)
                    layout.setContentsMargins(0, 0, 0, 0)
                    layout.setSpacing(0)
                    sidebar = QWidget()
                    sidebar.setFixedWidth(250)
                    layout.addWidget(sidebar)
                    controller = TrendFixture()
                    dashboard = DashboardView(translator(language, str(ROOT / "utils")), controller)
                    layout.addWidget(dashboard)
                    window.resize(1280, 837)
                    window.show()
                    try:
                        for width in (1280, 1000, 1600, 1280):
                            window.resize(width, 837)
                            self.app.processEvents()
                            self.assertEqual(window.width(), width)
                            for period in ("this_month", "this_year", "7_days", "this_month"):
                                dashboard.time_filter.blockSignals(True)
                                dashboard.time_filter.setCurrentIndex({"7_days": 0, "this_month": 1, "this_year": 2}[period])
                                dashboard.time_filter.blockSignals(False)
                                dashboard.update_trend_chart(period)
                                for _ in range(3):
                                    self.app.processEvents()
                                expected = controller.get_order_trend(period)
                                for series, key in zip(dashboard.trend_chart.series(), ("previous", "current")):
                                    self.assertEqual([(p.x(), p.y()) for p in series.points()],
                                                     list(enumerate(expected[key])))
                                axis = dashboard.axis_x_trend
                                labels = axis.categoriesLabels()
                                formatted = [d if period == "this_year" else d[-5:] for d in expected["dates"]]
                                self.assertEqual(labels[0], formatted[0])
                                self.assertEqual(labels[-1], formatted[-1])
                                self.assertEqual(labels, sorted(labels, key=formatted.index))
                                metrics = QFontMetricsF(axis.labelsFont())
                                scale = dashboard.trend_chart.plotArea().width() / len(formatted)
                                for left, right in zip(labels, labels[1:]):
                                    distance = (axis.endValue(right) - axis.endValue(left)) * scale
                                    self.assertGreater(distance, max(metrics.horizontalAdvance(left), metrics.horizontalAdvance(right)) + 16)
                        evidence = os.environ.get("QA_DATE_EVIDENCE")
                        if evidence:
                            Path(evidence).mkdir(parents=True, exist_ok=True)
                            self.assertTrue(window.grab().save(str(Path(evidence) / f"dates-{language}-{theme}.png")))
                    finally:
                        window.close()
                        window.deleteLater()
                        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
