from aware.app.parser.nl_parser import parse_rule


def test_parse_sound_trigger() -> None:
    rule = parse_rule("doorbell", "when doorbell rings", "say welcome")
    assert any(t.type == "sound" and t.value == "doorbell" for t in rule.triggers)


def test_parse_detection_trigger() -> None:
    rule = parse_rule("person_alert", "when someone walks in", "flash green")
    assert any(t.type == "detection" and t.value == "person" for t in rule.triggers)


def test_parse_time_trigger() -> None:
    rule = parse_rule("night_alert", "when glass breaks after 10pm", "sound alarm")
    assert any(t.type == "time" for t in rule.triggers)
    assert any(t.type == "sound" and t.value == "glass_break" for t in rule.triggers)


def test_parse_actions() -> None:
    rule = parse_rule("greet", "when person detected", "say welcome and flash green")
    action_types = {a.type for a in rule.actions}
    assert "speak" in action_types
    assert "led_flash" in action_types


def test_parse_telegram_action() -> None:
    rule = parse_rule("alert", "when intruder", "notify me")
    assert any(a.type == "telegram" for a in rule.actions)


def test_parse_no_match_defaults_to_log() -> None:
    rule = parse_rule("custom", "something random", "something else")
    assert any(a.type == "log" for a in rule.actions)
