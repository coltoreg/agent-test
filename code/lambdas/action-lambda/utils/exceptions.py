class ActionLambdaError(Exception):
    """Base Exception for Action Lambda"""
    pass

class ValidationError(ActionLambdaError):
    """Raised when input validation fails"""
    pass

class DatabaseQueryError(ActionLambdaError):
    """Raised when database query fails"""
    pass

class ExternalAPIError(ActionLambdaError):
    """Raised when calling external API fails"""
    pass

class UserInputError(ActionLambdaError):
    """Raised when user provides invalid input"""
    pass
