import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.exceptions import DomainError
from app.routers import appointments, doctors, patients
from fastapi.responses import RedirectResponse

app = FastAPI(title="Clinic Booking API", version="1.0.0")
logger = logging.getLogger(__name__)
app.include_router(doctors.router)
app.include_router(appointments.router)
app.include_router(patients.router)

@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    issues = exc.errors()
    message = "; ".join(f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}" for e in issues)
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": message}})

@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    code_by_status = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    message_by_status = {
        404: "The requested resource was not found.",
        405: "The request method is not allowed for this resource.",
    }
    code = code_by_status.get(exc.status_code, "HTTP_ERROR")
    message = message_by_status.get(exc.status_code, str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": message}}, headers=exc.headers)

@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.error("Unhandled server error", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_SERVER_ERROR", "message": "An unexpected server error occurred."}})

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")

@app.get("/health", tags=["system"])
def health():
    # Keep this lightweight endpoint available for service health checks.
    return {"status": "ok"}
