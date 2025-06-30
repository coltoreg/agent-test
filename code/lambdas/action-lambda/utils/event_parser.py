def parse_event(event):
    parameters = event.get("parameters", [])
    session_attributes = event.get("sessionAttributes", {})
    return parameters, session_attributes