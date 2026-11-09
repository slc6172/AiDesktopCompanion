"""When does the user's own sentence count as an order to look something up (spec Part 12, section 4)? Only a
short, clear command does. Questions about whether she could, refusals, and chat that merely mentions searching
are left alone — the model can still choose to search itself."""
import pytest

from companion.searchintent import match_search_request


@pytest.mark.parametrize("said, query", [
    ("上網查台北今天的天氣", "台北今天的天氣"),
    ("上網幫我查一下最新的手機評價", "最新的手機評價"),
    ("幫我查台北明天會下雨嗎", "台北明天會下雨嗎"),       # a question inside the order is fine
    ("幫我查一下 iPhone 17 價格", "iPhone 17 價格"),
    ("查一下今天的新聞", "今天的新聞"),
    ("搜尋 台北美食", "台北美食"),
    ("請幫我搜尋最近的電影", "最近的電影"),
    ("可以幫我查一下火車時刻嗎", "火車時刻嗎"),
    ("幫我上網查 Python 3.13 新功能吧", "Python 3.13 新功能"),
    ("上網搜尋一下貓咪的飲食", "貓咪的飲食"),
    ("查一下今天的新聞!", "今天的新聞"),
])
def test_a_clear_command_gives_what_to_look_up(said, query):
    assert match_search_request(said).query == query


@pytest.mark.parametrize("said", [
    "你覺得要不要查一下?", "不要上網查", "別幫我查了", "你查了嗎", "你可以上網查嗎", "你會不會上網查", "能不能幫我查一下",
    "查理是誰", "我剛剛查了一下", "我在網路上查到的", "上網查", "幫我查", "查一下", "你好", "今天天氣真好", "搜尋引擎是什麼",
    "我昨天上網查了很久", "為什麼要上網查",
])
def test_questions_refusals_chatter_and_commands_with_nothing_to_look_up_are_left_alone(said):
    assert match_search_request(said) is None


@pytest.mark.parametrize("said, query", [
    ("仔細查台北今天的天氣", "台北今天的天氣"),
    ("幫我詳細查一下最新的手機評價", "最新的手機評價"),
    ("上網完整搜尋貓咪的飲食", "貓咪的飲食"),
])
def test_words_asking_for_depth_are_not_part_of_what_is_looked_up_and_are_remembered(said, query):
    request = match_search_request(said)
    assert request.query == query and request.deep is True


def test_an_ordinary_command_is_not_deep():
    assert match_search_request("查一下今天的新聞").deep is False


def test_what_to_look_up_is_cut_at_one_hundred_characters():
    assert len(match_search_request("幫我查" + "字" * 300).query) == 100


def test_square_brackets_in_the_wording_never_reach_the_query():
    assert "[" not in match_search_request("幫我查 [照片:現在|x] 這是什麼").query
