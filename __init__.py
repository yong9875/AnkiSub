# -*- coding: utf-8 -*-
"""
AnkiSub - 现代轻量影视切片制卡插件
Author: Nebula PC
Description: 纯粹高效的影视音频与封面截图切片插件，支持多语字幕对齐与内嵌轨提取。
"""

from aqt import mw
from aqt.qt import QAction
from aqt.utils import showInfo

# Defensive patch for Anki 26.09 Qt6 legacy editor cleanup bug
def _patch_anki26_legacy_editor_cleanup():
    try:
        from aqt import editcurrent_legacy
        orig_ec = editcurrent_legacy.EditCurrent.cleanup

        def _safe_ec_cleanup(self, *args, **kwargs):
            try:
                return orig_ec(self, *args, **kwargs)
            except RuntimeError:
                pass

        editcurrent_legacy.EditCurrent.cleanup = _safe_ec_cleanup
    except Exception:
        pass

    try:
        from aqt import editor_legacy
        orig_ed = editor_legacy.Editor.cleanup

        def _safe_ed_cleanup(self, *args, **kwargs):
            try:
                return orig_ed(self, *args, **kwargs)
            except RuntimeError:
                pass

        editor_legacy.Editor.cleanup = _safe_ed_cleanup
    except Exception:
        pass

_patch_anki26_legacy_editor_cleanup()

MODEL_NAME = "AnkiSub (Audio+Image)"

MODEL_CSS = """
.card {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 20px;
  text-align: center;
  color: #212121;
  background-color: #fdfdfd;
}
.nightMode.card {
  color: #e0e0e0;
  background-color: #1e1e1e;
}
.container {
  max-width: 680px;
  margin: 15px auto;
  padding: 10px;
}
.expression {
  font-size: 21px;
  font-weight: 600;
  line-height: 1.45;
  margin: 14px 4px 10px 4px;
  text-align: left;
  color: #1565c0;
}
.nightMode .expression {
  color: #64b5f6;
}
.translation {
  font-size: 19px;
  color: #37474f;
  line-height: 1.45;
  margin: 10px 4px 12px 4px;
  text-align: left;
}
.nightMode .translation {
  color: #cfd8dc;
}
.image {
  margin-top: 10px;
  text-align: center;
}
.image img {
  max-width: 320px;
  max-height: 200px;
  height: auto;
  border-radius: 6px;
  box-shadow: 0 3px 10px rgba(0,0,0,0.15);
}
.extra-field {
  text-align: left;
  font-size: 15px;
  background: rgba(0, 0, 0, 0.03);
  border-left: 3px solid #1976d2;
  padding: 8px 12px;
  margin: 10px auto;
  border-radius: 4px;
  line-height: 1.5;
}
.extra-field-title {
  font-weight: 600;
  font-size: 13px;
  color: #1976d2;
  margin-bottom: 4px;
}
.nightMode .extra-field {
  background: rgba(255, 255, 255, 0.05);
  border-left-color: #64b5f6;
  color: #e0e0e0;
}
.nightMode .extra-field-title {
  color: #64b5f6;
}
hr#answer {
  border: 0;
  height: 1px;
  background: #e0e0e0;
  margin: 16px 0;
}
.nightMode hr#answer {
  background: #333333;
}
"""

FRONT_TEMPLATE = """
<div class="container">
  {{#Image}}
  <div class="image">{{Image}}</div>
  {{/Image}}
  <div class="expression">{{Expression}}</div>
</div>
"""

BACK_TEMPLATE = """
<div class="container">
  {{#Image}}
  <div class="image">{{Image}}</div>
  {{/Image}}
  <div class="expression">{{Expression}}</div>
  <hr id="answer">
  <div class="audio">{{Audio}}</div>
  {{#Translation}}
  <div class="translation">{{Translation}}</div>
  {{/Translation}}
  {{#Words}}
  <div class="extra-field">
    <div class="extra-field-title">生词 / 词汇翻译</div>
    {{Words}}
  </div>
  {{/Words}}
  {{#Notes}}
  <div class="extra-field">
    <div class="extra-field-title">笔记 / 感想</div>
    {{Notes}}
  </div>
  {{/Notes}}
</div>
"""


def _migrate_existing_notes(col, model):
    """Automatically fix and restore any existing notes whose field contents were misplaced."""
    try:
        import re
        nids = col.find_notes(f"mid:{model['id']}")
        for nid in nids:
            note = col.get_note(nid)
            vals = list(note.values())
            audio = ""
            img = ""
            time_val = ""
            src = ""
            expr = ""
            trans = ""

            for v in vals:
                v_str = str(v).strip()
                if not v_str:
                    continue
                if v_str.startswith("[sound:") and v_str.endswith("]"):
                    audio = v_str
                elif "<img src=" in v_str:
                    img = v_str
                elif re.search(r"\d{2}:\d{2}:\d{2}[\.,]\d{3}\s*-\s*\d{2}:\d{2}:\d{2}", v_str):
                    time_val = v_str
                elif ("." in v_str and not " " in v_str) or "1080p" in v_str or "720p" in v_str or "BluRay" in v_str:
                    src = v_str
                elif not expr:
                    expr = v_str
                elif not trans and not v_str.startswith("[sound:") and not v_str.startswith("<img"):
                    trans = v_str

            cur_audio = note["Audio"] if "Audio" in note else ""
            cur_img = note["Image"] if "Image" in note else ""
            cur_words = note["Words"] if "Words" in note else ""
            cur_notes = note["Notes"] if "Notes" in note else ""
            cur_trans = note["Translation"] if "Translation" in note else ""

            needs_fix = False
            if audio and cur_audio != audio:
                needs_fix = True
            if img and cur_img != img:
                needs_fix = True
            if cur_words.startswith("[sound:") or cur_words.startswith("<img") or cur_words == src:
                needs_fix = True
            if cur_notes.startswith("[sound:") or cur_notes.startswith("<img") or cur_notes == time_val:
                needs_fix = True
            if cur_trans.startswith("<img") or cur_trans.startswith("[sound:"):
                needs_fix = True

            if needs_fix:
                if "Expression" in note and expr:
                    note["Expression"] = expr
                if "Words" in note and (cur_words.startswith("[sound:") or cur_words.startswith("<img") or cur_words == src):
                    note["Words"] = ""
                if "Notes" in note and (cur_notes.startswith("[sound:") or cur_notes.startswith("<img") or cur_notes == time_val):
                    note["Notes"] = ""
                if "Translation" in note:
                    note["Translation"] = "" if (cur_trans.startswith("<img") or cur_trans.startswith("[sound:")) else trans
                if "Audio" in note and audio:
                    note["Audio"] = audio
                if "Image" in note and img:
                    note["Image"] = img
                if "Source" in note and src:
                    note["Source"] = src
                if "Time" in note and time_val:
                    note["Time"] = time_val
                col.update_note(note)
    except Exception as e:
        print(f"[AnkiSub] Note auto-repair error: {e}")


def ensure_note_model():
    """Ensure the default AnkiSub (Audio+Image) note type exists, fields are ordered, and template is updated."""
    col = mw.col
    if not col:
        return

    desired_order = ["Expression", "Words", "Notes", "Translation", "Audio", "Image", "Source", "Time"]
    model = col.models.by_name(MODEL_NAME)
    if model is None:
        # Create new model
        model = col.models.new(MODEL_NAME)
        model['css'] = MODEL_CSS.strip()

        # Add fields in desired order
        for f_name in desired_order:
            fld = col.models.new_field(f_name)
            col.models.add_field(model, fld)

        # Add Card template
        tmpl = col.models.new_template("Card 1")
        tmpl['qfmt'] = FRONT_TEMPLATE.strip()
        tmpl['afmt'] = BACK_TEMPLATE.strip()
        col.models.add_template(model, tmpl)

        col.models.add(model)
        col.models.save(model)
    else:
        # Ensure Words and Notes exist in existing model
        existing = col.models.field_names(model)
        for f_name in ["Words", "Notes"]:
            if f_name not in existing:
                fld = col.models.new_field(f_name)
                col.models.add_field(model, fld)

        # Reorder fields in editor so Words and Notes are right under Expression
        fld_map = {f['name']: f for f in model.get('flds', [])}
        reordered = []
        for name in desired_order:
            if name in fld_map:
                reordered.append(fld_map.pop(name))
        for remaining in fld_map.values():
            reordered.append(remaining)
        for idx, f in enumerate(reordered):
            if 'ord' in f:
                f['ord'] = idx
        model['flds'] = reordered

        # Update existing model's card template and css
        tmpls = model.get('tmpls', [])
        if tmpls:
            tmpls[0]['qfmt'] = FRONT_TEMPLATE.strip()
            tmpls[0]['afmt'] = BACK_TEMPLATE.strip()
            model['css'] = MODEL_CSS.strip()
            col.models.save(model)

        # Auto-repair existing notes that may have been shifted
        _migrate_existing_notes(col, model)


dialog_instance = None


def open_dialog():
    global dialog_instance
    ensure_note_model()

    from .ui_dialog import AnkiSubDialog
    if dialog_instance is None:
        dialog_instance = AnkiSubDialog(mw)
    
    dialog_instance.show()
    dialog_instance.raise_()
    dialog_instance.activateWindow()


def init_addon():
    action = QAction("AnkiSub 影视切片制卡...", mw)
    action.triggered.connect(open_dialog)
    mw.form.menuTools.addAction(action)

    try:
        from aqt import gui_hooks
        gui_hooks.profile_did_open.append(ensure_note_model)
    except Exception:
        pass


# Initialize menu
init_addon()
