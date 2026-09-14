"""Rule editor component implementing Adw.ExpanderRow with clean two-line condition and action rows."""

from typing import Any, Callable, Dict, List, Optional
import uuid

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

FIELD_OPTIONS = [
    ("name", "Name"),
    ("extension", "Extension"),
    ("size_bytes", "Size (bytes)"),
    ("date_modified", "Modified Date (seconds ago)"),
    ("date_created", "Created Date (seconds ago)"),
    ("exif_date", "EXIF Date (seconds ago or ISO)"),
]

OPERATOR_OPTIONS = [
    ("is", "is"),
    ("is_not", "is not"),
    ("contains", "contains"),
    ("does_not_contain", "does not contain"),
    ("starts_with", "starts with"),
    ("ends_with", "ends with"),
    ("matches_regex", "matches regex"),
    ("greater_than", "greater than"),
    ("less_than", "less than"),
]

ACTION_TYPE_OPTIONS = [
    ("move", "Move File"),
    ("copy", "Copy File"),
    ("rename", "Rename File"),
    ("trash", "Move to Trash"),
]

STRATEGY_OPTIONS = [
    ("rename_counter", "Counter on Conflict"),
    ("skip", "Skip File"),
    ("overwrite", "Overwrite Existing"),
]

MODE_OPTIONS = [
    ("all", "Match ALL"),
    ("any", "Match ANY"),
    ("none", "Match NONE"),
]


class ConditionRow(Gtk.ListBoxRow):
    """Two-line layout condition row."""

    def __init__(self, data: Optional[Dict[str, Any]] = None, on_delete: Optional[Callable[[], None]] = None):
        super().__init__()
        self.set_activatable(False)
        self.set_selectable(False)
        self.on_delete = on_delete

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(8)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        self.set_child(vbox)

        # Line 1: Field, Operator, Delete Button
        line1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vbox.append(line1)

        field_names = [label for _, label in FIELD_OPTIONS]
        self.field_dropdown = Gtk.DropDown.new_from_strings(field_names)
        self.field_dropdown.connect("notify::selected", self._on_field_changed)
        line1.append(self.field_dropdown)

        op_names = [label for _, label in OPERATOR_OPTIONS]
        self.op_dropdown = Gtk.DropDown.new_from_strings(op_names)
        line1.append(self.op_dropdown)

        delete_btn = Gtk.Button(icon_name="user-trash-symbolic")
        delete_btn.add_css_class("destructive-action")
        delete_btn.set_tooltip_text("Delete condition")
        delete_btn.set_halign(Gtk.Align.END)
        delete_btn.set_hexpand(True)
        delete_btn.connect("clicked", self._on_delete_clicked)
        line1.append(delete_btn)

        # Line 2: Value Entry & Case sensitivity toggle
        line2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vbox.append(line2)

        self.value_entry = Gtk.Entry(placeholder_text="Match value or pattern...")
        self.value_entry.set_hexpand(True)
        line2.append(self.value_entry)

        self.case_toggle = Gtk.ToggleButton(label="Aa")
        self.case_toggle.set_tooltip_text("Case sensitive matching")
        line2.append(self.case_toggle)

        # Populate from data if provided
        if data:
            f = data.get("field", "name")
            for idx, (code, _) in enumerate(FIELD_OPTIONS):
                if code == f:
                    self.field_dropdown.set_selected(idx)
                    break

            op = data.get("operator", "is")
            for idx, (code, _) in enumerate(OPERATOR_OPTIONS):
                if code == op:
                    self.op_dropdown.set_selected(idx)
                    break

            self.value_entry.set_text(str(data.get("value", "")))
            self.case_toggle.set_active(not bool(data.get("case_insensitive", False)))

        self._update_case_toggle_visibility()

    def _on_field_changed(self, dropdown, _pspec):
        self._update_case_toggle_visibility()

    def _update_case_toggle_visibility(self):
        sel = self.field_dropdown.get_selected()
        field_code = FIELD_OPTIONS[sel][0]
        # Only meaningful for name and extension
        self.case_toggle.set_visible(field_code in ("name", "extension"))

    def _on_delete_clicked(self, _btn):
        if self.on_delete:
            self.on_delete()

    def get_data(self) -> Dict[str, Any]:
        sel_field = FIELD_OPTIONS[self.field_dropdown.get_selected()][0]
        sel_op = OPERATOR_OPTIONS[self.op_dropdown.get_selected()][0]
        val_str = self.value_entry.get_text()

        # Type conversion for numeric fields
        val: Any = val_str
        if sel_field == "size_bytes":
            try:
                val = int(val_str)
            except ValueError:
                val = 0
        elif sel_field in ("date_modified", "date_created"):
            try:
                val = float(val_str)
            except ValueError:
                val = 0.0

        res: Dict[str, Any] = {
            "field": sel_field,
            "operator": sel_op,
            "value": val,
        }
        if sel_field in ("name", "extension"):
            res["case_insensitive"] = not self.case_toggle.get_active()
        return res


class ActionRow(Gtk.ListBoxRow):
    """Two-line layout action row."""

    def __init__(self, data: Optional[Dict[str, Any]] = None, on_delete: Optional[Callable[[], None]] = None):
        super().__init__()
        self.set_activatable(False)
        self.set_selectable(False)
        self.on_delete = on_delete

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(8)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        self.set_child(vbox)

        # Line 1: Action Type, Conflict Strategy, Delete Button
        line1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vbox.append(line1)

        type_names = [label for _, label in ACTION_TYPE_OPTIONS]
        self.type_dropdown = Gtk.DropDown.new_from_strings(type_names)
        self.type_dropdown.connect("notify::selected", self._on_type_changed)
        line1.append(self.type_dropdown)

        strategy_names = [label for _, label in STRATEGY_OPTIONS]
        self.strat_dropdown = Gtk.DropDown.new_from_strings(strategy_names)
        line1.append(self.strat_dropdown)

        delete_btn = Gtk.Button(icon_name="user-trash-symbolic")
        delete_btn.add_css_class("destructive-action")
        delete_btn.set_tooltip_text("Delete action")
        delete_btn.set_halign(Gtk.Align.END)
        delete_btn.set_hexpand(True)
        delete_btn.connect("clicked", self._on_delete_clicked)
        line1.append(delete_btn)

        # Line 2: Destination or Format pattern
        line2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vbox.append(line2)

        self.param_entry = Gtk.Entry(placeholder_text="Target directory or rename pattern...")
        self.param_entry.set_hexpand(True)
        line2.append(self.param_entry)

        if data:
            t = data.get("type", "move")
            for idx, (code, _) in enumerate(ACTION_TYPE_OPTIONS):
                if code == t:
                    self.type_dropdown.set_selected(idx)
                    break

            strat = data.get("conflict_strategy", "rename_counter")
            for idx, (code, _) in enumerate(STRATEGY_OPTIONS):
                if code == strat:
                    self.strat_dropdown.set_selected(idx)
                    break

            if t in ("move", "copy"):
                self.param_entry.set_text(data.get("destination", ""))
            elif t == "rename":
                self.param_entry.set_text(data.get("pattern", ""))

        self._update_visibility()

    def _on_type_changed(self, dropdown, _pspec):
        self._update_visibility()

    def _update_visibility(self):
        sel_type = ACTION_TYPE_OPTIONS[self.type_dropdown.get_selected()][0]
        is_trash = sel_type == "trash"
        self.strat_dropdown.set_visible(not is_trash)
        self.param_entry.set_visible(not is_trash)
        if sel_type in ("move", "copy"):
            self.param_entry.set_placeholder_text("Target destination directory...")
        elif sel_type == "rename":
            self.param_entry.set_placeholder_text("Rename pattern (e.g. {date}_{name}.{ext})...")

    def _on_delete_clicked(self, _btn):
        if self.on_delete:
            self.on_delete()

    def get_data(self) -> Dict[str, Any]:
        sel_type = ACTION_TYPE_OPTIONS[self.type_dropdown.get_selected()][0]
        sel_strat = STRATEGY_OPTIONS[self.strat_dropdown.get_selected()][0]
        param = self.param_entry.get_text()

        res: Dict[str, Any] = {"type": sel_type}
        if sel_type in ("move", "copy"):
            res["destination"] = param
            res["conflict_strategy"] = sel_strat
        elif sel_type == "rename":
            res["pattern"] = param
            res["conflict_strategy"] = sel_strat
        return res


class RuleExpanderRow(Adw.ExpanderRow):
    """Expandable rule editor row implementing GNOME HIG and Adw.ExpanderRow."""

    def __init__(
        self,
        rule_data: Optional[Dict[str, Any]] = None,
        target_path: Optional[str] = None,
        on_save_needed: Optional[Callable[[], None]] = None,
        on_delete_rule: Optional[Callable[["RuleExpanderRow"], None]] = None,
    ):
        super().__init__()
        self.on_save_needed = on_save_needed
        self.on_delete_rule = on_delete_rule
        self.target_path = target_path or ""

        self.rule_id = (
            rule_data.get("metadata", {}).get("id")
            if rule_data
            else str(uuid.uuid4())
        )
        self.rule_enabled = (
            rule_data.get("metadata", {}).get("enabled", True)
            if rule_data
            else True
        )

        rule_name = (
            rule_data.get("metadata", {}).get("name", "New Rule")
            if rule_data
            else "New Rule"
        )
        self.set_title(rule_name)

        # Main settings rows
        self.name_row = Adw.EntryRow(title="Rule Name")
        self.name_row.set_text(rule_name)
        self.name_row.connect("changed", self._on_name_changed)
        self.add_row(self.name_row)

        self.priority_row = Adw.SpinRow.new_with_range(0, 1000, 1)
        self.priority_row.set_title("Evaluation Priority")
        priority = rule_data.get("metadata", {}).get("priority", 0) if rule_data else 0
        self.priority_row.set_value(priority)
        self.add_row(self.priority_row)

        self.stop_match_row = Adw.SwitchRow(title="Stop On Match")
        stop_match = rule_data.get("metadata", {}).get("stop_on_match", False) if rule_data else False
        self.stop_match_row.set_active(stop_match)
        self.add_row(self.stop_match_row)

        self.recursive_row = Adw.SwitchRow(title="Recursive Subdirectory Scanning")
        recursive = rule_data.get("triggers", {}).get("recursive", False) if rule_data else False
        self.recursive_row.set_active(recursive)
        self.add_row(self.recursive_row)

        # Conditions PreferencesGroup
        cond_group = Adw.PreferencesGroup(title="Conditions")
        mode_names = [label for _, label in MODE_OPTIONS]
        self.mode_dropdown = Gtk.DropDown.new_from_strings(mode_names)
        curr_mode = rule_data.get("conditions", {}).get("mode", "all") if rule_data else "all"
        for idx, (code, _) in enumerate(MODE_OPTIONS):
            if code == curr_mode:
                self.mode_dropdown.set_selected(idx)
                break
        cond_group.set_header_suffix(self.mode_dropdown)

        self.condition_list = Gtk.ListBox()
        self.condition_list.add_css_class("boxed-list")
        cond_group.add(self.condition_list)

        add_cond_btn = Gtk.Button(label="+ Add Condition")
        add_cond_btn.add_css_class("flat")
        add_cond_btn.set_halign(Gtk.Align.START)
        add_cond_btn.connect("clicked", self._add_condition_row)
        cond_group.add(add_cond_btn)

        self.add_row(cond_group)

        # Actions PreferencesGroup
        act_group = Adw.PreferencesGroup(title="Actions")
        self.action_list = Gtk.ListBox()
        self.action_list.add_css_class("boxed-list")
        act_group.add(self.action_list)

        add_act_btn = Gtk.Button(label="+ Add Action")
        add_act_btn.add_css_class("flat")
        add_act_btn.set_halign(Gtk.Align.START)
        add_act_btn.connect("clicked", self._add_action_row)
        act_group.add(add_act_btn)

        self.add_row(act_group)

        # Rule controls: Save & Delete Rule buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_margin_top(12)
        btn_box.set_margin_bottom(12)
        btn_box.set_margin_start(12)
        btn_box.set_margin_end(12)

        save_btn = Gtk.Button(label="Save Rule")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save_clicked)
        btn_box.append(save_btn)

        del_rule_btn = Gtk.Button(label="Delete Rule")
        del_rule_btn.add_css_class("destructive-action")
        del_rule_btn.set_hexpand(True)
        del_rule_btn.set_halign(Gtk.Align.END)
        del_rule_btn.connect("clicked", self._on_delete_rule_clicked)
        btn_box.append(del_rule_btn)

        self.add_row(btn_box)

        # Populate initial conditions and actions
        if rule_data:
            for cond in rule_data.get("conditions", {}).get("rules", []):
                self._create_condition_widget(cond)
            for act in rule_data.get("actions", []):
                self._create_action_widget(act)
        else:
            self._create_condition_widget({"field": "name", "operator": "contains", "value": ""})
            self._create_action_widget({"type": "move", "destination": "", "conflict_strategy": "rename_counter"})

    def _on_name_changed(self, entry):
        text = entry.get_text().strip()
        self.set_title(text if text else "Untitled Rule")

    def _add_condition_row(self, _btn):
        self._create_condition_widget({"field": "name", "operator": "is", "value": ""})

    def _create_condition_widget(self, data: Dict[str, Any]):
        def on_del():
            self.condition_list.remove(row)
        row = ConditionRow(data=data, on_delete=on_del)
        self.condition_list.append(row)

    def _add_action_row(self, _btn):
        self._create_action_widget({"type": "move", "destination": "", "conflict_strategy": "rename_counter"})

    def _create_action_widget(self, data: Dict[str, Any]):
        def on_del():
            self.action_list.remove(row)
        row = ActionRow(data=data, on_delete=on_del)
        self.action_list.append(row)

    def _on_save_clicked(self, _btn):
        if self.on_save_needed:
            self.on_save_needed()

    def _on_delete_rule_clicked(self, _btn):
        if self.on_delete_rule:
            self.on_delete_rule(self)

    def to_rule_dict(self) -> Dict[str, Any]:
        """Convert widget state to JSON Schema compliant rule dictionary."""
        conditions_data = []
        child = self.condition_list.get_first_child()
        while child:
            if isinstance(child, ConditionRow):
                conditions_data.append(child.get_data())
            child = child.get_next_sibling()

        actions_data = []
        child = self.action_list.get_first_child()
        while child:
            if isinstance(child, ActionRow):
                actions_data.append(child.get_data())
            child = child.get_next_sibling()

        sel_mode = MODE_OPTIONS[self.mode_dropdown.get_selected()][0]

        trigger_paths = [self.target_path] if self.target_path else ["~/Downloads"]

        return {
            "metadata": {
                "id": self.rule_id,
                "name": self.name_row.get_text() or "Untitled Rule",
                "enabled": self.rule_enabled,
                "priority": int(self.priority_row.get_value()),
                "stop_on_match": self.stop_match_row.get_active(),
            },
            "triggers": {
                "paths": trigger_paths,
                "recursive": self.recursive_row.get_active(),
            },
            "conditions": {
                "mode": sel_mode,
                "rules": conditions_data if conditions_data else [{"field": "name", "operator": "contains", "value": ""}],
            },
            "actions": actions_data if actions_data else [{"type": "move", "destination": "~/Documents", "conflict_strategy": "rename_counter"}],
        }
