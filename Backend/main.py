from fastapi import FastAPI
from datetime import datetime
import uvicorn
from APIs.route import api_router  

app = FastAPI(title="Chatbot Api" ,version="1.0.0")

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