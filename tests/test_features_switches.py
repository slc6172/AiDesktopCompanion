"""Every switch on `Features` must be read by something. A switch nobody reads looks like it controls a feature and
silently does nothing (the enabled/disabled state of the character state lives in its own config section, which the
engine reads directly)."""
import dataclasses
import re
from pathlib import Path

import pytest

from companion.features import Features

SOURCES = {p: p.read_text(encoding="utf-8") for p in (Path(__file__).resolve().parent.parent / "companion").glob("*.py")
           if p.name != "features.py"}


@pytest.mark.parametrize("name", [f.name for f in dataclasses.fields(Features)])
def test_every_feature_switch_is_read_somewhere_outside_features_py(name):
    readers = [p.name for p, text in SOURCES.items() if re.search(rf"\.{name}\b", text)]
    assert readers, f"Features.{name} is set but nothing reads it"
