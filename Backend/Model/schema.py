from pydantic import BaseModel,Field,EmailStr
from typing import Annotated,Literal,Optional
from datetime import datetime,timezone
from bson import ObjectId
from enum import Enum

class User(BaseModel) :
    id : str
    first_name : Annotated[str,Field(...,min_length=2,max_length=100,description="Add Your First Name",examples=["Max"])]
    last_name : Annotated[str,Field(...,min_length=2,max_length=100,description="Add Your Last Name",examples=["Verstappen"])]
    email : Annotated[EmailStr,Field(...,description="Enter Valid Email",examples=["max123@gmail.com"])]
    password : Annotated[str,Field(...,min_length=8,description="Password contain min 8 char,1 uppercase,1 special character and number",examples=["Max#1234"])]
    createdAt : datetime=Field(default_factory=lambda: datetime.now(timezone.utc))
    updatedAt : datetime=Field(default_factory=lambda: datetime.now(timezone.utc))

class Create_user(BaseModel) :
    first_name : Annotated[str,Field(...,min_length=2,max_length=100,description="Add Your First Name",examples=["Max"])]
    last_name : Annotated[str,Field(...,min_length=2,max_length=100,description="Add Your Last Name",examples=["Verstappen"])]
    email : Annotated[EmailStr,Field(...,description="Enter Valid Email",examples=["max123@gmail.com"])]
    password : Annotated[str,Field(...,min_length=8,description="Password contain min 8 char,1 uppercase,1 special character and number",examples=["Max#1234"])]

class Login_user(BaseModel) :
    email : Annotated[EmailStr,Field(...,description="Enter Valid Email",examples=["max123@gmail.com"])]
    password : Annotated[str,Field(...,min_length=8,description="Password contain min 8 char,1 uppercase,1 special character and number",examples=["Max#1234"])]

class Update_user(BaseModel) :
    first_name: str | None = Field(default=None, min_length=2, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email : EmailStr | None = Field(default=None)

class Update_password(BaseModel) :
    oldpassword : Annotated[str,Field(..., examples=["Abc@1234"])]
    newpassword: Annotated[str,Field(..., min_length=8 , examples=["Bac@1234"])]

class RefreshTokenRequest(BaseModel):
    refresh_token: Annotated[str, Field(..., description="Refresh token to obtain a new access token", examples=["your_refresh_token_here"])]

class CreateConversation(BaseModel):
    title : Annotated[str,Field(...,min_length=2,max_length=200,description="Enter Conversation Title",examples=["Artificial Intelligence(AI)"])]

class CreateMessages(BaseModel) :
    content : Annotated[str,Field(...,min_length=1,max_length=1000,description="Enter Your Message",examples=["Hello! How can I assist you today?"])]


class MessageStatus(str,Enum) :
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"




