import os
import uvicorn
from .api import create_app

app=create_app()

def main():
    uvicorn.run('assetsx_engine.server:app',host='0.0.0.0',port=int(os.getenv('PORT','8000')),workers=1)
if __name__=='__main__':main()
