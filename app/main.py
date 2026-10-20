from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.exceptions import DomainError
from app.routers import appointments, doctors, patients

app = FastAPI(title="Clinic Booking API", version="1.0.0")
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

@app.get("/health", tags=["system"])
def health():
    # Keep this lightweight endpoint available for service health checks.
    return {"status": "ok"}
