import pytest

from imgbot.service import BotService


def test_parse_button_definition_supports_two_columns() -> None:
    rows = BotService.parse_button_definition(
        "1|1|活动列表|https://example.com/events\n"
        "2|1|VIP群|https://t.me/vip\n"
        "2|2|官方频道|https://t.me/official"
    )
    assert rows == [
        [("活动列表", "https://example.com/events")],
        [("VIP群", "https://t.me/vip"), ("官方频道", "https://t.me/official")],
    ]


def test_parse_button_definition_rejects_unsafe_url() -> None:
    with pytest.raises(ValueError, match="URL"):
        BotService.parse_button_definition("1|1|危险|javascript:alert(1)")


def test_parse_button_definition_rejects_malformed_hostname() -> None:
    with pytest.raises(ValueError, match="URL"):
        BotService.parse_button_definition("1|1|错误邀请链接|https://t.me+invite")


def test_build_keyboard_skips_invalid_historical_button() -> None:
    from imgbot.models import TemplateButton

    keyboard = BotService.build_keyboard(
        [
            TemplateButton(
                id=1,
                bot_instance_id=1,
                text="错误链接",
                url="https://t.me+invite",
                row_number=0,
                column_number=0,
            ),
            TemplateButton(
                id=2,
                bot_instance_id=1,
                text="正确链接",
                url="https://t.me/+invite",
                row_number=0,
                column_number=1,
            ),
        ]
    )

    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    assert [button.text for button in keyboard.inline_keyboard[0]] == ["正确链接"]


def test_template_only_accepts_supported_fields() -> None:
    BotService.validate_template("你好 {display_name}，编号 {tg_id}")
    with pytest.raises(ValueError, match="不支持的变量"):
        BotService.validate_template("{unknown_field}")


def test_start_page_text_rejects_more_than_photo_caption_limit() -> None:
    with pytest.raises(ValueError, match="1024"):
        BotService.validate_start_page_text("x" * 1025)
