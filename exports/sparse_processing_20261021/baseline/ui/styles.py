"""Shared QSS for the shell and migrated pages; legacy widget styles stay local.

Keep state selectors here and visual values in ui.theme. Fragments retain the
existing cascade; views import the completed strings without assembling QSS.
"""
from .theme import qss


_SHARED = {
    "transparent_panel": qss("""
    background: transparent;
    border: none;
"""),
    "dialog_surface": qss("""
    background-color: ${surface};
    color: ${text_dialog};
"""),
    "dialog_stepper": qss("""
    width: 24px;
    border: none;
    background-color: ${control_stepper};
"""),
    "dialog_button": qss("""
    min-width: 80px;
    min-height: 34px;
    border: 1px solid ${border_control};
    border-radius: ${radius_control};
    background-color: ${control};
    color: ${text};
    padding: 0 ${space_button};
"""),
    "primary_action": qss("""
    background-color: ${accent};
    border-color: ${accent};
    color: ${on_accent};
"""),
    "page_title": qss("""
  color: ${text_heading};
  font-size: 20px;
  font-weight: 700;
"""),
    "page_subtitle": qss("""
  color: ${text_muted};
  font-size: 13px;
"""),
    "summary_label": qss("""
  color: ${text_summary_label};
  font-size: 13px;
"""),
    "page_surface": qss("""
    background: ${background};
    color: ${text};
"""),
    "card": qss("""
    background: ${surface};
    border: 1px solid ${border_card};
    border-radius: ${radius_card};
"""),
    "secondary_button": qss("""
    min-height: 32px;
    border: 1px solid ${border_control};
    border-radius: ${radius_control};
    background: ${control};
    color: ${text_button};
    padding: 0 ${space_button};
"""),
    "primary_button": qss("""
    background: ${accent};
    border-color: ${accent};
    color: ${on_accent};
    font-weight: 650;
"""),
}


def _style(source: str) -> str:
    return qss(source, **_SHARED)


SHELL_QSS = _style("""
QWidget#ApplicationShell {
    background: ${background};
    color: ${text};
    font-size: 13px;
}
QFrame#ApplicationSidebar {
    background: ${sidebar};
    border-right: 1px solid ${border_sidebar};
}
QLabel#BrandLogo {
    ${transparent_panel}
}
QPushButton#ModuleButton {
    min-height: 54px;
    padding: 0;
    border: none;
    border-left: 3px solid transparent;
    border-radius: ${radius_control};
    background: transparent;
    color: ${text_secondary};
}
QPushButton#ModuleButton:hover {
    background: ${surface_hover};
    color: ${text_heading_hover};
}
QPushButton#ModuleButton:checked {
    background: ${surface_selected};
    color: ${accent_hover};
    border-left-color: ${accent};
    font-weight: 650;
}
QLabel#NavGlyph {
    min-width: 25px;
    max-width: 25px;
    color: ${text_secondary};
    font-size: 20px;
    background: transparent;
}
QLabel#NavLabel {
    color: ${text_secondary};
    font-size: 15px;
    background: transparent;
}
QLabel#NavGlyph[active="true"],
QLabel#NavLabel[active="true"] {
    color: ${accent_hover};
    font-weight: 650;
}
QComboBox QAbstractItemView {
    background-color: ${control};
    color: ${text};
    selection-background-color: ${selection_popup};
    selection-color: ${on_accent};
}
QFrame#ShellContent {
    background: ${background};
    border: none;
}
""")


APP_DIALOG_QSS = _style("""
QDialog,
QMessageBox,
QInputDialog {
    ${dialog_surface}
}
QDialog QLabel,
QMessageBox QLabel,
QInputDialog QLabel {
    color: ${text_body};
    background: transparent;
}
QDialog QLineEdit,
QDialog QComboBox,
QDialog QSpinBox,
QDialog QDoubleSpinBox {
    min-height: 34px;
    border: 1px solid ${border_control};
    border-radius: ${radius_control};
    background-color: ${control};
    color: ${text};
    padding: 0 ${space_input};
    selection-background-color: ${accent};
}
QDialog QComboBox::drop-down,
QDialog QSpinBox::up-button,
QDialog QSpinBox::down-button,
QDialog QDoubleSpinBox::up-button,
QDialog QDoubleSpinBox::down-button {
    ${dialog_stepper}
}
QDialog QAbstractItemView {
    background-color: ${control};
    color: ${text};
    border: 1px solid ${border_control};
    selection-background-color: ${selection_popup};
}
QDialog QPushButton,
QMessageBox QPushButton {
    ${dialog_button}
}
QDialog QPushButton:hover,
QMessageBox QPushButton:hover {
    background-color: ${control_hover};
}
QDialog QPushButton:default,
QMessageBox QPushButton:default {
    ${primary_action}
}
""")


SETUP_QSS = _style("""
QWidget#SetupViewRoot {
  background-color: ${background};
  color: ${text_dialog};
}
QFrame#TopSubjectBar,
QFrame#ModeBar {
  background-color: ${surface};
  border: none;
  border-radius: ${radius_action};
}
QFrame#ConfigWorkArea {
    ${transparent_panel}
}
QFrame#ConfigSummaryCard {
  background-color: ${surface};
  border: none;
  border-radius: ${radius_card};
}
QLabel#PageTitle {
    ${page_title}
}
QLabel#PageSubtitle {
    ${page_subtitle}
}
QLabel#SummaryTitle {
  color: ${text_summary_heading};
  font-size: 18px;
  font-weight: 700;
}
QLabel#SummaryState {
  color: ${accent_text};
  font-size: 14px;
  font-weight: 600;
}
QLabel#SummaryText {
  color: ${text_summary};
  font-size: 14px;
}
QLabel#SummaryHint {
  color: ${text_hint};
  font-size: 13px;
}
QLabel#SummarySectionLabel {
  color: ${text_body};
  font-size: 14px;
  font-weight: 700;
  margin-top: ${space_xxs};
}
QFrame#SummaryFilterRow {
  background: transparent;
  border: none;
  border-bottom: 1px solid ${border_divider};
}
QLabel#SummaryRowLabel {
    ${summary_label}
}
QLabel#FilterState {
  color: ${text_summary};
  font-size: 13px;
  font-weight: 600;
}
QLabel#FilterDetails {
  color: ${text_filter_detail};
  font-size: 13px;
  padding: 0 0 5px ${space_control};
}
QFrame#DeviceStatusCard {
    ${transparent_panel}
}
QLabel#DeviceState {
  font-size: 14px;
  font-weight: 700;
}
QLabel#DeviceMeta {
    ${summary_label}
}
QLineEdit, QComboBox {
  min-height: 32px;
  border-radius: ${radius_control};
  border: 1px solid ${border_control};
  background-color: ${control};
  color: ${text};
  padding: 0 ${space_control};
}
QPushButton {
  min-height: 32px;
  border-radius: ${radius_control};
  border: 1px solid ${border_control};
  background-color: ${control};
  color: ${text_button};
  padding: 0 ${space_lg};
}
QPushButton:hover {
  background-color: ${control_hover};
}
QPushButton#SubjectPrimaryButton,
QPushButton#PrimaryStartButton,
QPushButton#SegmentButton:checked {
    ${primary_action}
}
QPushButton#PrimaryStartButton {
  min-height: 46px;
  font-size: 14px;
  font-weight: 700;
  border-radius: ${radius_action};
}
QPushButton#PrimaryStartButton:disabled {
  background-color: ${control_disabled};
  border-color: ${border_disabled};
  color: ${text_disabled};
}
QPushButton#SegmentButton {
  min-width: 112px;
  border: none;
  background-color: transparent;
  font-weight: 600;
}
QPushButton#SegmentButton:hover {
  background-color: ${hover_subtle};
}
QMenu {
  background-color: ${menu};
  color: ${text};
  border: 1px solid ${border_menu};
  padding: 6px;
}
QMenu::item {
  padding: ${space_sm} ${space_page_bottom};
  border-radius: ${radius_compact};
}
QMenu::item:selected {
  background-color: ${selection_menu};
}
QScrollArea#ManualConfigScroll,
QScrollArea#ManualConfigScroll QWidget#qt_scrollarea_viewport {
  background: ${surface};
  border: none;
}
QScrollArea#ManualConfigScroll QScrollBar:vertical {
  width: 10px;
  margin: 0;
  border: none;
  background-color: ${scroll_track};
}
QScrollArea#ManualConfigScroll QScrollBar::handle:vertical {
  min-height: 32px;
  border-radius: ${radius_compact};
  background-color: ${scroll_handle};
}
QScrollArea#ManualConfigScroll QScrollBar::handle:vertical:hover {
  background-color: ${scroll_handle_hover};
}
QScrollArea#ManualConfigScroll QScrollBar::add-line:vertical,
QScrollArea#ManualConfigScroll QScrollBar::sub-line:vertical {
  height: 0;
  border: none;
  background: transparent;
}
QScrollArea#ManualConfigScroll QScrollBar::add-page:vertical,
QScrollArea#ManualConfigScroll QScrollBar::sub-page:vertical {
  background: transparent;
}
""")


NEW_SUBJECT_DIALOG_QSS = _style("""
QDialog#NewSubjectDialog {
    ${dialog_surface}
}
QDialog#NewSubjectDialog QLabel {
  color: ${text_body};
  font-size: 13px;
}
QDialog#NewSubjectDialog QLineEdit,
QDialog#NewSubjectDialog QComboBox,
QDialog#NewSubjectDialog QSpinBox {
  min-height: 34px;
  border-radius: ${radius_control};
  border: 1px solid ${border_control};
  background-color: ${control};
  color: ${text};
  padding: 0 ${space_control};
  selection-background-color: ${accent};
}
QDialog#NewSubjectDialog QComboBox::drop-down,
QDialog#NewSubjectDialog QSpinBox::up-button,
QDialog#NewSubjectDialog QSpinBox::down-button {
    ${dialog_stepper}
}
QDialog#NewSubjectDialog QPushButton {
    ${dialog_button}
}
QDialog#NewSubjectDialog QPushButton:hover {
  background-color: ${control_hover};
}
QDialog#NewSubjectDialog QPushButton:default {
    ${primary_action}
}
""")


ATHLETES_QSS = _style("""
QWidget#AthletesViewRoot {
    ${page_surface}
}
QLabel#PageTitle {
    ${page_title}
}
QLabel#PageSubtitle {
    ${page_subtitle}
}
QFrame#AthleteToolbar,
QFrame#AthleteTableCard {
    ${card}
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 32px;
    border: 1px solid ${border_control};
    border-radius: ${radius_control};
    background: ${control};
    color: ${text};
    padding: 0 ${space_input};
}
QPushButton {
    ${secondary_button}
}
QPushButton:hover {
    background: ${control_hover};
}
QPushButton#PrimaryButton {
    ${primary_button}
}
QTableWidget {
    background: ${surface};
    alternate-background-color: ${surface_hover};
    color: ${text_body};
    border: none;
    gridline-color: ${table_grid};
    selection-background-color: ${selection_table};
    selection-color: ${on_accent};
}
QHeaderView::section {
    background: ${surface_selected};
    color: ${table_header_text};
    border: none;
    border-bottom: 1px solid ${table_header_border};
    padding: ${space_sm};
}
""")


HISTORY_QSS = _style("""
QWidget#HistoryViewRoot {
    background: ${background};
    color: ${text};
    font-size: 14px;
}
QLabel#HistoryTitle {
    color: ${text_heading};
    font-size: 22px;
    font-weight: 700;
}
QLabel#HistoryContext {
    color: ${text_secondary};
    font-size: 13px;
}
QLabel#DetailTitle {
    color: ${text_detail_heading};
    font-size: 18px;
    font-weight: 700;
}
QFrame#HistoryDetailCard {
    ${card}
}
QLabel#HistoryDetailText {
    color: ${text_body};
    font-size: 14px;
    background: transparent;
}
QComboBox#HistoryFilter {
    min-width: 150px;
    min-height: 34px;
    padding: 0 ${space_control};
    border: 1px solid ${border_control};
    border-radius: ${radius_control};
    background: ${control};
    color: ${text};
}
QTableWidget {
    background: ${surface};
    alternate-background-color: ${surface_hover};
    color: ${text_body};
    border: 1px solid ${border_card};
    border-radius: ${radius_card};
    gridline-color: ${table_grid};
    selection-background-color: ${selection_table};
    selection-color: ${on_accent};
    font-size: 14px;
}
QTableWidget::item {
    padding: ${space_sm} ${space_control};
}
QTableWidget::item:selected {
    background: ${selection_table_row};
    color: ${on_accent};
}
QHeaderView::section {
    background: ${surface_selected};
    color: ${table_header_text};
    border: none;
    border-bottom: 1px solid ${table_header_border};
    padding: ${space_sm};
    font-size: 13px;
    font-weight: 600;
}
QPushButton {
    min-height: 34px;
    border: 1px solid ${border_control};
    border-radius: ${radius_control};
    background: ${control};
    color: ${text_button};
    padding: 0 ${space_button};
}
QPushButton:hover {
    background: ${control_hover};
}
QPushButton:disabled {
    color: ${text_history_disabled};
    background: ${history_disabled};
}
QPushButton#PrimaryHistoryAction {
    ${primary_button}
}
""")


SETTINGS_QSS = _style("""
QWidget#SettingsViewRoot {
    ${page_surface}
}
QLabel#PageTitle {
    ${page_title}
}
QLabel#PageSubtitle {
    ${page_subtitle}
}
QLabel#ModeLabel {
    color: ${status_text};
    background: ${status_surface};
    border: 1px solid ${status_border};
    border-radius: ${radius_action};
    padding: 7px 11px;
    font-size: 13px;
}
QFrame#SettingsCard {
    ${card}
}
QLabel#CardTitle {
    color: ${text_card_heading};
    font-size: 14px;
    font-weight: 700;
}
QLabel#FieldLabel {
    ${page_subtitle}
}
QLabel#FieldValue {
    color: ${text_field};
    font-size: 13px;
}
QDoubleSpinBox, QSpinBox {
    color: ${text};
    background: ${control};
    border: 1px solid ${border_control};
    border-radius: ${radius_compact};
    min-height: 30px;
    padding: 0 ${space_sm};
}
QPushButton {
    ${secondary_button}
}
QPushButton:hover {
    background: ${control_hover};
}
""")
