from fastapi import FastAPI
from app.models.company import Company

app = FastAPI(title="alfa_llm")



@app.get("/health")
def root():
    return {"status": "ok",
            "message": "app is running"
            }

@app.post("/research")
def create_company(company: Company):
    return {
    "status" :"accepted",
    "company_name":company.name, 
    "message": "Компания принята",
    "company": company.model_dump()
}