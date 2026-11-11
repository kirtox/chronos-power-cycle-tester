"""Main application window: Event Tracking / Device Baseline / Power Cycle Test tabs."""
import logging
import os

from PyQt5 import QtCore, QtWidgets

from .. import autostart, device_baseline, power_cycle, providers, storage
from ..config import AppConfig, load_config, save_config
from ..event_watcher import LEVEL_NAMES, EventWatcher
from . import tray

logger = logging.getLogger(__name__)


class Signals(QtCore.QObject):
    event_matched = QtCore.pyqtSignal(dict)
    power_cycle_progress = QtCore.pyqtSignal(dict)
    power_cycle_finished = QtCore.pyqtSignal()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chronos — Power Cycle Test & Recovery Verifier")
        self.resize(900, 600)

        self.config: AppConfig = load_config()
        self.signals = Signals()
        self.signals.event_matched.connect(self._on_event_matched)
        self.signals.power_cycle_progress.connect(self._on_power_cycle_progress)
        self.signals.power_cycle_finished.connect(self._on_power_cycle_finished)

        self.watcher: EventWatcher | None = None
        self.power_cycle_runner = power_cycle.PowerCycleTestRunner(
            on_progress=lambda d: self.signals.power_cycle_progress.emit(d),
            on_finished=lambda: self.signals.power_cycle_finished.emit(),
        )

        self.tray = tray.build_tray_icon(self)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_event_tab(), "Event Tracking")
        tabs.addTab(self._build_device_tab(), "Device Baseline")
        tabs.addTab(self._build_power_cycle_tab(), "Power Cycle Test")
        self.setCentralWidget(tabs)

    # ---------------------------------------------------------------- Event tab
    def _build_event_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)

        filter_box = QtWidgets.QGroupBox("Filter")
        filter_layout = QtWidgets.QVBoxLayout(filter_box)

        filter_layout.addWidget(QtWidgets.QLabel("Level"))
        self.level_list = QtWidgets.QListWidget()
        self.level_list.setMaximumHeight(120)
        for level, name in LEVEL_NAMES.items():
            item = QtWidgets.QListWidgetItem(name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setData(QtCore.Qt.UserRole, level)
            item.setCheckState(
                QtCore.Qt.Checked if level in self.config.filter.levels else QtCore.Qt.Unchecked
            )
            self.level_list.addItem(item)
        filter_layout.addWidget(self.level_list)

        source_header = QtWidgets.QHBoxLayout()
        source_header.addWidget(QtWidgets.QLabel("Source (Provider)"))
        refresh_btn = QtWidgets.QPushButton("重新整理")
        refresh_btn.clicked.connect(self._refresh_providers)
        source_header.addWidget(refresh_btn)
        filter_layout.addLayout(source_header)
        self.source_list = QtWidgets.QListWidget()
        filter_layout.addWidget(self.source_list)
        self._populate_providers(self.config.filter.providers)

        filter_layout.addWidget(QtWidgets.QLabel("Event ID (逗號分隔)"))
        self.event_id_edit = QtWidgets.QLineEdit(
            ",".join(str(e) for e in self.config.filter.event_ids)
        )
        filter_layout.addWidget(self.event_id_edit)

        btn_layout = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("開始追蹤")
        self.start_btn.clicked.connect(self._start_tracking)
        self.stop_btn = QtWidgets.QPushButton("停止追蹤")
        self.stop_btn.clicked.connect(self._stop_tracking)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        filter_layout.addLayout(btn_layout)

        self.autostart_checkbox = QtWidgets.QCheckBox("開機自動啟動")
        self.autostart_checkbox.setChecked(self.config.autostart_enabled)
        self.autostart_checkbox.toggled.connect(self._toggle_autostart)
        filter_layout.addWidget(self.autostart_checkbox)

        layout.addWidget(filter_box, stretch=1)

        result_box = QtWidgets.QGroupBox("符合條件的事件")
        result_layout = QtWidgets.QVBoxLayout(result_box)
        self.event_table = QtWidgets.QTableWidget(0, 6)
        self.event_table.setHorizontalHeaderLabels(
            ["Time", "Level", "Provider", "EventID", "Computer", "Message"]
        )
        self.event_table.horizontalHeader().setStretchLastSection(True)
        self.event_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        result_layout.addWidget(self.event_table)
        export_btn = QtWidgets.QPushButton("匯出 CSV")
        export_btn.clicked.connect(self._export_events_csv)
        result_layout.addWidget(export_btn)
        layout.addWidget(result_box, stretch=2)

        self._refresh_event_table()
        return widget

    def _populate_providers(self, selected: list) -> None:
        self.source_list.clear()
        for name in selected:
            item = QtWidgets.QListWidgetItem(name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.source_list.addItem(item)

    def _refresh_providers(self) -> None:
        try:
            names = providers.detect_providers()
        except Exception:
            logger.exception("Failed to detect providers")
            QtWidgets.QMessageBox.warning(self, "錯誤", "偵測 Provider 清單失敗，請查看 log")
            return
        checked = {
            self.source_list.item(i).text()
            for i in range(self.source_list.count())
            if self.source_list.item(i).checkState() == QtCore.Qt.Checked
        }
        self.source_list.clear()
        for name in names:
            item = QtWidgets.QListWidgetItem(name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if name in checked else QtCore.Qt.Unchecked)
            self.source_list.addItem(item)

    def _collect_filter_config(self):
        from ..config import FilterConfig
        levels = [
            self.level_list.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.level_list.count())
            if self.level_list.item(i).checkState() == QtCore.Qt.Checked
        ]
        sources = [
            self.source_list.item(i).text()
            for i in range(self.source_list.count())
            if self.source_list.item(i).checkState() == QtCore.Qt.Checked
        ]
        event_ids = []
        for part in self.event_id_edit.text().split(","):
            part = part.strip()
            if part.isdigit():
                event_ids.append(int(part))
        return FilterConfig(levels=levels, providers=sources, event_ids=event_ids)

    def _start_tracking(self) -> None:
        filter_config = self._collect_filter_config()
        self.config.filter = filter_config
        save_config(self.config)

        self.watcher = EventWatcher(filter_config, on_match=self._handle_match)
        try:
            self.watcher.start()
        except Exception:
            logger.exception("Failed to start EventWatcher")
            QtWidgets.QMessageBox.critical(self, "錯誤", "啟動追蹤失敗，請查看 log")
            return
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _stop_tracking(self) -> None:
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _handle_match(self, data: dict) -> None:
        """Runs on the Event Log service's callback thread."""
        storage.insert_event(
            data["record_id"], data["time_created"], data["provider"],
            data["level"], data["event_id"], data["computer"],
            data["message"], data["xml"],
        )
        self.signals.event_matched.emit(data)

    def _on_event_matched(self, data: dict) -> None:
        self._refresh_event_table()
        level_name = LEVEL_NAMES.get(data["level"], str(data["level"]))
        tray.notify(
            self.tray,
            f"[{level_name}] {data['provider']} (ID {data['event_id']})",
            data["message"][:200] or "(no message)",
        )

    def _refresh_event_table(self) -> None:
        rows = storage.query_events(limit=200)
        self.event_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                row["time_created"], LEVEL_NAMES.get(row["level"], row["level"]),
                row["provider"], row["event_id"], row["computer"], row["message"],
            ]
            for c, value in enumerate(values):
                self.event_table.setItem(r, c, QtWidgets.QTableWidgetItem(str(value)))

    def _export_events_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "匯出 CSV", "events.csv", "CSV (*.csv)")
        if path:
            storage.export_events_csv(path)
            QtWidgets.QMessageBox.information(self, "完成", f"已匯出至 {path}")

    def _toggle_autostart(self, checked: bool) -> None:
        try:
            if checked:
                autostart.register()
            else:
                autostart.unregister()
        except Exception:
            logger.exception("Failed to toggle autostart")
            QtWidgets.QMessageBox.warning(self, "錯誤", "設定開機自動啟動失敗，請查看 log")
            return
        self.config.autostart_enabled = checked
        save_config(self.config)

    # ------------------------------------------------------------- Device tab
    def _build_device_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        header = QtWidgets.QHBoxLayout()
        refresh_btn = QtWidgets.QPushButton("重新整理裝置清單")
        refresh_btn.clicked.connect(self._refresh_devices)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        self.device_list = QtWidgets.QListWidget()
        layout.addWidget(self.device_list)
        self._refresh_devices()

        action_layout = QtWidgets.QHBoxLayout()
        baseline_btn = QtWidgets.QPushButton("拍攝 Baseline")
        baseline_btn.clicked.connect(self._take_device_baseline)
        compare_btn = QtWidgets.QPushButton("立即比對")
        compare_btn.clicked.connect(self._compare_devices_now)
        action_layout.addWidget(baseline_btn)
        action_layout.addWidget(compare_btn)
        layout.addLayout(action_layout)

        self.device_result = QtWidgets.QTextEdit()
        self.device_result.setReadOnly(True)
        layout.addWidget(self.device_result)
        return widget

    def _refresh_devices(self) -> None:
        tracked = set(self.config.device_baseline.tracked_device_ids)
        self.device_list.clear()
        try:
            devices = device_baseline.list_devices()
        except Exception:
            logger.exception("Failed to list devices")
            QtWidgets.QMessageBox.warning(self, "錯誤", "讀取 Device Manager 清單失敗")
            return
        for d in devices:
            item = QtWidgets.QListWidgetItem(f"[{d['pnp_class']}] {d['name']} ({d['status']})")
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setData(QtCore.Qt.UserRole, d["device_id"])
            item.setCheckState(
                QtCore.Qt.Checked if d["device_id"] in tracked else QtCore.Qt.Unchecked
            )
            self.device_list.addItem(item)

    def _selected_device_ids(self) -> list:
        return [
            self.device_list.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.device_list.count())
            if self.device_list.item(i).checkState() == QtCore.Qt.Checked
        ]

    def _take_device_baseline(self) -> None:
        device_ids = self._selected_device_ids()
        self.config.device_baseline.tracked_device_ids = device_ids
        save_config(self.config)
        snapshot = device_baseline.take_snapshot(device_ids)
        storage.insert_device_snapshot("baseline", device_baseline.new_batch_id(), snapshot)
        self.device_result.setPlainText(f"已拍攝 {len(snapshot)} 個裝置的 Baseline。")

    def _compare_devices_now(self) -> None:
        baseline_rows = storage.get_latest_snapshot("baseline")
        if not baseline_rows:
            QtWidgets.QMessageBox.information(self, "尚無 Baseline", "請先拍攝 Baseline")
            return
        baseline = [dict(row) for row in baseline_rows]
        device_ids = [d["device_id"] for d in baseline]
        current = device_baseline.take_snapshot(device_ids)
        diffs = device_baseline.compare(baseline, current)
        if not diffs:
            self.device_result.setPlainText("比對結果：所有追蹤裝置狀態皆與 Baseline 一致。")
        else:
            lines = [f"- {d['name']}: {d['change']}" for d in diffs]
            self.device_result.setPlainText("發現差異：\n" + "\n".join(lines))
            tray.notify(self.tray, "Device Baseline 比對發現差異", "\n".join(lines)[:200],
                        QtWidgets.QSystemTrayIcon.Warning)

    # --------------------------------------------------------- Power cycle tab
    def _build_power_cycle_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        supported = power_cycle.detect_supported_states()
        type_box = QtWidgets.QGroupBox("循環類型")
        type_layout = QtWidgets.QHBoxLayout(type_box)
        self.reboot_cb = QtWidgets.QCheckBox("Reboot")
        self.reboot_cb.setChecked("reboot" in self.config.power_cycle_test.types)
        type_layout.addWidget(self.reboot_cb)

        self.sleep_cb = QtWidgets.QCheckBox("Sleep (Modern Standby)")
        self.sleep_cb.setEnabled(supported["modern_standby"] or supported["s3"])
        self.sleep_cb.setChecked("sleep" in self.config.power_cycle_test.types)
        type_layout.addWidget(self.sleep_cb)

        self.hibernate_cb = QtWidgets.QCheckBox("Hibernate")
        self.hibernate_cb.setEnabled(supported["hibernate"])
        self.hibernate_cb.setChecked("hibernate" in self.config.power_cycle_test.types)
        type_layout.addWidget(self.hibernate_cb)

        if not supported["hibernate"]:
            enable_hib_btn = QtWidgets.QPushButton("啟用 Hibernate (需要 UAC)")
            enable_hib_btn.clicked.connect(self._enable_hibernate)
            type_layout.addWidget(enable_hib_btn)
        layout.addWidget(type_box)

        params_box = QtWidgets.QGroupBox("測試參數")
        form = QtWidgets.QFormLayout(params_box)
        self.cycles_spin = QtWidgets.QSpinBox()
        self.cycles_spin.setRange(1, 1000)
        self.cycles_spin.setValue(self.config.power_cycle_test.cycles_per_type)
        form.addRow("總輪數 N（每種類型）", self.cycles_spin)

        self.wake_delay_spin = QtWidgets.QSpinBox()
        self.wake_delay_spin.setRange(1, 120)
        self.wake_delay_spin.setValue(self.config.power_cycle_test.wake_delay_minutes)
        form.addRow("喚醒延遲（分鐘）", self.wake_delay_spin)

        self.settle_spin = QtWidgets.QSpinBox()
        self.settle_spin.setRange(5, 600)
        self.settle_spin.setValue(self.config.power_cycle_test.settle_seconds)
        form.addRow("恢復後穩定等待（秒）", self.settle_spin)

        self.stop_on_failure_cb = QtWidgets.QCheckBox("失敗即停止")
        self.stop_on_failure_cb.setChecked(self.config.power_cycle_test.stop_on_failure)
        form.addRow(self.stop_on_failure_cb)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem("每種類型各跑 N 次", "per_type")
        self.mode_combo.addItem("混合大迴圈跑 N 輪", "mixed")
        idx = 0 if self.config.power_cycle_test.mode == "per_type" else 1
        self.mode_combo.setCurrentIndex(idx)
        form.addRow("執行模式", self.mode_combo)
        layout.addWidget(params_box)

        btn_layout = QtWidgets.QHBoxLayout()
        self.pc_start_btn = QtWidgets.QPushButton("開始 Power Cycle Test")
        self.pc_start_btn.clicked.connect(self._start_power_cycle_test)
        self.pc_stop_btn = QtWidgets.QPushButton("停止")
        self.pc_stop_btn.clicked.connect(self._stop_power_cycle_test)
        self.pc_stop_btn.setEnabled(False)
        btn_layout.addWidget(self.pc_start_btn)
        btn_layout.addWidget(self.pc_stop_btn)
        layout.addLayout(btn_layout)

        self.pc_table = QtWidgets.QTableWidget(0, 5)
        self.pc_table.setHorizontalHeaderLabels(["Type", "Cycle", "Start", "Result", "Reason"])
        self.pc_table.horizontalHeader().setStretchLastSection(True)
        self.pc_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.pc_table)

        export_btn = QtWidgets.QPushButton("匯出測試報告 (CSV)")
        export_btn.clicked.connect(self._export_power_cycle_csv)
        layout.addWidget(export_btn)

        self._refresh_power_cycle_table()
        return widget

    def _enable_hibernate(self) -> None:
        power_cycle.enable_hibernate()
        QtWidgets.QMessageBox.information(
            self, "請重新整理", "已嘗試啟用 Hibernate（請於 UAC 確認），請重啟工具以更新選項狀態。"
        )

    def _start_power_cycle_test(self) -> None:
        types = []
        if self.reboot_cb.isChecked():
            types.append("reboot")
        if self.sleep_cb.isChecked():
            types.append("sleep")
        if self.hibernate_cb.isChecked():
            types.append("hibernate")
        if not types:
            QtWidgets.QMessageBox.warning(self, "請選擇類型", "請至少勾選一種循環類型")
            return

        device_ids = self.config.device_baseline.tracked_device_ids
        if not device_ids:
            reply = QtWidgets.QMessageBox.question(
                self, "沒有追蹤裝置",
                "尚未在 Device Baseline 分頁選擇要追蹤的裝置，仍要繼續嗎？（將只用 event log 驗證）",
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return

        from ..config import PowerCycleTestConfig
        pc_config = PowerCycleTestConfig(
            types=types,
            cycles_per_type=self.cycles_spin.value(),
            wake_delay_minutes=self.wake_delay_spin.value(),
            settle_seconds=self.settle_spin.value(),
            stop_on_failure=self.stop_on_failure_cb.isChecked(),
            mode=self.mode_combo.currentData(),
        )
        self.config.power_cycle_test = pc_config
        save_config(self.config)

        self.pc_start_btn.setEnabled(False)
        self.pc_stop_btn.setEnabled(True)
        self.power_cycle_runner.start_new_test(pc_config, device_ids)

    def _stop_power_cycle_test(self) -> None:
        self.power_cycle_runner.stop()

    def resume_power_cycle_if_pending(self) -> None:
        self.power_cycle_runner.resume_after_restart()

    def _on_power_cycle_progress(self, data: dict) -> None:
        self._refresh_power_cycle_table()
        if data["result"] in ("pass", "fail"):
            tray.notify(
                self.tray,
                f"Power Cycle Test [{data['cycle_type']} #{data['cycle_index']}] {data['result'].upper()}",
                data["reason"][:200],
                QtWidgets.QSystemTrayIcon.Information if data["result"] == "pass"
                else QtWidgets.QSystemTrayIcon.Critical,
            )

    def _on_power_cycle_finished(self) -> None:
        self.pc_start_btn.setEnabled(True)
        self.pc_stop_btn.setEnabled(False)
        tray.notify(self.tray, "Power Cycle Test 結束", "所有排定的循環已完成或已停止。")

    def _refresh_power_cycle_table(self) -> None:
        rows = storage.query_power_cycle_results(limit=200)
        self.pc_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [row["cycle_type"], row["cycle_index"], row["start_time"],
                      row["result"], row["reason"]]
            for c, value in enumerate(values):
                self.pc_table.setItem(r, c, QtWidgets.QTableWidgetItem(str(value)))

    def _export_power_cycle_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "匯出測試報告", "power_cycle_report.csv", "CSV (*.csv)"
        )
        if path:
            storage.export_power_cycle_csv(path)
            QtWidgets.QMessageBox.information(self, "完成", f"已匯出至 {path}")

    # ------------------------------------------------------------------- misc
    def closeEvent(self, event) -> None:
        """Minimize to tray instead of quitting."""
        event.ignore()
        self.hide()
        tray.notify(self.tray, "Chronos", "已縮小到系統匣，測試/追蹤仍在背景執行中。")
