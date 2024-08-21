import os
from fastapi import FastAPI, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, Column, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from svix.webhooks import Webhook, WebhookVerificationError
from dotenv import load_dotenv
import aiofiles
import json
from pathlib import Path

# Load environment variables from a .env file
load_dotenv()

# Environment variables for database URL and Svix secret
DATABASE_URL = os.getenv("DATABASE_URL")
SVIX_SECRET = os.getenv("SVIX_SECRET")

# Database setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Define the User model
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, index=True, nullable=True)
    profile_picture_url = Column(String, nullable=True)

# Create all tables in the database
Base.metadata.create_all(bind=engine)

app = FastAPI()

# Dependency for database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Endpoint to handle Svix webhooks
@app.post("/webhook")
async def handle_webhook(request: Request, db: Session = Depends(get_db)):
    headers = {
        "svix-id": request.headers.get("svix-id"),
        "svix-timestamp": request.headers.get("svix-timestamp"),
        "svix-signature": request.headers.get("svix-signature"),
    }

    try:
        payload = await request.body()
        wh = Webhook(SVIX_SECRET)
        json_payload = wh.verify(payload, headers)
    except WebhookVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = json_payload.get("type")
    user_data = json_payload.get("data", {}).get("object", {})

    if event_type in ["user.created", "user.updated"]:
        user_id = user_data.get("id")
        email = user_data.get("email_addresses")[0]["email_address"]
        username = user_data.get("username", None)
        profile_picture_url = user_data.get("profile_image_url", None)

        db_user = db.query(User).filter(User.id == user_id).first()
        if db_user:
            db_user.email = email
            db_user.username = username
            db_user.profile_picture_url = profile_picture_url
        else:
            new_user = User(id=user_id, email=email, username=username, profile_picture_url=profile_picture_url)
            db.add(new_user)
        
        db.commit()

    return {"status": "success"}

# Endpoint to get combined JSON data from all subdirectories
@app.get("/games/")
async def get_combined_json():
    combined_data = {"__comment__": "Combined data"}

    base_dir = Path("./games")
    for json_file in base_dir.rglob("data.json"):
        async with aiofiles.open(json_file, 'r') as f:
            data = await f.read()
            parsed_data = json.loads(data)
            combined_data.update(parsed_data)

    return combined_data

# Endpoint to get a specific JSON file from a subdirectory
@app.get("/games/{dir_name}")
async def get_json_file(dir_name: str):
    json_path = Path(f"./games/{dir_name}/data.json")
    if json_path.exists():
        async with aiofiles.open(json_path, 'r') as f:
            data = await f.read()
            return json.loads(data)
    else:
        raise HTTPException(status_code=404, detail="File not found")


# Endpoint to get user data by user_id
@app.get("/user/{user_id}/data")
async def get_user_data(user_id: str, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user:
        return {
            "id": db_user.id,
            "email": db_user.email,
            "username": db_user.username,
            "profile_picture_url": db_user.profile_picture_url,
        }
    else:
        raise HTTPException(status_code=404, detail="User not found")
