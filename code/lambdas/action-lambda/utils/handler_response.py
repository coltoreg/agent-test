from typing import Any, Dict

class HandlerResponse:
    def __init__(self, result: Any, session_attributes: Dict[str, Any]):
        self.result = result
        self.session_attributes = session_attributes

    def to_tuple(self):
        return self.result, self.session_attributes
