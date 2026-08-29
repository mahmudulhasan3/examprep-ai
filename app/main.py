from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def root():
    return {"message": "ExamPrep AI API is running"}
