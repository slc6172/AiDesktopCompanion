"""docs/animation-tutorial.md must agree with what the program really looks for: the file names, the five emotions, the
fallback, the outfit rules and the photo rules. The prompts are code blocks the reader copies."""
import re
from pathlib import Path

import pytest

from companion.config import DEFAULT_CONFIG
from companion.engine import EMOTIONS
from companion.imageprep import REFERENCE_LIMIT
from tests.repo_scan import ROOT, mentioned_files_that_do_not_exist

TUTORIAL = (ROOT / "docs" / "animation-tutorial.md").read_text(encoding="utf-8")
CODE_BLOCKS = re.findall(r"```[a-z]*\n(.*?)```", TUTORIAL, re.S)
GENERATED = {"idle.webm", "idle.mp4", "base.png", "outfit.txt", "config.json", "persona.md", "base_916.png"}


@pytest.mark.parametrize("state", ["idle", "thinking", "listening", *[f"talking-{e}" for e in EMOTIONS]])
def test_every_state_clip_the_program_looks_for_is_named_in_the_tutorial(state):
    assert f"`{state}.webm`" in TUTORIAL


def test_it_says_which_clip_stands_in_for_a_missing_one():
    assert "talking-neutral" in TUTORIAL and "idle" in TUTORIAL
    assert re.search(r"talking-\*?.{0,40}(退回|取代|改用).{0,40}talking-neutral", TUTORIAL, re.S)


def test_it_names_the_default_outfit_and_the_folders_the_program_ignores():
    assert f"`{DEFAULT_CONFIG['outfit']['default']}`" in TUTORIAL
    assert "底線" in TUTORIAL and "_草稿" in TUTORIAL


def test_it_gives_the_size_limit_the_base_photo_is_shrunk_to():
    assert str(REFERENCE_LIMIT) in TUTORIAL


def test_the_tools_it_tells_you_to_use_are_where_it_says_they_are():
    assert "animation-tools" in TUTORIAL and "make-clip.bat" in TUTORIAL and "crop-916.bat" in TUTORIAL
    assert mentioned_files_that_do_not_exist(TUTORIAL, GENERATED, search=("", "docs", "animation-tools")) == []


def test_the_prompts_are_in_code_blocks_so_they_can_be_copied():
    joined = "\n".join(CODE_BLOCKS)
    for needle in ("Use the image as the first frame", "Gentle slow breathing", "Speaking casually",
                   "Keep the exact same character"):
        assert needle in joined


def test_the_example_character_in_the_prompts_is_not_tied_to_a_gender_and_is_photographic():
    joined = "\n".join(CODE_BLOCKS)
    assert not re.search(r"\b(girl|woman|boy|man|female|male|she|her|his|him|he)\b", joined, re.I)
    assert "photo" in joined.lower()


def test_it_is_honest_that_realistic_faces_are_refused_more_often_by_some_generators():
    assert "寫實" in TUTORIAL and "拒絕" in TUTORIAL


def test_the_old_readmes_are_replaced_by_short_ones_that_point_here():
    assert not (ROOT / "clips" / "README.txt").exists() and not (ROOT / "fillers" / "README.txt").exists()
    for folder in ("clips", "fillers"):
        assert "animation-tutorial" in (ROOT / folder / "README.md").read_text(encoding="utf-8")
