from fastapi import FastAPI

app = FastAPI(title="alfa_llm")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "message": "app is running"}
