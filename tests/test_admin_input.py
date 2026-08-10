import pytest

from imgbot.handlers.admin import parse_administrator_input


def test_admin_input_accepts_id_and_name_on_separate_lines() -> None:
    assert parse_administrator_input("123456789\n张三") == (123456789, "张三")


def test_admin_input_allows_empty_name() -> None:
    assert parse_administrator_input("123456789") == (123456789, None)
    assert parse_administrator_input("123456789\n") == (123456789, None)


@pytest.mark.parametrize("value", ["", "abc\n张三", "-1\n张三", "1\n张三\n额外行"])
def test_admin_input_rejects_invalid_format(value: str) -> None:
    with pytest.raises(ValueError):
        parse_administrator_input(value)
