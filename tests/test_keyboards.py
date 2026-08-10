from imgbot.keyboards import admin_menu


def callback_values(is_super_admin: bool) -> set[str]:
    keyboard = admin_menu(True, is_super_admin=is_super_admin)
    return {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def test_super_admin_sees_all_management_entries() -> None:
    values = callback_values(is_super_admin=True)
    assert {"admin:stats", "admin:verify", "admin:admins"} <= values
    assert {"admin:template", "admin:buttons", "admin:export", "admin:unbind"} <= values


def test_regular_admin_does_not_see_privileged_entries() -> None:
    values = callback_values(is_super_admin=False)
    assert "admin:stats" not in values
    assert "admin:verify" not in values
    assert "admin:admins" not in values
    assert {"admin:template", "admin:buttons", "admin:export", "admin:unbind"} <= values
