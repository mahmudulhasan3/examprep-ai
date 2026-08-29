from app.db.database import Base, engine
from app.db.models import User, ChatSession, ChatMessage, Exam, Question, Answer, Result

Base.metadata.create_all(bind=engine)

print("Database created successfully")
