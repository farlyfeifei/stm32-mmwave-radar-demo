"""PyQt5 real-time 2D radar visualization upper-computer for the STM32 mmWave demo.

Drives either the deterministic :func:`generate_scenario` simulator or a CSV
replay (:func:`read_measurements_csv`) with a 100 ms QTimer, runs each frame
through :class:`RadarTracker`, and renders a PPI-style display with QPainter.

The viewer only depends on the public API of :mod:`host.radar_demo` and does not
modify it.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, Iterator, List, Optional, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Support both "python host/radar_viewer.py" and "python -m host.radar_viewer"
if __package__ in (None, ""):
    # Running as a script: add project root so "host" package is importable
    _project_root = str(Path(__file__).resolve().parent.parent)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from host.radar_demo import (
        Measurement,
        RadarTracker,
        Track,
        generate_scenario,
        read_measurements_csv,
    )
else:
    from host.radar_demo import (
        Measurement,
        RadarTracker,
        Track,
        generate_scenario,
        read_measurements_csv,
    )


# --------------------------------------------------------------------------- #
# Look & feel
# --------------------------------------------------------------------------- #
COLOR_BG = QColor("#0a0f14")
COLOR_PANEL = QColor("#0d141b")
COLOR_GRID = QColor("#4fd1ff")
COLOR_CROSS = QColor("#4fd1ff")
COLOR_RING_LABEL = QColor("#4fd1ff")
COLOR_STABLE = QColor("#50fa7b")
COLOR_UNSTABLE = QColor("#f1fa8c")
COLOR_ARROW = QColor("#ff79c6")
COLOR_TRAIL = QColor("#50fa7b")
COLOR_TEXT = QColor("#cfd8dc")
COLOR_TEXT_DIM = QColor("#6b7785")
COLOR_DIM = QColor("#6b7785")
COLOR_ACCENT_2 = QColor("#ffb84f")
COLOR_OK = QColor("#50fa7b")

MAX_RANGE_M = 30.0          # outer distance ring
RING_STEP_M = 10.0          # one ring every 10 m
TRAIL_LENGTH = 10           # keep the last 10 positions per track
TIMER_INTERVAL_MS = 100     # one frame every 100 ms
ARROW_TIME_S = 4.0          # velocity vector = ARROW_TIME_S seconds of travel


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def polar_to_xy(range_m: float, angle_deg: float) -> Tuple[float, float]:
    """Convert polar (range, azimuth) to cartesian meters.

    0 deg points "up" (forward), positive angles to the right, y grows upward.
    """
    a = math.radians(angle_deg)
    return range_m * math.sin(a), range_m * math.cos(a)


def lerp_color(color: QColor, alpha: int) -> QColor:
    """Return a copy of ``color`` with the given alpha channel (0-255)."""
    out = QColor(color)
    out.setAlpha(alpha)
    return out


# --------------------------------------------------------------------------- #
# Canvas
# --------------------------------------------------------------------------- #
class RadarCanvas(QWidget):
    """Self-drawn PPI radar display."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 640)
        self.setStyleSheet(f"background-color: {COLOR_BG.name()};")

        self._tracks: List[Track] = []
        self._trails: Dict[int, Deque[Tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=TRAIL_LENGTH)
        )
        self._frame_seq: Optional[int] = None
        self._sweep_deg: float = -90.0  # sweep starts pointing up (forward)

    # ----- public API ------------------------------------------------------- #
    def update_frame(self, seq: int, tracks: List[Track]) -> None:
        self._frame_seq = seq
        self._tracks = tracks

        # Append a fresh trail point only for tracks actually updated this frame.
        for track in tracks:
            if track.missed == 0:
                self._trails[track.track_id].append(
                    polar_to_xy(track.range_m, track.angle_deg)
                )

        # Drop trails for tracks that have been retired by the tracker.
        active_ids = {t.track_id for t in tracks}
        for stale_id in [tid for tid in self._trails if tid not in active_ids]:
            del self._trails[stale_id]

        # Advance the PPI sweep for a subtle scan animation.
        self._sweep_deg = (self._sweep_deg + 9.0) % 360.0

        self.update()

    # ----- painting --------------------------------------------------------- #
    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), COLOR_BG)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        margin = 48.0  # room for azimuth labels
        radius_px = max(40.0, min(w, h) / 2.0 - margin)
        scale = radius_px / MAX_RANGE_M  # pixels per meter

        self._draw_sweep(painter, cx, cy, radius_px)
        self._draw_grid(painter, cx, cy, radius_px, scale)
        self._draw_trails(painter, cx, cy, scale)
        self._draw_targets(painter, cx, cy, scale)
        self._draw_legend(painter, w, h)

    # -- grid: rings, crosshair, azimuth ticks ------------------------------- #
    def _draw_grid(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        radius_px: float,
        scale: float,
    ) -> None:
        pen = QPen(COLOR_GRID, 1)
        pen.setStyle(Qt.DashLine)
        pen.setWidthF(1.0)

        # Concentric distance rings.
        painter.setPen(QPen(lerp_color(COLOR_GRID, 120), 1.0, Qt.DashLine))
        for r_m in range(int(RING_STEP_M), int(MAX_RANGE_M) + 1, int(RING_STEP_M)):
            r_px = r_m * scale
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), r_px, r_px)
            painter.setPen(lerp_color(COLOR_RING_LABEL, 200))
            painter.drawText(
                QRectF(cx + 4, cy - r_px - 12, 60, 14),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"{r_m}m",
            )
            painter.setPen(QPen(lerp_color(COLOR_GRID, 120), 1.0, Qt.DashLine))

        # Crosshair (full diameter lines through the center).
        painter.setPen(QPen(lerp_color(COLOR_CROSS, 90), 1.0))
        painter.drawLine(QPointF(cx - radius_px, cy), QPointF(cx + radius_px, cy))
        painter.drawLine(QPointF(cx, cy - radius_px), QPointF(cx, cy + radius_px))

        # Diagonal guides for a tech-feel compass.
        painter.setPen(QPen(lerp_color(COLOR_CROSS, 45), 1.0, Qt.DotLine))
        for d in (45, 135, 225, 315):
            a = math.radians(d)
            painter.drawLine(
                QPointF(cx, cy),
                QPointF(cx + radius_px * math.cos(a), cy + radius_px * math.sin(a)),
            )

        # Azimuth ticks + labels every 30 deg around the outer ring.
        painter.setPen(QPen(lerp_color(COLOR_GRID, 160), 1.2))
        tick_outer = radius_px
        tick_inner = radius_px - 8.0
        label_font = QFont("Consolas", 8)
        painter.setFont(label_font)
        for deg in range(0, 360, 30):
            a = math.radians(deg - 90)  # 0 deg at top
            x1 = cx + tick_outer * math.cos(a)
            y1 = cy + tick_outer * math.sin(a)
            x2 = cx + tick_inner * math.cos(a)
            y2 = cy + tick_inner * math.sin(a)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            # Label: show signed bearing relative to forward (0 at top).
            bearing = deg if deg <= 180 else deg - 360
            lx = cx + (radius_px + 16) * math.cos(a)
            ly = cy + (radius_px + 16) * math.sin(a)
            painter.setPen(lerp_color(COLOR_GRID, 170))
            painter.drawText(
                QRectF(lx - 18, ly - 8, 36, 14),
                Qt.AlignCenter,
                f"{bearing:+d}",
            )
            painter.setPen(QPen(lerp_color(COLOR_GRID, 160), 1.2))

        # Center marker (radar position).
        painter.setBrush(lerp_color(COLOR_GRID, 220))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), 3.0, 3.0)

    # -- rotating sweep ------------------------------------------------------ #
    def _draw_sweep(
        self, painter: QPainter, cx: float, cy: float, radius_px: float
    ) -> None:
        span_deg = 24.0
        steps = 12
        polygon = QPolygonF()
        polygon.append(QPointF(cx, cy))
        for i in range(steps + 1):
            frac = i / steps
            deg = self._sweep_deg - span_deg * frac
            a = math.radians(deg - 90)
            polygon.append(
                QPointF(cx + radius_px * math.cos(a), cy + radius_px * math.sin(a))
            )
        painter.setBrush(lerp_color(COLOR_GRID, 28))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(polygon)

        # Leading edge line.
        a = math.radians(self._sweep_deg - 90)
        painter.setPen(QPen(lerp_color(COLOR_GRID, 110), 1.2))
        painter.drawLine(
            QPointF(cx, cy),
            QPointF(cx + radius_px * math.cos(a), cy + radius_px * math.sin(a)),
        )

    # -- trails -------------------------------------------------------------- #
    def _draw_trails(
        self, painter: QPainter, cx: float, cy: float, scale: float
    ) -> None:
        for track_id, points in self._trails.items():
            if len(points) < 2:
                continue
            n = len(points)
            for i in range(1, n):
                alpha = int(30 + 180 * (i / n))
                x0, y0 = points[i - 1]
                x1, y1 = points[i]
                painter.setPen(
                    QPen(lerp_color(COLOR_TRAIL, alpha), 2.0, Qt.SolidLine, Qt.RoundCap)
                )
                painter.drawLine(
                    QPointF(cx + x0 * scale, cy - y0 * scale),
                    QPointF(cx + x1 * scale, cy - y1 * scale),
                )

    # -- targets + labels + velocity arrows ---------------------------------- #
    def _draw_targets(
        self, painter: QPainter, cx: float, cy: float, scale: float
    ) -> None:
        label_font = QFont("Consolas", 8)
        for track in self._tracks:
            x_m, y_m = polar_to_xy(track.range_m, track.angle_deg)
            sx = cx + x_m * scale
            sy = cy - y_m * scale

            color = COLOR_STABLE if track.stable else COLOR_UNSTABLE

            # Radius scaled by SNR (confidence), clamped to a readable band.
            snr = max(0.0, track.confidence)
            r_px = max(4.0, min(12.0, 4.0 + (snr - 8.0) * 0.4))

            # Glow halo.
            painter.setBrush(lerp_color(color, 60))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(sx, sy), r_px * 2.0, r_px * 2.0)

            # Solid core.
            painter.setBrush(color)
            painter.setPen(QPen(lerp_color(COLOR_BG, 255), 1.0))
            painter.drawEllipse(QPointF(sx, sy), r_px, r_px)

            self._draw_velocity_arrow(painter, track, sx, sy, scale)
            self._draw_target_label(painter, track, sx, sy, r_px, color, label_font)

    def _draw_velocity_arrow(
        self,
        painter: QPainter,
        track: Track,
        sx: float,
        sy: float,
        scale: float,
    ) -> None:
        if abs(track.velocity_mps) < 1e-3:
            return

        # Radial unit vector (screen coords, y flipped).
        a = math.radians(track.angle_deg)
        ux = math.sin(a)
        uy = -math.cos(a)

        # Arrow length in pixels: ARROW_TIME_S seconds of radial travel, capped.
        length_m = track.velocity_mps * ARROW_TIME_S
        length_m = max(-MAX_RANGE_M / 3.0, min(MAX_RANGE_M / 3.0, length_m))
        ex = sx + ux * length_m * scale
        ey = sy + uy * length_m * scale

        painter.setPen(QPen(COLOR_ARROW, 1.6, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(sx, sy), QPointF(ex, ey))

        # Arrowhead.
        angle = math.atan2(ey - sy, ex - sx)
        head_len = 7.0
        head_ang = math.radians(26.0)
        hx1 = ex - head_len * math.cos(angle - head_ang)
        hy1 = ey - head_len * math.sin(angle - head_ang)
        hx2 = ex - head_len * math.cos(angle + head_ang)
        hy2 = ey - head_len * math.sin(angle + head_ang)
        head = QPolygonF([QPointF(ex, ey), QPointF(hx1, hy1), QPointF(hx2, hy2)])
        painter.setBrush(COLOR_ARROW)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(head)

    def _draw_target_label(
        self,
        painter: QPainter,
        track: Track,
        sx: float,
        sy: float,
        r_px: float,
        color: QColor,
        font: QFont,
    ) -> None:
        text = f"#{track.track_id} {track.range_m:.1f}m {track.velocity_mps:+.1f}m/s"
        painter.setFont(font)
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(text)
        th = metrics.height()
        tx = sx + r_px + 4
        ty = sy - r_px - 4

        # Dark backdrop for legibility on the busy grid.
        painter.setBrush(lerp_color(COLOR_BG, 200))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(tx - 2, ty - th + 2, tw + 6, th + 2), 3, 3)

        # Shadow + colored text.
        painter.setPen(lerp_color(COLOR_BG, 255))
        painter.drawText(QPointF(tx + 1, ty + 1), text)
        painter.setPen(color)
        painter.drawText(QPointF(tx, ty), text)

    # -- legend -------------------------------------------------------------- #
    def _draw_legend(self, painter: QPainter, w: float, h: float) -> None:
        painter.setFont(QFont("Consolas", 8))
        items = [
            (COLOR_STABLE, "稳定航迹"),
            (COLOR_UNSTABLE, "不稳定"),
            (COLOR_ARROW, "速度矢量"),
        ]
        x = 12.0
        y = h - 16.0
        for color, label in items:
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(x + 4, y), 4.0, 4.0)
            painter.setPen(COLOR_TEXT_DIM)
            painter.drawText(QPointF(x + 14, y + 4), label)
            x += 14 + painter.fontMetrics().horizontalAdvance(label) + 18


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class RadarViewer(QMainWindow):
    """Top-level window: canvas on the left, info panel on the right."""

    def __init__(
        self,
        frames: Iterator[Tuple[int, List[Measurement]]],
        total_frames: Optional[int] = None,
        source_label: str = "",
        interactive: bool = False,
    ) -> None:
        super().__init__()
        self.setWindowTitle("低空之眸 — 单雷达目标检测可视化")
        self.resize(1180, 820 if interactive else 740)

        self._frames = frames
        self._total_frames = total_frames
        self._source_label = source_label
        self._tracker = RadarTracker()
        self._frame_count = 0
        self._status = "等待数据…"
        self._interactive = interactive

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(8)

        self.canvas = RadarCanvas()
        main_row.addWidget(self.canvas, 1)

        self.info_label = QLabel()
        self.info_label.setMinimumWidth(340)
        self.info_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.info_label.setTextFormat(Qt.RichText)
        self.info_label.setStyleSheet(
            f"background-color: {COLOR_PANEL.name()};"
            f"color: {COLOR_TEXT.name()};"
            "padding: 10px;"
            "border-radius: 4px;"
        )
        main_row.addWidget(self.info_label, 0)

        outer.addLayout(main_row, 1)

        # ----- interactive panel (bottom) -----
        if interactive:
            outer.addWidget(self._build_interactive_panel())

        self.setCentralWidget(central)
        self._render_info()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(TIMER_INTERVAL_MS)

    # ----- interactive panel ------------------------------------------------ #
    def _build_interactive_panel(self) -> QWidget:
        from host.scenario_parser import EXAMPLES

        panel = QFrame()
        panel.setStyleSheet(
            f"background-color: {COLOR_PANEL.name()};"
            f"color: {COLOR_TEXT.name()};"
            "border-radius: 6px;"
            "padding: 4px;"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        # Title row
        title = QLabel("✦ 交互式场景生成 — 用中文描述飞行状态,雷达实时响应")
        title.setStyleSheet(f"color: {COLOR_ACCENT_2.name()}; font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        # Input row
        input_row = QHBoxLayout()
        self._ai_input = QLineEdit()
        self._ai_input.setPlaceholderText("例: 两个目标从远处飞来,一个从左一个从右,强杂波")
        self._ai_input.setStyleSheet(
            f"background-color: {COLOR_BG.name()};"
            f"color: {COLOR_TEXT.name()};"
            f"border: 1px solid {COLOR_GRID.name()};"
            "border-radius: 4px; padding: 6px 10px; font-size: 13px;"
        )
        self._ai_input.returnPressed.connect(self._on_interactive_submit)
        input_row.addWidget(self._ai_input, 1)

        btn = QPushButton("生成场景")
        btn.setStyleSheet(
            f"background-color: {COLOR_ACCENT_2.name()};"
            "color: #2a1a00; border: none; border-radius: 4px;"
            "padding: 6px 16px; font-size: 13px; font-weight: bold;"
        )
        btn.clicked.connect(self._on_interactive_submit)
        input_row.addWidget(btn, 0)
        layout.addLayout(input_row)

        # Example chips
        chip_row = QHBoxLayout()
        chip_label = QLabel("示例:")
        chip_label.setStyleSheet(f"color: {COLOR_DIM.name()}; font-size: 11px;")
        chip_row.addWidget(chip_label, 0)
        self._example_buttons = []
        for ex in EXAMPLES:
            chip = QPushButton(ex)
            chip.setStyleSheet(
                f"background-color: rgba(79,209,255,0.08);"
                f"color: {COLOR_DIM.name()};"
                f"border: 1px solid {COLOR_GRID.name()};"
                "border-radius: 10px; padding: 2px 8px; font-size: 11px;"
            )
            chip.clicked.connect(lambda checked, text=ex: self._load_example(text))
            self._example_buttons.append(chip)
            chip_row.addWidget(chip, 0)
        chip_row.addStretch()
        layout.addLayout(chip_row)

        # Parse report
        self._ai_report = QLabel("")
        self._ai_report.setStyleSheet(
            f"color: {COLOR_OK.name()};"
            f"background-color: rgba(0,0,0,0.3);"
            "border-radius: 4px; padding: 4px 8px; font-size: 11px;"
            "font-family: Consolas, monospace;"
        )
        self._ai_report.setTextFormat(Qt.RichText)
        layout.addWidget(self._ai_report)

        return panel

    def _load_example(self, text: str) -> None:
        """Fill the input with an example and immediately run it."""
        self._ai_input.setText(text)
        self._on_interactive_submit()

    def _on_interactive_submit(self) -> None:
        """Parse the text, build a new scenario, restart simulation."""
        from host.scenario_parser import parse_flight_description, explain
        from host.radar_demo import generate_from_config

        text = self._ai_input.text().strip()
        if not text:
            return

        cfg = parse_flight_description(text)
        report = explain(cfg)
        self._ai_report.setText(report.replace("\n", "<br>"))

        # Stop current timer, reset state
        self._timer.stop()
        self._tracker = RadarTracker()
        self._frame_count = 0
        self.canvas._trails.clear()

        # New frame generator from parsed config
        self._frames = generate_from_config(cfg)
        self._total_frames = cfg.frame_count
        self._source_label = f"交互: {text[:30]}"
        self._status = "场景已加载"

        self._timer.start(TIMER_INTERVAL_MS)

    # ----- timer callback --------------------------------------------------- #
    def _tick(self) -> None:
        try:
            seq, measurements = next(self._frames)
        except StopIteration:
            self._timer.stop()
            self._status = "回放结束"
            self._render_info()
            return

        self._tracker.update(measurements)
        tracks = list(self._tracker.tracks)
        self._frame_count += 1
        self._status = "运行中"

        self.canvas.update_frame(seq, tracks)
        self._render_info(seq, tracks)

    # ----- info panel ------------------------------------------------------- #
    def _render_info(
        self, seq: Optional[int] = None, tracks: Optional[List[Track]] = None
    ) -> None:
        tracks = tracks or []
        stable_count = sum(1 for t in tracks if t.stable)

        total_txt = str(self._total_frames) if self._total_frames is not None else "?"
        seq_txt = f"{seq:03d}" if seq is not None else "---"

        rows_html = []
        if tracks:
            for t in sorted(tracks, key=lambda x: x.track_id):
                row_color = COLOR_STABLE.name() if t.stable else COLOR_UNSTABLE.name()
                status_txt = "稳定" if t.stable else f"miss{t.missed}"
                rows_html.append(
                    f"<tr style='color:{row_color};'>"
                    f"<td align='right'>#{t.track_id}</td>"
                    f"<td align='right'>{t.range_m:6.2f}</td>"
                    f"<td align='right'>{t.velocity_mps:+6.2f}</td>"
                    f"<td align='right'>{t.angle_deg:+6.1f}</td>"
                    f"<td align='right'>{t.confidence:5.1f}</td>"
                    f"<td align='right'>{t.age:3d}</td>"
                    f"<td align='center'>{status_txt}</td>"
                    f"</tr>"
                )
        else:
            rows_html.append(
                "<tr><td colspan='7' align='center' style='color:#6b7785;'>"
                "暂无活跃航迹</td></tr>"
            )

        html = f"""
        <div style='font-family: Consolas, "Microsoft YaHei", monospace; font-size: 12px;'>
          <div style='font-size: 15px; color: {COLOR_GRID.name()}; font-weight: bold;'>
            低空之眸 · 雷达监控
          </div>
          <div style='color: {COLOR_TEXT_DIM.name()}; font-size: 11px; margin-bottom: 8px;'>
            数据源: {self._source_label or "-"}
          </div>
          <div>帧号: <b style='color:{COLOR_GRID.name()}'>{seq_txt}</b>
               <span style='color:{COLOR_TEXT_DIM.name()};'> / {total_txt}</span></div>
          <div>已处理帧数: {self._frame_count}</div>
          <div>活跃航迹: {len(tracks)}</div>
          <div>稳定目标:
               <b style='color:{COLOR_STABLE.name()}'>{stable_count}</b></div>
          <hr style='border:0; border-top:1px solid #1f2933; margin:8px 0;'>
          <table cellspacing='2' cellpadding='2' style='font-size:11px;'>
            <tr style='color:{COLOR_GRID.name()};'>
              <th align='right'>ID</th>
              <th align='right'>距m</th>
              <th align='right'>速m/s</th>
              <th align='right'>角°</th>
              <th align='right'>SNR</th>
              <th align='right'>age</th>
              <th align='center'>状态</th>
            </tr>
            {''.join(rows_html)}
          </table>
          <hr style='border:0; border-top:1px solid #1f2933; margin:8px 0;'>
          <div style='color:{COLOR_TEXT_DIM.name()}; font-size:10px;'>
            状态: {self._status} · 每 {TIMER_INTERVAL_MS}ms 一帧
          </div>
        </div>
        """
        self.info_label.setText(html)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PyQt5 real-time 2D radar visualization upper-computer"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--simulate",
        action="store_true",
        help="generate deterministic radar measurements via generate_scenario",
    )
    mode.add_argument(
        "--scenario",
        type=Path,
        help="generate measurements from a JSON scenario file (see scenarios/)",
    )
    mode.add_argument(
        "--replay",
        type=Path,
        help="replay a measurement CSV (produced by radar_demo.py --csv)",
    )
    mode.add_argument(
        "--interactive",
        action="store_true",
        help="interactive mode: type Chinese flight descriptions to generate scenarios",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=80,
        help="number of simulated frames (only used with --simulate)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    interactive = False

    if args.interactive:
        interactive = True
        from host.scenario_parser import parse_flight_description
        from host.radar_demo import generate_from_config
        # Start with a default scenario; user will type new ones in the UI
        cfg = parse_flight_description("单目标匀速接近,中等杂波")
        frames: Iterator[Tuple[int, List[Measurement]]] = generate_from_config(cfg)
        total = cfg.frame_count
        source = "交互模式 (输入描述后自动生成)"
    elif args.simulate:
        frames = generate_scenario(args.frames)
        total = args.frames
        source = f"simulate ({args.frames} 帧)"
    elif args.scenario:
        from host.radar_demo import ScenarioConfig, generate_scenario_from_config
        cfg = ScenarioConfig.from_json(args.scenario)
        frames = generate_scenario_from_config(args.scenario)
        total = cfg.frame_count
        source = f"scenario: {cfg.name}"
    else:
        frames = read_measurements_csv(args.replay)
        total = None
        source = f"replay {args.replay.name}"

    app = QApplication(sys.argv)
    viewer = RadarViewer(frames, total_frames=total, source_label=source, interactive=interactive)
    viewer.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
