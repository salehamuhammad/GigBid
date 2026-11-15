from agent.guardrails import mask_obj


def test_numeric_token_usage_is_visible_but_credentials_are_redacted():
    assert mask_obj({
        "usage": {"input_tokens": 25, "output_tokens": 10, "total_tokens": 35},
        "access_token": "credential",
        "apiKey": "credential",
        "nested": {"input_tokens": "credential", "output_tokens": True},
    }) == {
        "usage": {"input_tokens": 25, "output_tokens": 10, "total_tokens": 35},
        "access_token": "[secret]",
        "apiKey": "[secret]",
        "nested": {"input_tokens": "[secret]", "output_tokens": "[secret]"},
    }
