from fastapi import FastAPI,Request
import uuid
import time 
from datetime import datetime
import uvicorn
from APIs.route import api_router  
import logging
from config.logging_config import configure_logging, request_id_var

configure_logging()
logger = logging.getLogger("app")

app = FastAPI(title="Chatbot Api" ,version="1.0.0")
logger.info("Application initialized successfully")

@app.middleware("http")
async def logging_middleware(request: Request, call_next):

    request_id = str(uuid.uuid4())
    token = request_id_var.set(request_id)

    start_time = time.perf_counter()

    try:
        response = await call_next(request)

        duration_ms = round(
            (time.perf_counter() - start_time) * 1000, 2
        )

        logger.info(
            "Request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
        )

        response.headers["X-Request-ID"] = request_id

        return response

    except Exception:
        logger.exception(
            "Request failed",
            extra={
                "method": request.method,
                "path": request.url.path,
            }
        )
        raise

    finally:
        request_id_var.reset(token)

app.include_router(api_router , prefix="/api")

@app.get('/')
def home() :
    return {'status' : 'ok',
            'statuscode' : 200,
            'message' : 'server run smoothly',
            'Timestamp' : datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

@app.get('/health')
def health() :
    return {'health' : 'Good',
            'statuscode' : 200}


if __name__=="__main__" :
    uvicorn.run("main:app",host="127.0.0.1",port=5000,reload=True)