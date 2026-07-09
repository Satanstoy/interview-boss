from app.agents.chat.state import ChatState


def test_chat_state_has_turn_action():
    """ChatState 类型注解应包含 turn_action 字段。"""
    annotations = ChatState.__annotations__
    assert "turn_action" in annotations, "turn_action 字段缺失"
    assert "turn_reason" in annotations, "turn_reason 字段缺失"


def test_chat_state_has_generation_error():
    """ChatState 类型注解应包含 generation_error 字段。"""
    annotations = ChatState.__annotations__
    assert "generation_error" in annotations, "generation_error 字段缺失"


def test_chat_state_has_natural_question_text():
    """ChatState 类型注解应包含 natural_question_text 字段。"""
    annotations = ChatState.__annotations__
    assert "natural_question_text" in annotations, "natural_question_text 字段缺失"


def test_chat_state_has_question_intent():
    """ChatState 类型注解应包含 question_intent 字段。"""
    annotations = ChatState.__annotations__
    assert "question_intent" in annotations, "question_intent 字段缺失"
