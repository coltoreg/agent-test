def get_parameter_value(parameters, param_name):
    for param in parameters:
        if param.get("name") == param_name:
            return param.get("value")
    return None