class DomainError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code, self.code, self.message = status_code, code, message
        super().__init__(message)

def not_found(entity: str): return DomainError(404, "NOT_FOUND", f"{entity} not found.")
def invalid(code: str, message: str): return DomainError(422, code, message)
def conflict(code: str, message: str): return DomainError(409, code, message)
